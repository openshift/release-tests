"""
Shared log capture utility for CLI commands and MCP server.

Provides thread-safe log capture mechanism that works in both:
1. Direct CLI execution (single-threaded, no ThreadFilter needed)
2. MCP server execution (multi-threaded via ThreadPoolExecutor)

This module is used by:
- CLI layer (cmd_group.py result_callback) for automatic StateBox updates
- MCP server (server.py) for capturing command output

Design:
    - StringIO handler captures logs from root logger
    - ThreadFilter isolates logs per thread (when thread_safe=True)
    - Context manager ensures proper cleanup
    - Merge utility combines Click output with captured logs

Usage:
    # Single-threaded (CLI)
    with capture_logs(thread_safe=False) as captured:
        # Run command
        result = runner.invoke(command_func, args)

    logs = captured.getvalue()

    # Multi-threaded (MCP server)
    with capture_logs(thread_safe=True) as captured:
        # Run command
        result = runner.invoke(command_func, args)

    logs = captured.getvalue()
"""

import io
import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from oar.core.const import LOG_FORMAT, LOG_DATE_FORMAT


class ThreadFilter(logging.Filter):
    """
    Filter logs to only include records from current thread.

    This prevents log mixing between concurrent thread pool workers
    when multiple AI agents send MCP requests simultaneously.

    Design:
        - Captures thread ID at filter creation time
        - Only allows log records from that specific thread
        - Used in MCP server ThreadPoolExecutor workers

    Example:
        thread_id = threading.get_ident()
        thread_filter = ThreadFilter(thread_id)
        handler.addFilter(thread_filter)
    """

    def __init__(self, thread_id: int):
        """
        Initialize thread filter.

        Args:
            thread_id: Thread ID to filter for (from threading.get_ident())
        """
        super().__init__()
        self.thread_id = thread_id

    def filter(self, record) -> bool:
        """
        Check if log record should be included.

        Args:
            record: LogRecord to filter

        Returns:
            True if record is from our thread, False otherwise
        """
        return threading.get_ident() == self.thread_id


@contextmanager
def capture_logs(thread_safe: bool = False) -> Iterator[io.StringIO]:
    """
    Context manager for capturing logs from root logger.

    Captures all logs emitted during the context and returns them as a StringIO.
    Automatically cleans up log handler on exit.

    Args:
        thread_safe: Enable ThreadFilter for multi-threaded execution (default: False)
                    Set to True when running in MCP server ThreadPoolExecutor
                    Set to False for direct CLI usage (single-threaded)

    Yields:
        StringIO: Buffer containing captured log output

    Thread Safety:
        - thread_safe=False: No isolation (safe for single-threaded CLI)
        - thread_safe=True: ThreadFilter prevents log mixing (required for MCP server)

    Example:
        # CLI layer (single-threaded)
        with capture_logs(thread_safe=False) as logs:
            runner.invoke(command_func, args)

        output = logs.getvalue()

        # MCP server (multi-threaded)
        with capture_logs(thread_safe=True) as logs:
            runner.invoke(command_func, args)

        output = logs.getvalue()
    """
    # Create StringIO buffer for log capture
    log_buffer = io.StringIO()

    # Create handler with formatter matching console handler
    # This ensures captured logs have same format and level as console output
    log_handler = logging.StreamHandler(log_buffer)

    # Inherit log level from root logger to match console handler behavior
    # This ensures we capture the same logs that appear in the console
    root_logger = logging.getLogger()
    log_handler.setLevel(root_logger.level)

    log_handler.setFormatter(logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT
    ))

    # Add ThreadFilter if thread-safe mode enabled
    if thread_safe:
        thread_id = threading.get_ident()
        log_handler.addFilter(ThreadFilter(thread_id))

    # Add handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)

    try:
        yield log_buffer
    finally:
        # Always clean up handler to prevent memory leaks
        root_logger.removeHandler(log_handler)
        log_handler.close()


def merge_output(click_output: str, captured_logs: str) -> str:
    """
    Merge Click command output with captured logs.

    Deduplicates content that appears in both outputs and combines
    them into a single coherent output string.

    Args:
        click_output: Output from Click command (result.output)
        captured_logs: Logs captured from logger

    Returns:
        Combined output string

    Deduplication Strategy:
        - If click_output contains captured_logs, return click_output only
        - If captured_logs contains click_output, return captured_logs only
        - Otherwise, concatenate both (logs first, then click output)

    Example:
        >>> click_out = "Task completed\\n"
        >>> logs = "INFO: Starting task\\nINFO: Task completed\\n"
        >>> merge_output(click_out, logs)
        'INFO: Starting task\\nINFO: Task completed\\n'
    """
    click_output = click_output.strip()
    captured_logs = captured_logs.strip()

    # If either is empty, return the other
    if not click_output:
        return captured_logs
    if not captured_logs:
        return click_output

    # Deduplication: check if one contains the other
    if captured_logs in click_output:
        # Click output already includes all logs
        return click_output
    if click_output in captured_logs:
        # Logs already include all Click output
        return captured_logs

    # Both have unique content - combine them
    # Logs first (chronological order), then Click output
    return f"{captured_logs}\n{click_output}"
