#!/usr/bin/env python3
"""
Simple test script to verify MCP server is working correctly.

Usage:
    # Test local server
    python3 tests/test_mcp_server.py

    # Test remote server
    python3 tests/test_mcp_server.py --url http://vm-hostname:8080/sse
"""

import asyncio
import argparse
import sys

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
except ImportError:
    print("ERROR: MCP client library not installed")
    print("Install with: pip3 install mcp")
    sys.exit(1)


async def test_mcp_server(url: str):
    """Test connection to MCP server and list available tools."""
    print(f"🔍 Testing MCP server at: {url}")
    print("-" * 60)

    try:
        # Connect to server
        print("📡 Connecting to server...")
        async with sse_client(url=url) as (read, write):
            async with ClientSession(read, write) as session:
                print("✅ Connected successfully!\n")

                # Initialize session
                await session.initialize()
                print("✅ Session initialized\n")

                # List available tools
                print("📋 Available tools:")
                print("-" * 60)
                tools_result = await session.list_tools()

                # Handle both old and new API
                # New API returns ListToolsResult with .tools attribute
                tools = tools_result.tools if hasattr(tools_result, 'tools') else tools_result

                if not tools:
                    print("⚠️  No tools found - check server configuration")
                    return

                for i, tool in enumerate(tools, 1):
                    # Tools should be Tool objects with .name and .description
                    tool_name = tool.name if hasattr(tool, 'name') else str(tool)
                    tool_desc = tool.description if hasattr(tool, 'description') else ''

                    print(f"{i}. {tool_name}")
                    if tool_desc:
                        # Print first line of description
                        desc = tool_desc.split('\n')[0]
                        print(f"   {desc}")
                    print()

                print(f"\n✅ Total tools available: {len(tools)}")
                print("-" * 60)

                # Test a simple read-only tool if available
                print("\n🧪 Testing a sample tool call...")
                test_tools = [
                    "oar_check_greenwave_cvp_tests",
                    "oar_check_cve_tracker_bug",
                ]

                tool_found = False
                for test_tool in test_tools:
                    # Build list of tool names
                    tool_names = [t.name if hasattr(t, 'name') else str(t) for t in tools]
                    if test_tool in tool_names:
                        print(f"   Calling: {test_tool}")
                        print("   Note: This may fail if release doesn't exist - that's OK")
                        tool_found = True

                        try:
                            result = await session.call_tool(
                                test_tool,
                                arguments={"release": "4.19.1"}
                            )
                            print(f"   ✅ Tool executed (check output for actual result)")
                            if hasattr(result, 'content'):
                                print(f"   Result: {result.content[:100]}...")
                        except Exception as e:
                            print(f"   ⚠️  Tool call failed: {e}")
                            print(f"   This is expected if release 4.19.1 doesn't exist")
                        break

                if not tool_found:
                    print("   ⚠️  No safe test tools found to try")

                print("\n" + "=" * 60)
                print("✅ MCP Server Test Complete!")
                print("=" * 60)

    except ConnectionError as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check if server is running: sudo systemctl status release-tests-mcp")
        print("2. Check if port is open: telnet <hostname> <port>")
        print("3. Check firewall: sudo firewall-cmd --list-ports")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Test MCP server connection and tools")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/sse",
        help="MCP server URL (default: http://localhost:8000/sse)"
    )
    args = parser.parse_args()

    await test_mcp_server(args.url)


if __name__ == "__main__":
    asyncio.run(main())
