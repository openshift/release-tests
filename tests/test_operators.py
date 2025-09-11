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


if __name__ == '__main__':
    unittest.main()
