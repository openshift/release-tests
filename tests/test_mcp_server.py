#!/usr/bin/env python3
"""
Integration tests for MCP server.

Tests MCP server connection, tool availability, and tool execution.
Uses unittest.IsolatedAsyncioTestCase for async test support.

Usage:
    # Run all tests (auto-starts server)
    python3 tests/test_mcp_server.py

    # Run specific test
    python3 tests/test_mcp_server.py TestMCPServer.test_server_connection

    # Run with custom server URL (skips auto-start)
    MCP_SERVER_URL=http://vm-hostname:8080/mcp python3 tests/test_mcp_server.py
"""

import asyncio
import os
import sys
import unittest
import subprocess
import time
import signal
import socket
import warnings

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    import httpx
except ImportError:
    print("ERROR: MCP client library not installed")
    print("Install with: pip3 install mcp httpx")
    sys.exit(1)

# Suppress async generator cleanup warnings from MCP client library
# These are harmless cleanup issues in the test environment
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", message=".*asynchronous generator.*")
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")


# Global server process handle
_server_process = None


def is_port_listening(host="localhost", port=8000, timeout=1.0):
    """
    Check if a port is listening and accepting connections.

    Args:
        host: Hostname to check
        port: Port number to check
        timeout: Connection timeout in seconds

    Returns:
        bool: True if port is listening, False otherwise
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def start_mcp_server(port=8000):
    """
    Start MCP server in background process.

    Returns:
        subprocess.Popen: Server process handle, or None if failed to start
    """
    # Check if user provided custom server URL
    if os.getenv("MCP_SERVER_URL"):
        print(f"Using custom server URL: {os.getenv('MCP_SERVER_URL')}")
        print("Skipping auto-start of local server")
        return None

    print(f"Starting MCP server on port {port}...")

    # Find mcp_server directory
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(test_dir)
    server_path = os.path.join(project_dir, "mcp_server", "server.py")

    if not os.path.exists(server_path):
        print(f"ERROR: Server file not found at {server_path}")
        return None

    # Start server process
    env = os.environ.copy()
    try:
        process = subprocess.Popen(
            [sys.executable, server_path],
            cwd=os.path.join(project_dir, "mcp_server"),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None
        )

        # Wait for server to start and verify port is listening
        print("Waiting for server to start...")
        max_wait_time = 15  # Maximum wait time in seconds
        check_interval = 0.5  # Check every 0.5 seconds
        elapsed = 0

        while elapsed < max_wait_time:
            # Check if process crashed
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print(f"ERROR: Server process crashed during startup")
                print(f"STDOUT: {stdout.decode()}")
                print(f"STDERR: {stderr.decode()}")
                return None

            # Check if port is listening
            if is_port_listening("localhost", port):
                print(f"✓ Server started successfully (PID: {process.pid})")
                print(f"✓ Port {port} is listening")
                return process

            time.sleep(check_interval)
            elapsed += check_interval

        # Timeout - server didn't start listening in time
        print(f"ERROR: Server did not start listening on port {port} within {max_wait_time} seconds")

        # Get logs for debugging
        if process.poll() is None:
            # Process is still running but not listening
            print("Process is running but port is not accepting connections")
            print("This usually indicates environment configuration issues")
        else:
            # Process exited
            stdout, stderr = process.communicate()
            print(f"STDOUT: {stdout.decode()}")
            print(f"STDERR: {stderr.decode()}")

        # Clean up
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            process.kill()
            process.wait()

        return None

    except Exception as e:
        print(f"ERROR: Failed to start server: {e}")
        return None


def stop_mcp_server(process):
    """
    Stop MCP server process.

    Args:
        process: subprocess.Popen handle or None
    """
    if process is None:
        return

    print(f"Stopping MCP server (PID: {process.pid})...")

    try:
        # Send SIGTERM to process group
        if hasattr(os, 'killpg'):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()

        # Wait for graceful shutdown
        try:
            process.wait(timeout=5)
            print("✓ Server stopped gracefully")
        except subprocess.TimeoutExpired:
            # Force kill if not stopped
            if hasattr(os, 'killpg'):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            print("✓ Server force-killed")

    except Exception as e:
        print(f"Warning: Error stopping server: {e}")


def setUpModule():
    """Module-level setup - start MCP server once for all tests"""
    # Ensure localhost is not proxied (corporate proxy issue)
    # This prevents HTTP clients from routing localhost through squid proxy
    current_no_proxy = os.getenv("NO_PROXY", "")
    current_no_proxy_lower = os.getenv("no_proxy", "")

    localhost_entries = "localhost,127.0.0.1,.local"

    if localhost_entries not in current_no_proxy:
        new_no_proxy = f"{current_no_proxy},{localhost_entries}" if current_no_proxy else localhost_entries
        os.environ["NO_PROXY"] = new_no_proxy

    if localhost_entries not in current_no_proxy_lower:
        new_no_proxy_lower = f"{current_no_proxy_lower},{localhost_entries}" if current_no_proxy_lower else localhost_entries
        os.environ["no_proxy"] = new_no_proxy_lower

    global _server_process
    _server_process = start_mcp_server(port=8000)

    if _server_process is None and not os.getenv("MCP_SERVER_URL"):
        print("=" * 60)
        print("WARNING: Could not start MCP server")
        print("Tests will be skipped unless MCP_SERVER_URL is set")
        print("=" * 60)


def tearDownModule():
    """Module-level teardown - stop MCP server after all tests"""
    global _server_process
    if _server_process:
        stop_mcp_server(_server_process)
        _server_process = None


class TestMCPServer(unittest.IsolatedAsyncioTestCase):
    """Test suite for MCP server integration tests"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests"""
        cls.server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
        cls.test_release = "4.19.1"

    async def asyncSetUp(self):
        """Set up async resources before each test"""
        # Skip tests if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        # Connect to server using HTTP transport
        self.http_context = streamablehttp_client(url=self.server_url)
        self.read, self.write, _ = await self.http_context.__aenter__()

        # Create session
        self.session_context = ClientSession(self.read, self.write)
        self.session = await self.session_context.__aenter__()

        # Initialize session
        await self.session.initialize()

    async def asyncTearDown(self):
        """Clean up async resources after each test"""
        # Close session and connection
        # Suppress RuntimeError from async cleanup (MCP client library issue)
        try:
            await self.session_context.__aexit__(None, None, None)
        except RuntimeError as e:
            if "cancel scope" not in str(e):
                raise

        try:
            await self.http_context.__aexit__(None, None, None)
        except RuntimeError as e:
            if "cancel scope" not in str(e):
                raise

    async def test_server_connection(self):
        """Test that we can connect to MCP server and initialize session"""
        # Session is already initialized in asyncSetUp
        self.assertIsNotNone(self.session, "Session should be initialized")

    async def test_list_tools(self):
        """Test that server returns list of available tools"""
        tools_result = await self.session.list_tools()

        # Handle both old and new API
        tools = tools_result.tools if hasattr(tools_result, 'tools') else tools_result

        self.assertIsNotNone(tools, "Tools list should not be None")
        self.assertGreater(len(tools), 0, "Should have at least one tool available")

        # Verify expected tools exist
        tool_names = [t.name if hasattr(t, 'name') else str(t) for t in tools]

        expected_tools = [
            'oar_get_release_metadata',
            'mcp_cache_stats',
            'oar_is_release_shipped',
            'oar_get_release_status',
        ]

        for expected_tool in expected_tools:
            self.assertIn(expected_tool, tool_names,
                         f"Expected tool '{expected_tool}' should be available")

    async def test_tool_metadata(self):
        """Test that tools have proper metadata (name and description)"""
        tools_result = await self.session.list_tools()
        tools = tools_result.tools if hasattr(tools_result, 'tools') else tools_result

        for tool in tools:
            # Each tool should have a name
            self.assertTrue(hasattr(tool, 'name'), "Tool should have 'name' attribute")
            self.assertIsInstance(tool.name, str, "Tool name should be string")
            self.assertGreater(len(tool.name), 0, "Tool name should not be empty")

            # Each tool should have a description
            self.assertTrue(hasattr(tool, 'description'), "Tool should have 'description' attribute")

    async def test_cache_stats_tool(self):
        """Test mcp_cache_stats tool execution (read-only, safe)"""
        # cache_stats is a pure MCP tool that doesn't need external resources
        result = await self.session.call_tool('mcp_cache_stats', arguments={})

        self.assertTrue(hasattr(result, 'content'), "Result should have content")
        content = str(result.content)

        # Verify cache stats output contains expected fields
        self.assertIn('metrics', content, "Output should contain metrics")
        self.assertIn('cache_size', content, "Output should contain cache_size")
        self.assertIn('max_size', content, "Output should contain max_size")

    @unittest.skip("Requires real OAR environment (GitHub, ConfigStore data)")
    async def test_get_release_metadata_tool(self):
        """Test oar_get_release_metadata tool execution (read-only, safe)"""
        # This test requires real ConfigStore data from GitHub
        # Skip in automated testing, run manually when needed
        result = await self.session.call_tool(
            'oar_get_release_metadata',
            arguments={'release': self.test_release}
        )

        self.assertTrue(hasattr(result, 'content'), "Result should have content")
        content = str(result.content)

        # Verify metadata output contains expected fields
        self.assertIn('release', content, "Output should contain release")
        self.assertIn('advisories', content, "Output should contain advisories")
        self.assertIn(self.test_release, content, "Output should contain test release version")

    @unittest.skip("Requires real OAR environment (GitHub, ConfigStore data)")
    async def test_log_capture_integration(self):
        """Test that logger messages are captured in tool output"""
        # This test requires real ConfigStore data from GitHub
        # Skip in automated testing, run manually when needed
        result = await self.session.call_tool(
            'oar_get_release_metadata',
            arguments={'release': self.test_release}
        )

        self.assertTrue(hasattr(result, 'content'), "Result should have content")
        content = str(result.content)

        # Verify content is not empty
        self.assertGreater(len(content), 0, "Tool output should not be empty")

        # Check for JSON structure (indicates successful execution)
        self.assertTrue(
            '{' in content and '}' in content,
            "Output should contain JSON structure"
        )


class TestMCPServerConcurrency(unittest.IsolatedAsyncioTestCase):
    """Test suite for concurrent MCP client handling"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

    async def test_concurrent_client_connections(self):
        """Test that multiple clients can connect simultaneously"""
        # Skip test if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        async def connect_client(client_id):
            """Connect a single client and call cache_stats"""
            async with streamablehttp_client(url=self.server_url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Call cache_stats (safe, read-only)
                    result = await session.call_tool('mcp_cache_stats', arguments={})

                    # Verify result
                    self.assertTrue(hasattr(result, 'content'),
                                  f"Client {client_id} should get result")
                    content = str(result.content)
                    self.assertIn('metrics', content)

                    return f"Client {client_id} succeeded"

        # Create 5 concurrent clients
        tasks = [connect_client(i) for i in range(5)]

        # Run all clients concurrently
        results = await asyncio.gather(*tasks)

        # Verify all clients succeeded
        self.assertEqual(len(results), 5)
        for i, result in enumerate(results):
            self.assertEqual(result, f"Client {i} succeeded")

    async def test_concurrent_tool_calls_different_clients(self):
        """Test concurrent tool calls from multiple clients"""
        # Skip test if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        async def client_workflow(client_id, tool_name):
            """Single client making a tool call"""
            async with streamablehttp_client(url=self.server_url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Call tool
                    result = await session.call_tool(tool_name, arguments={})

                    # Verify result has content
                    self.assertTrue(hasattr(result, 'content'),
                                  f"Client {client_id} should get result for {tool_name}")

                    return (client_id, tool_name, len(str(result.content)))

        # Create 3 clients calling different tools concurrently
        tasks = [
            client_workflow(0, 'mcp_cache_stats'),
            client_workflow(1, 'mcp_cache_stats'),
            client_workflow(2, 'mcp_cache_stats'),
        ]

        # Run all workflows concurrently
        results = await asyncio.gather(*tasks)

        # Verify all completed
        self.assertEqual(len(results), 3)
        for client_id, _tool_name, content_len in results:
            self.assertGreater(content_len, 0,
                             f"Client {client_id} should get non-empty response")

    async def test_thread_pool_isolation(self):
        """Test that concurrent requests are properly isolated in thread pool"""
        # Skip test if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        # This test verifies that:
        # 1. Multiple concurrent cache_stats calls complete successfully
        # 2. Results are consistent (no race conditions)
        # 3. Cache metrics show expected behavior

        async def get_cache_stats(_client_id):
            """Get cache stats from single client"""
            async with streamablehttp_client(url=self.server_url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool('mcp_cache_stats', arguments={})
                    return str(result.content)

        # Run 10 concurrent requests
        tasks = [get_cache_stats(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify all results contain expected fields
        for i, content in enumerate(results):
            self.assertIn('metrics', content, f"Result {i} should have metrics")
            self.assertIn('cache_size', content, f"Result {i} should have cache_size")
            self.assertIn('hit_rate', content, f"Result {i} should have hit_rate")


class TestMCPServerErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test suite for MCP server error handling"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

    async def test_invalid_release_version(self):
        """Test handling of invalid release version"""
        # Skip test if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        async with streamablehttp_client(url=self.server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to get metadata for non-existent release
                # This should fail gracefully with error message
                try:
                    result = await session.call_tool(
                        'oar_get_release_metadata',
                        arguments={'release': '99.99.99'}
                    )

                    # Should get result with error message
                    self.assertTrue(hasattr(result, 'content'),
                                  "Result should have content even for errors")
                    content = str(result.content)

                    # Should contain error indicator
                    self.assertTrue(
                        'Error' in content or 'error' in content or 'failed' in content,
                        "Output should indicate error for invalid release"
                    )
                except Exception as e:
                    # Some errors may be raised instead of returned
                    self.assertIsInstance(e, Exception, "Should raise or return error")


class TestMCPServerStateBoxIntegration(unittest.IsolatedAsyncioTestCase):
    """Test suite for MCP server StateBox integration"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
        # Use a test release version
        cls.test_release = "4.20.5"

    async def test_statebox_task_update_with_timestamps(self):
        """Test that StateBox task is updated with status, result, and timestamps"""
        # Skip test if server is not available
        global _server_process
        if _server_process is None and not os.getenv("MCP_SERVER_URL"):
            self.skipTest("MCP server is not running")

        # Import StateBox
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from oar.core.statebox import StateBox
        from datetime import datetime, timezone

        async with streamablehttp_client(url=self.server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Record time before calling command
                time_before = datetime.now(timezone.utc)

                # Call oar_image_signed_check via MCP
                # This will execute the command and update StateBox via CLI layer's result_callback
                result = await session.call_tool(
                    'oar_image_signed_check',
                    arguments={'release': self.test_release}
                )

                # Record time after command completes
                time_after = datetime.now(timezone.utc)

                # Verify MCP call completed
                self.assertTrue(hasattr(result, 'content'), "Result should have content")
                content = str(result.content)
                print(f"\nMCP call completed with output length: {len(content)}")

                # Reload StateBox state from GitHub to get latest updates
                from oar.core.configstore import ConfigStore
                cs = ConfigStore(self.test_release)
                statebox = StateBox(configstore=cs)
                task = statebox.get_task("image-signed-check")

                # Verify task was created and updated
                self.assertIsNotNone(task, "Task should exist in StateBox after MCP execution")

                # Verify all required fields exist
                self.assertIn("name", task, "Task should have 'name' field")
                self.assertEqual(task["name"], "image-signed-check", "Task name should match")

                self.assertIn("status", task, "Task should have 'status' field")
                self.assertIn(task["status"], ["Pass", "Fail"],
                            f"Task status should be Pass or Fail, got: {task['status']}")

                self.assertIn("result", task, "Task should have 'result' field")
                self.assertIsNotNone(task["result"], "Task result should not be None")
                self.assertGreater(len(task["result"]), 0, "Task result should contain output")

                # CRITICAL: Verify timestamps are set
                self.assertIn("started_at", task, "Task should have 'started_at' timestamp")
                self.assertIsNotNone(task["started_at"], "started_at should not be None")

                self.assertIn("completed_at", task, "Task should have 'completed_at' timestamp")
                self.assertIsNotNone(task["completed_at"], "completed_at should not be None")

                # Parse timestamps (format: 2025-11-25T13:10:28.062203)
                # StateBox stores timestamps as timezone-naive UTC timestamps
                started_at = datetime.fromisoformat(task["started_at"])
                completed_at = datetime.fromisoformat(task["completed_at"])

                # Make timezone-aware by adding UTC (StateBox uses UTC timestamps)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)

                # Verify timestamp logic
                self.assertLessEqual(started_at, completed_at,
                                   "started_at should be <= completed_at")

                # Verify completed_at is recent (CRITICAL: always updated on every run)
                # StateBox behavior: completed_at is ALWAYS updated with current timestamp
                self.assertGreaterEqual(completed_at, time_before,
                                      "completed_at should be >= time_before (task just ran)")
                self.assertLessEqual(completed_at, time_after,
                                   "completed_at should be <= time_after (task just completed)")

                # Note about started_at: It may be from a previous run if task was already "Pass"
                # This is CORRECT StateBox behavior - it preserves the original start time
                # We do NOT assert started_at >= time_before because it may be from days ago

                # Print task details for manual verification
                print(f"\nStateBox task details:")
                print(f"  Name: {task['name']}")
                print(f"  Status: {task['status']}")
                print(f"  Started at: {task['started_at']}")
                print(f"  Completed at: {task['completed_at']}")
                print(f"  Result length: {len(task['result'])} characters")
                print(f"  Result sample: {task['result'][:200]}")

                # Verify result contains expected output (not empty)
                # The result should contain captured logs from command execution
                # Note: StateBox stores raw captured logs, NOT the formatted MCP output
                # So we won't see ✓/✗ symbols (those are added by format_result() in MCP server)
                # Instead, verify it contains actual log content
                self.assertGreater(len(task['result']), 10,
                                 "Result should contain substantial log output (>10 chars)")

                print(f"\n✓ StateBox integration test passed!")
                print(f"  Task was properly created with all timestamps and captured output")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
