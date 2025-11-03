#!/usr/bin/env python3
"""
MCP Data Collector Module

This module provides a Python interface to collect release data.
It can either use the MCP server (for remote access) or call OAR functions directly (for local access).

Usage:
    # Use MCP server (remote)
    collector = MCPDataCollector(use_mcp=True, server_url="http://server:8000/sse")

    # Use direct OAR calls (local, faster)
    collector = MCPDataCollector(use_mcp=False)

    status = collector.get_release_status("4.19.1")
    metadata = collector.get_release_metadata("4.19.1")
"""

import json
import logging
import os
import sys
import asyncio
from typing import Dict, Any, Optional
from mcp.client.sse import sse_client
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
    """

    def __init__(self, server_url: Optional[str] = None):
        """
        Initialize the MCP data collector

        Args:
            server_url: MCP server URL (default: from MCP_SERVER_URL env var or http://localhost:8000/sse)
        """
        default_url = os.environ.get('MCP_SERVER_URL', 'http://localhost:8000/sse')
        self.server_url = server_url or default_url
        self.timeout = 120  # HTTP request timeout in seconds (increased from 60)
        self.sse_read_timeout = 600  # SSE read timeout in seconds (10 min for slow operations, increased from 300)
        logger.info(f"Initialized MCP data collector with server: {self.server_url}")

    async def _call_mcp_tool_async(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Call an MCP tool via SSE transport (async)

        Args:
            tool_name: Name of the MCP tool to call
            **kwargs: Tool parameters

        Returns:
            Parsed JSON response from the tool

        Raises:
            RuntimeError: If tool call fails
        """
        try:
            logger.debug(f"Calling MCP tool: {tool_name} with args: {kwargs}")

            # Connect to MCP server via SSE with explicit timeouts
            async with sse_client(
                self.server_url,
                timeout=self.timeout,
                sse_read_timeout=self.sse_read_timeout
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize the session
                    await session.initialize()

                    # Call the tool (no prefix needed for fastmcp server)
                    # Set a timeout for the tool call itself
                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments=kwargs),
                        timeout=self.sse_read_timeout
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

        except asyncio.TimeoutError:
            logger.error(f"Timeout calling MCP tool {tool_name} after {self.sse_read_timeout}s")
            raise RuntimeError(f"MCP tool call timed out after {self.sse_read_timeout}s")
        except Exception as e:
            logger.error(f"Failed to call MCP tool {tool_name}: {str(e)}")
            raise RuntimeError(f"MCP tool call failed: {str(e)}")

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

    # Synchronous wrappers for backward compatibility
    def get_release_status(self, release: str) -> Dict[str, Any]:
        """Get release status (sync wrapper)"""
        return asyncio.run(self.get_release_status_async(release))

    def get_release_metadata(self, release: str) -> Dict[str, Any]:
        """Get release metadata (sync wrapper)"""
        return asyncio.run(self.get_release_metadata_async(release))

    def is_release_shipped(self, release: str) -> Dict[str, Any]:
        """Check if release is shipped (sync wrapper)"""
        return asyncio.run(self.is_release_shipped_async(release))

    def get_all_release_data(self, release: str) -> Dict[str, Any]:
        """Get all release data (sync wrapper)"""
        return asyncio.run(self.get_all_release_data_async(release))


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