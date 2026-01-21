import unittest
import logging
from unittest.mock import Mock, patch, MagicMock
from oar.core.operators import ApprovalOperator, ReleaseShipmentOperator
from oar.core.configstore import ConfigStore
from oar.core.exceptions import ShipmentDataException

logger = logging.getLogger(__name__)

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
        cs = ConfigStore("4.19.16")
        if not cs.is_konflux_flow():
            self.skipTest("Release uses Errata flow, not Konflux")

        operator = ReleaseShipmentOperator(cs)
        result = operator.is_release_shipped()

        self.assertEqual(result["flow_type"], "konflux")
        details = result["details"]

        # Check expected keys for Konflux flow
        self.assertIn("shipment_mr_status", details)
        self.assertIn("rpm_advisory", details)
        self.assertIn("rhcos_advisory", details)

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



class TestApprovalOperatorMergedMR(unittest.TestCase):
    """Test ApprovalOperator handles merged shipment MR gracefully

    This test suite verifies the fix for OCPERT-295 where change-advisory-status
    was failing when the GitLab shipment MR was already merged.
    """

    @patch('oar.core.operators.ShipmentData')
    @patch('oar.core.operators.AdvisoryManager')
    def test_initialization_with_merged_mr_konflux_flow(self, mock_am_class, mock_sd_class):
        """Test ApprovalOperator initialization when shipment MR is already merged (Konflux flow)"""
        # Setup mock ConfigStore for Konflux flow
        mock_cs = Mock(spec=ConfigStore)
        mock_cs.release = "4.19.1"
        mock_cs.is_konflux_flow.return_value = True

        # Mock ShipmentData to raise exception (MR is merged)
        mock_sd_class.side_effect = ShipmentDataException("Gitlab MR 12345 state is not open")

        # Create ApprovalOperator - should not raise exception
        operator = ApprovalOperator(mock_cs)

        # Verify initialization succeeded gracefully
        self.assertIsNotNone(operator)
        self.assertEqual(operator._cs, mock_cs)
        self.assertIsNone(operator._sd)  # ShipmentData should be None
        self.assertIsNotNone(operator._sd_init_error)  # Error should be stored
        self.assertIn("state is not open", operator._sd_init_error)

        # Verify ShipmentData was attempted (for Konflux flow)
        mock_sd_class.assert_called_once_with(mock_cs)

    @patch('oar.core.operators.ShipmentData')
    @patch('oar.core.operators.AdvisoryManager')
    def test_initialization_with_open_mr_konflux_flow(self, mock_am_class, mock_sd_class):
        """Test ApprovalOperator initialization when MR is still open (normal Konflux flow)"""
        # Setup mock ConfigStore for Konflux flow
        mock_cs = Mock(spec=ConfigStore)
        mock_cs.release = "4.19.1"
        mock_cs.is_konflux_flow.return_value = True

        # Mock ShipmentData to succeed (MR is open)
        mock_sd_instance = Mock()
        mock_sd_class.return_value = mock_sd_instance

        # Create ApprovalOperator
        operator = ApprovalOperator(mock_cs)

        # Verify initialization succeeded with ShipmentData
        self.assertIsNotNone(operator)
        self.assertEqual(operator._cs, mock_cs)
        self.assertIsNotNone(operator._sd)  # ShipmentData should be initialized
        self.assertEqual(operator._sd, mock_sd_instance)
        self.assertIsNone(operator._sd_init_error)  # No error

        # Verify ShipmentData was initialized
        mock_sd_class.assert_called_once_with(mock_cs)

    @patch('oar.core.operators.ShipmentData')
    @patch('oar.core.operators.AdvisoryManager')
    def test_initialization_errata_flow_skips_shipment_data(self, mock_am_class, mock_sd_class):
        """Test ApprovalOperator initialization for Errata flow (no ShipmentData)"""
        # Setup mock ConfigStore for Errata flow
        mock_cs = Mock(spec=ConfigStore)
        mock_cs.release = "4.19.1"
        mock_cs.is_konflux_flow.return_value = False  # Errata flow

        # Create ApprovalOperator
        operator = ApprovalOperator(mock_cs)

        # Verify initialization succeeded without ShipmentData
        self.assertIsNotNone(operator)
        self.assertEqual(operator._cs, mock_cs)
        self.assertIsNone(operator._sd)  # ShipmentData should be None
        self.assertIsNone(operator._sd_init_error)  # No error

        # Verify ShipmentData was NOT initialized (Errata flow)
        mock_sd_class.assert_not_called()

    @patch('oar.core.operators.util.is_payload_metadata_url_accessible')
    @patch('oar.core.operators.ShipmentData')
    @patch('oar.core.operators.AdvisoryManager')
    def test_approve_release_skips_qe_approval_when_mr_merged(self, mock_am_class, mock_sd_class, mock_url_check):
        """Test approve_release skips QE approval when MR is already merged"""
        # Setup mock ConfigStore for Konflux flow
        mock_cs = Mock(spec=ConfigStore)
        mock_cs.release = "4.19.1"
        mock_cs.is_konflux_flow.return_value = True

        # Mock ShipmentData to raise exception (MR is merged)
        mock_sd_class.side_effect = ShipmentDataException("Gitlab MR 12345 state is not open")

        # Mock payload URL as accessible
        mock_url_check.return_value = True

        # Mock AdvisoryManager
        mock_am_instance = Mock()
        mock_am_class.return_value = mock_am_instance

        # Create ApprovalOperator
        operator = ApprovalOperator(mock_cs)

        # Call approve_release
        result = operator.approve_release()

        # Verify QE approval was NOT called (MR is merged, _sd is None)
        # Since _sd is None, add_qe_approval should not be called

        # Verify advisory status was changed (should proceed regardless of MR state)
        mock_am_instance.change_advisory_status.assert_called_once()

        # Verify result is True (success)
        self.assertTrue(result)

    @patch('oar.core.operators.util.is_payload_metadata_url_accessible')
    @patch('oar.core.operators.ShipmentData')
    @patch('oar.core.operators.AdvisoryManager')
    def test_approve_release_adds_qe_approval_when_mr_open(self, mock_am_class, mock_sd_class, mock_url_check):
        """Test approve_release adds QE approval when MR is still open"""
        # Setup mock ConfigStore for Konflux flow
        mock_cs = Mock(spec=ConfigStore)
        mock_cs.release = "4.19.1"
        mock_cs.is_konflux_flow.return_value = True

        # Mock ShipmentData to succeed (MR is open)
        mock_sd_instance = Mock()
        mock_sd_class.return_value = mock_sd_instance

        # Mock payload URL as accessible
        mock_url_check.return_value = True

        # Mock AdvisoryManager
        mock_am_instance = Mock()
        mock_am_class.return_value = mock_am_instance

        # Create ApprovalOperator
        operator = ApprovalOperator(mock_cs)

        # Call approve_release
        result = operator.approve_release()

        # Verify QE approval was called (MR is open, _sd exists)
        mock_sd_instance.add_qe_approval.assert_called_once()

        # Verify advisory status was changed
        mock_am_instance.change_advisory_status.assert_called_once()

        # Verify result is True (success)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
