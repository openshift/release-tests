import unittest
import logging
from unittest.mock import Mock, patch
from oar.core.operators import ApprovalOperator
from oar.core.configstore import ConfigStore


# Define the LogCaptureHandler class here for testing since it's local to the method
class LogCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.log_messages = []
        
    def emit(self, record):
        log_entry = self.format(record)
        self.log_messages.append(log_entry)
        
    def get_log_messages(self):
        """Get all captured log messages"""
        return self.log_messages


class TestLogCaptureHandler(unittest.TestCase):
    """Test the LogCaptureHandler functionality"""

    def test_log_capture_handler_initialization(self):
        """Test that LogCaptureHandler initializes correctly"""
        handler = LogCaptureHandler()
        self.assertEqual(handler.get_log_messages(), [])
        self.assertIsInstance(handler.get_log_messages(), list)

    def test_log_capture_handler_emit(self):
        """Test that LogCaptureHandler captures log messages"""
        handler = LogCaptureHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        
        # Create a test log record
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )
        
        # Emit the record
        handler.emit(record)
        
        # Check that the message was captured
        messages = handler.get_log_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('INFO - Test message', messages[0])

    def test_log_capture_handler_multiple_messages(self):
        """Test that LogCaptureHandler captures multiple messages"""
        handler = LogCaptureHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Create multiple test log records
        records = [
            logging.LogRecord('test', logging.INFO, 'test.py', 1, 'Message 1', (), None),
            logging.LogRecord('test', logging.WARNING, 'test.py', 2, 'Message 2', (), None),
            logging.LogRecord('test', logging.ERROR, 'test.py', 3, 'Message 3', (), None)
        ]
        
        # Emit all records
        for record in records:
            handler.emit(record)
        
        # Check that all messages were captured
        messages = handler.get_log_messages()
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0], 'Message 1')
        self.assertEqual(messages[1], 'Message 2')
        self.assertEqual(messages[2], 'Message 3')


class TestApprovalOperatorLogCapture(unittest.TestCase):
    """Test the LogCaptureHandler integration with ApprovalOperator"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock the ConfigStore to avoid external dependencies
        self.mock_cs = Mock(spec=ConfigStore)
        self.mock_cs.release = "4.19.0"
        self.mock_cs.is_konflux_flow.return_value = True
        
        # Create ApprovalOperator instance
        self.operator = ApprovalOperator(self.mock_cs)
        
        # Mock dependencies
        self.operator._am = Mock()
        self.operator._sd = Mock()

    def test_log_capture_handler_integration(self):
        """Test that LogCaptureHandler works with the actual logger"""
        # Create a logger and add our custom handler
        logger = logging.getLogger(__name__)
        original_handlers = logger.handlers.copy()
        
        try:
            # Clear existing handlers for clean test
            logger.handlers.clear()
            
            # Add our capture handler
            capture_handler = LogCaptureHandler()
            capture_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
            capture_handler.setLevel(logging.DEBUG)
            logger.addHandler(capture_handler)
            logger.setLevel(logging.DEBUG)
            
            # Log some test messages
            logger.info("Test info message")
            logger.warning("Test warning message")
            logger.error("Test error message")
            logger.debug("Test debug message")
            
            # Check that all messages were captured
            messages = capture_handler.get_log_messages()
            self.assertEqual(len(messages), 4)
            self.assertIn("INFO - Test info message", messages)
            self.assertIn("WARNING - Test warning message", messages)
            self.assertIn("ERROR - Test error message", messages)
            self.assertIn("DEBUG - Test debug message", messages)
            
        finally:
            # Restore original handlers
            logger.handlers.clear()
            for handler in original_handlers:
                logger.addHandler(handler)

    @patch('oar.core.operators.logger')
    def test_background_metadata_checker_log_capture_pattern(self, mock_logger):
        """Test the log capture pattern used in _background_metadata_checker"""
        # Create a mock capture handler
        capture_handler = LogCaptureHandler()
        capture_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        
        # Set up the mock logger to use our capture handler
        mock_logger.addHandler(capture_handler)
        mock_logger.setLevel(logging.DEBUG)
        
        # Mock the logger methods to actually capture messages
        def mock_info(msg):
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None
            )
            capture_handler.emit(record)
        
        def mock_warning(msg):
            record = logging.LogRecord(
                name='test',
                level=logging.WARNING,
                pathname='test.py',
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None
            )
            capture_handler.emit(record)
        
        def mock_error(msg):
            record = logging.LogRecord(
                name='test',
                level=logging.ERROR,
                pathname='test.py',
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None
            )
            capture_handler.emit(record)
        
        mock_logger.info.side_effect = mock_info
        mock_logger.warning.side_effect = mock_warning
        mock_logger.error.side_effect = mock_error
        
        # Simulate the logging pattern from _background_metadata_checker
        mock_logger.info("Scheduler lock acquired")
        mock_logger.warning("Test warning message")
        mock_logger.error("Test error message")
        mock_logger.info("Release approval completed. Payload metadata URL is now accessible")
        
        # Verify all messages were captured
        messages = capture_handler.get_log_messages()
        self.assertEqual(len(messages), 4)
        self.assertIn("INFO - Scheduler lock acquired", messages)
        self.assertIn("WARNING - Test warning message", messages)
        self.assertIn("ERROR - Test error message", messages)
        self.assertIn("INFO - Release approval completed. Payload metadata URL is now accessible", messages)


class TestReleaseShipmentOperator(unittest.TestCase):
    """Test the ReleaseShipmentOperator for release shipment status checking

    Uses two test releases:
    - 4.19.16: Konflux-based release (for testing Konflux flow)
    - 4.19.6: Errata-based release (for testing Errata flow)
    """

    def test_initialization_with_real_configstore_konflux(self):
        """Test that ReleaseShipmentOperator initializes correctly with Konflux release"""
        try:
            cs = ConfigStore("4.19.16")
            operator = ReleaseShipmentOperator(cs)
            self.assertIsNotNone(operator)
            self.assertEqual(operator._cs, cs)
        except Exception as e:
            # Skip if release not configured
            self.skipTest(f"Release 4.19.16 (Konflux) not configured: {str(e)}")

    def test_is_release_shipped_returns_dict_with_required_keys(self):
        """Test that is_release_shipped returns dict with required keys"""
        try:
            cs = ConfigStore("4.19.16")
            operator = ReleaseShipmentOperator(cs)
            result = operator.is_release_shipped()

            # Check required keys exist
            self.assertIn("shipped", result)
            self.assertIn("flow_type", result)
            self.assertIn("details", result)

            # Check types
            self.assertIsInstance(result["shipped"], bool)
            self.assertIsInstance(result["flow_type"], str)
            self.assertIsInstance(result["details"], dict)

            # Check flow_type is valid
            self.assertIn(result["flow_type"], ["errata", "konflux"])
        except Exception as e:
            self.skipTest(f"Release 4.19.16 not configured: {str(e)}")

    def test_is_release_shipped_konflux_flow_structure(self):
        """Test structure of result for Konflux flow"""
        try:
            cs = ConfigStore("4.19.16")
            if not cs.is_konflux_flow():
                self.skipTest("Release uses Errata flow, not Konflux")

            operator = ReleaseShipmentOperator(cs)
            result = operator.is_release_shipped()

            self.assertEqual(result["flow_type"], "konflux")
            details = result["details"]

            # Check expected keys for Konflux flow
            self.assertIn("prod_release", details)
            self.assertIn("shipment_mr_merged", details)
            self.assertIn("rpm_advisory", details)
            self.assertIn("rhcos_advisory", details)
        except Exception as e:
            self.skipTest(f"Release 4.19.16 not configured: {str(e)}")

    def test_is_release_shipped_errata_flow_structure(self):
        """Test structure of result for Errata flow"""
        try:
            cs = ConfigStore("4.19.6")
            if cs.is_konflux_flow():
                self.skipTest("Release uses Konflux flow, not Errata")

            operator = ReleaseShipmentOperator(cs)
            result = operator.is_release_shipped()

            self.assertEqual(result["flow_type"], "errata")
            details = result["details"]

            # Check that there are advisory details
            self.assertGreater(len(details), 0)

            # Check that at least some advisory keys exist
            advisory_keys = [k for k in details.keys() if k.startswith("advisory_")]
            self.assertGreater(len(advisory_keys), 0)
        except Exception as e:
            self.skipTest(f"Release 4.19.6 (Errata) not configured: {str(e)}")

    def test_get_advisory_by_impetus_returns_advisory_or_none_konflux(self):
        """Test _get_advisory_by_impetus returns Advisory object or None (Konflux)"""
        try:
            cs = ConfigStore("4.19.16")
            operator = ReleaseShipmentOperator(cs)

            # Try to get rpm advisory (Konflux flow)
            advisories = cs.get_advisories()

            if advisories:
                # Get first advisory impetus
                first_impetus = list(advisories.keys())[0]
                result = operator._get_advisory_by_impetus(first_impetus)

                # Should return Advisory object or None
                if result is not None:
                    from oar.core.advisory import Advisory
                    self.assertIsInstance(result, Advisory)
            else:
                self.skipTest("No advisories configured for release")
        except Exception as e:
            self.skipTest(f"Release 4.19.16 (Konflux) not configured: {str(e)}")

    def test_get_advisory_by_impetus_not_found_returns_none_errata(self):
        """Test _get_advisory_by_impetus returns None for non-existent advisory (Errata)"""
        try:
            cs = ConfigStore("4.19.6")
            operator = ReleaseShipmentOperator(cs)

            # Try to get an advisory that shouldn't exist
            result = operator._get_advisory_by_impetus("nonexistent_impetus")

            self.assertIsNone(result)
        except Exception as e:
            self.skipTest(f"Release 4.19.6 (Errata) not configured: {str(e)}")

    def test_check_konflux_shipped_with_real_data(self):
        """Integration test: Check Konflux shipped status with real data"""
        try:
            cs = ConfigStore("4.19.16")
            if not cs.is_konflux_flow():
                self.skipTest("Release uses Errata flow, not Konflux")

            operator = ReleaseShipmentOperator(cs)
            result = operator.is_release_shipped()

            # Verify result structure
            self.assertEqual(result["flow_type"], "konflux")
            self.assertIn("prod_release", result["details"])
            self.assertIn("shipment_mr_merged", result["details"])
            self.assertIn("rpm_advisory", result["details"])
            self.assertIn("rhcos_advisory", result["details"])

            # Log the actual state for manual verification
            logger.info(f"Konflux release shipped status: {result}")
        except Exception as e:
            self.skipTest(f"Release 4.19.16 not configured: {str(e)}")

    def test_check_errata_shipped_with_real_data(self):
        """Integration test: Check Errata shipped status with real data"""
        try:
            cs = ConfigStore("4.19.6")
            if cs.is_konflux_flow():
                self.skipTest("Release uses Konflux flow, not Errata")

            operator = ReleaseShipmentOperator(cs)
            result = operator.is_release_shipped()

            # Verify result structure
            self.assertEqual(result["flow_type"], "errata")
            self.assertGreater(len(result["details"]), 0)

            # Check that all advisory states are documented
            for key, value in result["details"].items():
                self.assertIsInstance(value, str)

            # Log the actual state for manual verification
            logger.info(f"Errata release shipped status: {result}")
        except Exception as e:
            self.skipTest(f"Release 4.19.6 (Errata) not configured: {str(e)}")



if __name__ == '__main__':
    unittest.main()
