#!/usr/bin/env python3
"""
MCP Data Collector Module

This module provides a Python interface to collect release data from the MCP server.

Usage:
    # Use MCP server (local default: http://localhost:8000/mcp)
    collector = MCPDataCollector()

    # Use MCP server (remote)
    collector = MCPDataCollector(server_url="http://server:8000/mcp")

    # Fetch release data
    status = collector.get_release_status("4.19.1")
    metadata = collector.get_release_metadata("4.19.1")
"""

import json
import logging
import os
import sys
import asyncio
import concurrent.futures
from typing import Dict, Any, Optional
import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession

logger = logging.getLogger(__name__)

# Add parent directory to path for OAR imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)


class MCPDataCollector:
    """
    Collector class for fetching data from release-tests MCP server

    This class provides methods to retrieve:
    - Release status (task completion, overall status)
    - Release metadata (advisories, builds, dates)
    - Shipment status (shipped, flow type)

    Note: Maintains a persistent event loop to avoid "Task group is not initialized"
    errors with FastMCP's streamable-http transport.
    """

    def __init__(self, server_url: Optional[str] = None):
        """
        Initialize the MCP data collector

        Args:
            server_url: MCP server URL (default: from MCP_SERVER_URL env var or http://localhost:8000/mcp)
        """
        default_url = os.environ.get('MCP_SERVER_URL', 'http://localhost:8000/mcp')
        self.server_url = server_url or default_url
        self.timeout = 120  # HTTP connection timeout in seconds
        self.read_timeout = 600  # HTTP read timeout in seconds (10 min for slow operations)

        # Create a persistent event loop for this instance
        # This avoids "Task group is not initialized" errors with streamable-http transport
        # when making multiple calls (asyncio.run() creates new loop each time which breaks FastMCP)

        # Check if we're in an environment with a running loop (like Streamlit)
        try:
            asyncio.get_running_loop()
            self._loop_is_external = True
            logger.info(f"Detected external event loop (e.g., Streamlit)")
        except RuntimeError:
            self._loop_is_external = False
            logger.info(f"No external event loop detected")

        # Always create our own dedicated event loop (don't reuse external loops)
        self._loop = asyncio.new_event_loop()
        logger.info(f"Created dedicated event loop for MCP data collector")

        logger.info(f"Initialized MCP data collector with server: {self.server_url}")

    async def _call_mcp_tool_async(self, tool_name: str, max_retries: int = 5, **kwargs) -> Dict[str, Any]:
        """
        Call an MCP tool via HTTP transport with retry logic (async)

        This implements retry logic similar to Claude Code's MCP client configuration
        to handle transient "Task group is not initialized" errors from FastMCP.

        Args:
            tool_name: Name of the MCP tool to call
            max_retries: Maximum number of retry attempts (default: 5, matching Claude Code)
            **kwargs: Tool parameters

        Returns:
            Parsed JSON response from the tool

        Raises:
            RuntimeError: If tool call fails after all retries
        """
        last_error = None
        initial_delay = 2.0  # seconds, matching Claude Code's config

        for attempt in range(max_retries):
            try:
                logger.debug(f"Calling MCP tool: {tool_name} with args: {kwargs} (attempt {attempt + 1}/{max_retries})")

                # Create httpx client with timeout configuration
                # Configure both connect and read timeouts to match MCP server expectations
                http_timeout = httpx.Timeout(
                    connect=self.timeout,  # Connection timeout
                    read=self.read_timeout,  # Read timeout for long operations
                    write=self.timeout,  # Write timeout
                    pool=self.timeout  # Pool timeout
                )

                async with httpx.AsyncClient(timeout=http_timeout) as http_client:
                    # Connect to MCP server via HTTP with configured client
                    async with streamable_http_client(
                        self.server_url,
                        http_client=http_client
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            # Initialize the session
                            await session.initialize()

                            # Call the tool (no prefix needed for fastmcp server)
                            # Set a timeout for the tool call itself
                            result = await asyncio.wait_for(
                                session.call_tool(tool_name, arguments=kwargs),
                                timeout=self.read_timeout
                            )

                            # Check for error response
                            if result.isError:
                                error_msg = result.content[0].text if result.content else "Unknown error"
                                logger.error(f"MCP tool {tool_name} returned error: {error_msg}")
                                raise RuntimeError(f"Tool returned error: {error_msg}")

                            # Extract text content from result
                            if result.content and len(result.content) > 0:
                                text_content = result.content[0].text
                                # Parse JSON response
                                return json.loads(text_content)
                            else:
                                logger.warning(f"Empty response from tool {tool_name}")
                                return {}

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(f"Timeout calling MCP tool {tool_name} after {self.read_timeout}s (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue
            except Exception as e:
                last_error = e
                # Check if this is a "Task group is not initialized" error
                error_str = str(e)
                if "Task" in error_str and "group" in error_str:
                    logger.warning(f"Task group error calling MCP tool {tool_name}: {error_str} (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        delay = initial_delay * (2 ** attempt)  # Exponential backoff
                        logger.info(f"Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        continue
                # Non-retryable error, fail immediately
                logger.error(f"Failed to call MCP tool {tool_name}: {str(e)}")
                raise RuntimeError(f"MCP tool call failed: {str(e)}")

        # All retries exhausted
        error_msg = f"MCP tool call failed after {max_retries} attempts"
        if last_error:
            error_msg += f": {str(last_error)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    async def get_release_status_async(self, release: str) -> Dict[str, Any]:
        """
        Get task execution status for a release (async)

        Args:
            release: Release version (e.g., "4.19.1")

        Returns:
            Dictionary with structure:
            {
                "release": "4.19.1",
                "overall_status": "Green" | "Red",
                "tasks": {
                    "task-name": "Pass" | "Fail" | "In Progress" | "Not Started",
                    ...
                }
            }
        """
        try:
            return await self._call_mcp_tool_async('oar_get_release_status', release=release)
        except Exception as e:
            logger.warning(f"Failed to get release status for {release}: {str(e)}")
            return {
                "release": release,
                "overall_status": "Unknown",
                "tasks": {},
                "error": str(e)
            }

    async def get_release_metadata_async(self, release: str) -> Dict[str, Any]:
        """
        Get release metadata from ConfigStore (async)

        Args:
            release: Release version (e.g., "4.19.1")

        Returns:
            Dictionary with structure:
            {
                "release": "4.19.1",
                "advisories": {...},
                "jira_ticket": "OCPBUGS-xxxxx",
                "candidate_builds": {...},
                "shipment_mr": "https://...",
                "release_date": "2025-Nov-04"
            }
        """
        try:
            return await self._call_mcp_tool_async('oar_get_release_metadata', release=release)
        except Exception as e:
            logger.warning(f"Failed to get release metadata for {release}: {str(e)}")
            return {
                "release": release,
                "advisories": {},
                "jira_ticket": "",
                "candidate_builds": {},
                "shipment_mr": "",
                "release_date": "",
                "error": str(e)
            }

    async def is_release_shipped_async(self, release: str) -> Dict[str, Any]:
        """
        Check if a release has been shipped (async)

        Args:
            release: Release version (e.g., "4.19.1")

        Returns:
            Dictionary with structure:
            {
                "shipped": true | false,
                "flow_type": "errata" | "konflux",
                "details": {...}
            }
        """
        try:
            return await self._call_mcp_tool_async('oar_is_release_shipped', release=release)
        except Exception as e:
            logger.warning(f"Failed to check shipment status for {release}: {str(e)}")
            return {
                "shipped": False,
                "flow_type": "unknown",
                "details": {},
                "error": str(e)
            }

    async def get_all_release_data_async(self, release: str) -> Dict[str, Any]:
        """
        Get all data for a release (status, metadata, shipment) - async

        Args:
            release: Release version (e.g., "4.19.1")

        Returns:
            Dictionary containing all release information
        """
        # Run all three calls concurrently
        status_task = self.get_release_status_async(release)
        metadata_task = self.get_release_metadata_async(release)
        shipped_task = self.is_release_shipped_async(release)

        status, metadata, shipped = await asyncio.gather(
            status_task, metadata_task, shipped_task
        )

        return {
            'status': status,
            'metadata': metadata,
            'shipped': shipped
        }

    def _run_async(self, coro):
        """
        Run async coroutine using the persistent event loop.

        This method ensures we reuse the same event loop across calls,
        which is required for FastMCP's streamable-http transport.

        When running in environments with existing event loops (like Streamlit),
        we use our own dedicated loop in a way that doesn't conflict.
        """
        if self._loop_is_external:
            # We're in an environment with a running loop (e.g., Streamlit)
            # We can't use loop.run_until_complete() directly because another loop is running
            # Instead, we need to run the coroutine in our persistent loop using threading
            # This avoids "This event loop is already running" error
            def run_in_thread():
                # Set our loop as the event loop for this thread
                asyncio.set_event_loop(self._loop)
                # Run the coroutine to completion
                return self._loop.run_until_complete(coro)

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result()
        else:
            # Use our persistent loop directly
            return self._loop.run_until_complete(coro)

    # Synchronous wrappers for backward compatibility
    def get_release_status(self, release: str) -> Dict[str, Any]:
        """Get release status (sync wrapper)"""
        return self._run_async(self.get_release_status_async(release))

    def get_release_metadata(self, release: str) -> Dict[str, Any]:
        """Get release metadata (sync wrapper)"""
        return self._run_async(self.get_release_metadata_async(release))

    def is_release_shipped(self, release: str) -> Dict[str, Any]:
        """Check if release is shipped (sync wrapper)"""
        return self._run_async(self.is_release_shipped_async(release))

    def get_all_release_data(self, release: str) -> Dict[str, Any]:
        """Get all release data (sync wrapper)"""
        return self._run_async(self.get_all_release_data_async(release))


if __name__ == "__main__":
    # Test the collector
    logging.basicConfig(level=logging.INFO)

    collector = MCPDataCollector()

    # Test with a sample release
    test_release = "4.19.1"

    print(f"\n=== Testing MCP Data Collector for {test_release} ===\n")

    print("1. Getting release status...")
    status = collector.get_release_status(test_release)
    print(json.dumps(status, indent=2))

    print("\n2. Getting release metadata...")
    metadata = collector.get_release_metadata(test_release)
    print(json.dumps(metadata, indent=2))

    print("\n3. Checking shipment status...")
    shipped = collector.is_release_shipped(test_release)
    print(json.dumps(shipped, indent=2))

    print("\n=== Test Complete ===")