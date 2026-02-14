# Release Tests MCP Server

This directory contains the MCP (Model Context Protocol) server implementation for Release Tests.

## What is this?

The MCP server exposes OAR commands as tools that can be used by AI agents (Claude Code, ChatGPT, etc.) over a network connection. This allows:

- **Remote Access**: AI agents on your laptop can execute OAR commands on the VM
- **No Local Setup**: Users don't need to install OAR or manage credentials locally
- **Centralized Credentials**: All authentication happens on the VM
- **Team Collaboration**: Multiple users can access the same MCP server

## Architecture

```
AI Agent (Laptop) ──HTTP/SSE──> MCP Server (VM) ──Direct Click Invocation──> OAR CLI
                                      ↓
                              Thread Pool (Async)
```

The MCP server:
1. Listens for HTTP/SSE connections
2. Receives tool call requests from AI agents
3. Executes OAR commands via **direct Click invocation** (no subprocess overhead)
4. Runs blocking CLI operations in **ThreadPoolExecutor** for async support
5. Returns results back to the AI agent

### Async Concurrency Model

- **FastMCP async handlers** run in asyncio event loop (main thread)
- **Blocking CLI operations** execute in ThreadPoolExecutor worker threads via `loop.run_in_executor()`
- **Thread pool size**: Auto-scales based on CPU count (2x by default, configurable via `MCP_THREAD_POOL_SIZE`)
- **Thread-safe log capture**: ThreadFilter isolates logs per worker thread
- **Performance**: 70-90% faster than subprocess approach, <1ms thread pool overhead per request

## Files

- `server.py` - Main MCP server implementation
- `__init__.py` - Package initialization
- `README.md` - This file

## Quick Start

### Running Locally (for testing)

```bash
# Ensure credentials are loaded
source ~/.bash_profile

# Navigate to mcp_server directory
cd mcp_server/

# Run the server
python3 server.py
```

### Deploying on VM

See the complete deployment guide:
**[deployment/MCP_SERVER_DEPLOYMENT.md](../deployment/MCP_SERVER_DEPLOYMENT.md)**

## Available Tools

The server exposes these OAR commands as MCP tools (33 total):

| Tool Name | Description | Type |
|-----------|-------------|------|
| `oar_check_greenwave_cvp_tests` | Check CVP test status | Read-only |
| `oar_check_cve_tracker_bug` | Check CVE coverage | Read-only |
| `oar_image_signed_check` | Verify image signatures | Read-only |
| `oar_image_consistency_check` | Check/start consistency tests | Query/Write |
| `oar_stage_testing` | Check/start stage testing | Query/Write |
| `oar_create_test_report` | Create new test report | Write |
| `oar_take_ownership` | Assign release owner | Write |
| `oar_update_bug_list` | Sync bugs from advisory | Write |
| `oar_push_to_cdn_staging` | Push to CDN staging | Write |
| `oar_drop_bugs` | Remove unverified bugs | Write |
| `oar_change_advisory_status` | Change advisory status | Write |
| `oarctl_start_release_detector` | Start release detector | Controller |
| `oarctl_jira_notificator` | Run Jira notificator | Controller |
| `job_run` | Run Prow job | Job Control |
| `jobctl_start_controller` | Start job controller for monitoring builds | Job Control |
| `jobctl_trigger_jobs_for_build` | Trigger Prow jobs for specific build | Job Control |
| `jobctl_start_aggregator` | Start test result aggregator | Job Control |
| `jobctl_promote_test_results` | Promote test results for a build | Job Control |
| `jobctl_update_retried_job_run` | Update retried job run information | Job Control |
| `oar_get_release_metadata` | Get release configuration metadata | Read-only |
| `oar_is_release_shipped` | Check if release is fully shipped | Read-only |
| `oar_get_release_status` | Get task execution status from test report | Read-only |
| `oar_update_task_status` | Update task status in test report | Write |
| `mcp_cache_stats` | View ConfigStore cache performance metrics | Cache Mgmt |
| `mcp_cache_invalidate` | Manually invalidate cache entries | Cache Mgmt |
| `mcp_cache_warm` | Pre-populate cache with releases | Cache Mgmt |
| `get_command_help` | Get help for any CLI command (oar/oarctl/job/jobctl) | Help |
| `oar_run_command` | Run any OAR command with custom arguments | Generic |
| `oarctl_run_command` | Run any oarctl command with custom arguments | Generic |
| `jobctl_run_command` | Run any jobctl command with custom arguments | Generic |

## Usage Examples

### Example 1: Check CVP Tests

```
User: Check greenwave CVP tests for release 4.19.1

AI Agent: [Calls oar_check_greenwave_cvp_tests via MCP]
          ✓ Command succeeded

          All CVP tests passed for 4.19.1
          ...
```

### Example 2: Get Release Metadata

```
User: Get metadata for release 4.19.1

AI Agent: [Calls oar_get_release_metadata via MCP]
          {
            "release": "4.19.1",
            "advisories": {
              "extras": 113027,
              "image": 113026,
              "metadata": 113028,
              "rpm": 113025
            },
            "jira_ticket": "ART-6626",
            "candidate_builds": {
              "amd64": "4.19.0-0.nightly-2024-01-15-123456",
              "arm64": "4.19.0-0.nightly-arm64-2024-01-15-123456"
            },
            "shipment_mr": "",
            "release_url": "https://amd64.ocp.releases.ci.openshift.org/..."
          }
```

### Example 3: Discover Command Options

```
User: What options are available for the update-bug-list command?

AI Agent: [Calls get_command_help via MCP]
          get_command_help(cli="oar", command="update-bug-list")

          Usage: oar update-bug-list [OPTIONS]

          Options:
            --notify / --no-notify  Send notification to bug owners
            --confirm-droppable     Notify only bug owners with critical severity
            --notify-managers       Send notification to managers
            ...
```

### Example 4: Use Generic Command Runner

```
User: Run update-bug-list without sending notifications for 4.19.1

AI Agent: [Calls oar_run_command via MCP]
          oar_run_command(
            release="4.19.1",
            command="update-bug-list",
            args="--no-notify"
          )

          ✓ Command succeeded

          [Bug sync completed without notifications...]
```

## Configuration

The server inherits all environment variables from the user's shell (bash_profile). Required variables:

- `OAR_JWK` - Config encryption key
- `JIRA_TOKEN` - Jira authentication
- `GCP_SA_FILE` - Google Cloud service account
- And other OAR credentials...

No credentials need to be hardcoded in the server code.

## Transport Mode

This server uses **SSE (Server-Sent Events)** transport, which means:

- ✅ Standard HTTP protocol
- ✅ Works through corporate proxies
- ✅ No special network configuration needed
- ✅ Simple to debug with curl/browser

## Performance Optimization: ConfigStore Caching

The MCP server implements intelligent caching of ConfigStore instances to optimize performance for AI agent workflows.

### Why Caching?

ConfigStore initialization involves:
- JWE decryption (~5-10ms)
- **GitHub HTTP request (~300-800ms)** ← Main bottleneck
- YAML parsing (~10-50ms)

Total: ~1000ms per request

Since ConfigStore data is **immutable** after ART announces a release, without caching every tool call pays this cost even for the same release.

### Performance Improvement

**Before caching:**
```
oar_get_release_metadata('4.19.1'): 1000ms
oar_is_release_shipped('4.19.1'):   1000ms
oar_get_release_status('4.19.1'):   1000ms
Total: ~3000ms
```

**After caching:**
```
oar_get_release_metadata('4.19.1'): 1000ms (cache miss)
oar_is_release_shipped('4.19.1'):   <10ms  (cache hit)
oar_get_release_status('4.19.1'):   <10ms  (cache hit)
Total: ~1020ms (3x faster)
```

### Cache Design

- **Scope**: Per z-stream release (e.g., "4.19.1")
- **TTL**: 7 days (aligns with weekly release schedule)
- **Max size**: 50 entries with LRU eviction
- **Thread-safe**: RLock for concurrent AI agent requests
- **Implementation**: Built on `cachetools.TTLCache`

### Cache Management Tools

Monitor and manage cache performance:

```bash
# View cache statistics
mcp_cache_stats()
# Output:
{
  "metrics": {
    "hits": 150,
    "misses": 10,
    "hit_rate": "93.75%",
    "evictions": 0,
    "manual_invalidations": 0
  },
  "cache_size": 5,
  "max_size": 50,
  "ttl_human": "7 days",
  "entries": [
    {"release": "4.19.1", "cached": true},
    {"release": "4.18.5", "cached": true}
  ]
}

# Manually invalidate cache (rarely needed)
mcp_cache_invalidate(release="4.19.1")  # Specific release
mcp_cache_invalidate()                  # All releases

# Pre-populate cache before operations
mcp_cache_warm(releases="4.19.1,4.18.5,4.17.10")
```

### When to Invalidate Cache

**Rarely needed!** ConfigStore data is immutable after release announcement.

Only invalidate if ART updates build data post-announcement (exceptional case):
```python
# ART changed candidate build for 4.19.1
mcp_cache_invalidate(release="4.19.1")
```

### Note on CLI vs MCP Server

Caching is **only used in MCP server**, not in CLI commands. CLI commands are short-lived processes where caching provides no benefit since each invocation creates a new process.

## Adding New Tools

To expose a new OAR command:

```python
@mcp.tool()
def oar_your_new_command(release: str, param: str) -> str:
    """
    Description of what this command does.

    Args:
        release: Release version
        param: Parameter description

    Returns:
        Command result
    """
    result = run_oar_command(["-r", release, "your-command", "-p", param])
    return format_result(result)
```

Then restart the server.

## Security

Since this server runs on internal network:

- Network access limited to corporate VPN
- Credentials stored only on VM
- No authentication layer (network security sufficient)

If you need to expose outside internal network, add API key authentication.

## Logging

The server logs all operations:

```python
logger.info(f"Executing: oar {' '.join(args)}")
logger.info(f"Command completed with exit code: {result.returncode}")
```

When running as systemd service, logs go to journald:
```bash
sudo journalctl -u release-tests-mcp -f
```

## Dependencies

```bash
pip3 install fastmcp cachetools
```

- **FastMCP**: MCP protocol implementation with SSE transport support
- **cachetools**: TTL-based caching for ConfigStore instances (performance optimization)

## Related Documentation

- [MCP Server Deployment Guide](../deployment/MCP_SERVER_DEPLOYMENT.md)
- [OAR CLI Documentation](../oar/README.md)
- [AGENTS.md](../AGENTS.md) - Complete OAR command reference
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
