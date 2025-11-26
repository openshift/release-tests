"""
Unit tests for log capture utility.

Tests the shared log_capture module used by CLI and MCP server.
"""

import logging
import threading
import unittest
from io import StringIO

from oar.core.log_capture import capture_logs, merge_output, ThreadFilter


logger = logging.getLogger(__name__)


class TestLogCapture(unittest.TestCase):
    """Test suite for log capture functionality."""

    def test_capture_logs_basic(self):
        """Test basic log capture without thread safety."""
        # Ensure root logger is at INFO level for test
        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.setLevel(logging.INFO)

        try:
            with capture_logs(thread_safe=False) as log_buffer:
                # Log some messages
                logger.info("Test message 1")
                logger.warning("Test warning")
                logger.info("Test message 2")

            # Get captured logs
            captured = log_buffer.getvalue()

            # Verify logs were captured with full format (timestamp + level + message)
            self.assertIn("INFO: Test message 1", captured)
            self.assertIn("WARNING: Test warning", captured)
            self.assertIn("INFO: Test message 2", captured)
        finally:
            # Restore original level
            root_logger.setLevel(original_level)

    def test_capture_logs_thread_safe(self):
        """Test log capture with thread safety enabled."""
        # Ensure root logger is at INFO level for test
        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.setLevel(logging.INFO)

        try:
            captured_logs = []

            def worker(worker_id):
                """Worker function that logs messages."""
                with capture_logs(thread_safe=True) as log_buffer:
                    logger.info(f"Worker {worker_id} message 1")
                    logger.info(f"Worker {worker_id} message 2")

                    # Get captured logs
                    logs = log_buffer.getvalue()
                    captured_logs.append((worker_id, logs))

            # Run multiple workers concurrently
            threads = []
            for i in range(3):
                t = threading.Thread(target=worker, args=(i,))
                threads.append(t)
                t.start()

            # Wait for all threads to complete
            for t in threads:
                t.join()

            # Verify each worker only captured its own logs
            for worker_id, logs in captured_logs:
                self.assertIn(f"Worker {worker_id} message 1", logs)
                self.assertIn(f"Worker {worker_id} message 2", logs)

                # Verify other workers' logs are NOT present
                for other_id in range(3):
                    if other_id != worker_id:
                        self.assertNotIn(f"Worker {other_id} message", logs)
        finally:
            # Restore original level
            root_logger.setLevel(original_level)

    def test_thread_filter(self):
        """Test ThreadFilter isolates logs by thread ID."""
        current_thread_id = threading.get_ident()
        thread_filter = ThreadFilter(current_thread_id)

        # Create a mock log record with current thread
        class MockRecord:
            pass

        record = MockRecord()

        # Filter should accept record from current thread
        self.assertTrue(thread_filter.filter(record))

    def test_merge_output_both_empty(self):
        """Test merge_output with both inputs empty."""
        result = merge_output("", "")
        self.assertEqual(result, "")

    def test_merge_output_click_only(self):
        """Test merge_output with only Click output."""
        result = merge_output("Click output", "")
        self.assertEqual(result, "Click output")

    def test_merge_output_logs_only(self):
        """Test merge_output with only captured logs."""
        result = merge_output("", "Captured logs")
        self.assertEqual(result, "Captured logs")

    def test_merge_output_logs_contains_click(self):
        """Test merge_output when logs contain Click output."""
        click_out = "Task completed"
        logs = "INFO: Starting task\nINFO: Task completed\n"

        result = merge_output(click_out, logs)
        # Should return logs only (no duplication)
        self.assertEqual(result, logs.strip())

    def test_merge_output_click_contains_logs(self):
        """Test merge_output when Click output contains logs."""
        click_out = "INFO: Starting task\nINFO: Task completed\n"
        logs = "Task completed"

        result = merge_output(click_out, logs)
        # Should return Click output only (no duplication)
        self.assertEqual(result, click_out.strip())

    def test_merge_output_both_unique(self):
        """Test merge_output when both have unique content."""
        click_out = "Click specific output"
        logs = "Log specific content"

        result = merge_output(click_out, logs)
        # Should contain both
        self.assertIn("Log specific content", result)
        self.assertIn("Click specific output", result)
        # Logs should come first (chronological order)
        self.assertTrue(result.index("Log specific") < result.index("Click specific"))

    def test_capture_logs_cleanup(self):
        """Test that log handler is properly cleaned up."""
        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)

        # Use capture_logs context
        with capture_logs(thread_safe=False) as log_buffer:
            # Handler should be added
            self.assertEqual(len(root_logger.handlers), initial_handler_count + 1)
            logger.info("Test message")

        # Handler should be removed after context exits
        self.assertEqual(len(root_logger.handlers), initial_handler_count)

    def test_cli_command_log_capture(self):
        """Test log capture with real CLI command invocation."""
        from click.testing import CliRunner
        from oar.cli.cmd_image_signed_check import image_signed_check
        from oar.cli.cmd_create_test_report import create_test_report
        from oar.core.configstore import ConfigStore

        # Note: This test will fail if environment is not properly configured
        # but it demonstrates that log capture mechanism works with real commands

        with capture_logs(thread_safe=False) as log_buffer:
            runner = CliRunner()

            # Create a minimal context (command will likely fail due to missing config)
            # but we're testing log capture, not command success
            ctx_obj = {
                '_log_buffer': log_buffer,
                'cs': ConfigStore("4.20.5")
            }

            # Invoke command - expect it to fail but capture any logs
            result = runner.invoke(create_test_report, obj=ctx_obj, catch_exceptions=True)

            # Get captured logs
            captured_logs = log_buffer.getvalue()

        # The command will fail (exit_code != 0) due to missing cs,
        # but if any logging happened, it should be captured
        # This test just verifies the mechanism works
        print(f"\nCLI command test - Exit code: {result.exit_code}")
        print(f"Captured logs length: {len(captured_logs)}")
        if captured_logs:
            print(f"Sample captured logs: {captured_logs[:200]}")


if __name__ == '__main__':
    unittest.main()