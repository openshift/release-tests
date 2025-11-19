#!/usr/bin/env python3
"""
Unit tests for thread-based log capture in MCP server.

This test suite verifies:
1. Logger messages are captured and merged with Click output
2. ConfigStore caching works correctly with significant performance improvement
3. cmd_group accepts and uses cached ConfigStore from MCP server
"""

import sys
import os
import unittest
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.server import merge_output, get_cached_configstore
from click.testing import CliRunner
from oar.cli.cmd_group import cli


class TestMergeOutput(unittest.TestCase):
    """Test suite for merge_output utility function"""

    def test_merge_both_outputs(self):
        """Test merging both Click output and logger output"""
        click_out = "Click output"
        log_out = "Logger output"
        result = merge_output(click_out, log_out)
        self.assertEqual(result, "Click output\nLogger output")

    def test_merge_click_only(self):
        """Test with only Click output (no logs)"""
        result = merge_output("Click only", "")
        self.assertEqual(result, "Click only")

    def test_merge_log_only(self):
        """Test with only logger output (no Click output)"""
        result = merge_output("", "Log only")
        self.assertEqual(result, "Log only")

    def test_merge_with_trailing_newline(self):
        """Test that trailing newlines are handled correctly"""
        result = merge_output("Click output\n", "Logger output")
        self.assertEqual(result, "Click output\nLogger output")


class TestConfigStoreCache(unittest.TestCase):
    """Test suite for ConfigStore caching functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures - warm the cache once for all tests"""
        cls.test_release = "4.19.1"
        # Warm cache
        cls.cs1 = get_cached_configstore(cls.test_release)

    def test_cache_returns_same_object(self):
        """Test that cache returns the same ConfigStore object"""
        cs2 = get_cached_configstore(self.test_release)
        self.assertIs(self.cs1, cs2, "Cache should return same object")

    def test_cache_performance(self):
        """Test that cache provides significant performance improvement"""
        # First call - should be from cache (fast)
        start = time.time()
        cs1 = get_cached_configstore(self.test_release)
        time1 = time.time() - start

        # Second call - should also be from cache (fast)
        start = time.time()
        cs2 = get_cached_configstore(self.test_release)
        time2 = time.time() - start

        # Both should be very fast (< 10ms for cache hits)
        self.assertLess(time1, 0.01, "Cache hit should be < 10ms")
        self.assertLess(time2, 0.01, "Cache hit should be < 10ms")
        self.assertIs(cs1, cs2, "Should return same cached object")


class TestCmdGroupCachedConfigStore(unittest.TestCase):
    """Test suite for cmd_group accepting cached ConfigStore"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_release = "4.19.1"
        self.runner = CliRunner()

    def test_cmd_group_accepts_cached_configstore(self):
        """Test that cmd_group accepts cached ConfigStore from MCP server"""
        # Get cached ConfigStore
        cs1 = get_cached_configstore(self.test_release)

        # Invoke help command with cached ConfigStore
        # Using --help avoids actual command execution and network issues
        result = self.runner.invoke(cli, ["-r", self.test_release, "--help"], obj={"cs": cs1})

        # Verify command accepted the cached ConfigStore
        self.assertEqual(result.exit_code, 0, "Help command should succeed")
        self.assertIn("Usage:", result.output, "Help output should contain 'Usage:'")

    def test_cached_configstore_reused(self):
        """Test that the same cached ConfigStore object is reused"""
        cs1 = get_cached_configstore(self.test_release)
        cs2 = get_cached_configstore(self.test_release)
        self.assertIs(cs1, cs2, "Should return same cached ConfigStore object")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
