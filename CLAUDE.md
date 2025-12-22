# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ERT (Errata Reliability Team) Release Tests** - A Python-based automation framework for managing OpenShift z-stream releases. This project automates QE tasks throughout the release lifecycle, including advisory management, bug tracking, test execution, and release approval workflows.

**Key Technologies:**
- Python 3.11+
- Click framework (CLI)
- StateBox (GitHub-backed YAML for release state tracking)
- Google Sheets API (backward compatibility for old releases)
- Errata Tool, Jira, GitLab, Jenkins, Slack integrations
- Prow/Gangway (CI test orchestration)
- Kerberos authentication (for Red Hat internal services)

## Installation & Setup

```bash
# Install the package in editable mode
pip3 install -e .

# Alternative: Use Makefile
make install

# Uninstall
make uninstall

# Clean reinstall
make clean-install
```

**Python Version:** Requires Python 3.11+

## Running Tests

```bash
# Run all tests with pytest
pytest

# Run specific test file
pytest tests/test_advisory.py

# Run with verbose output
pytest -v

# Run tests matching pattern
pytest -k test_jenkins
```

Test files are located in `tests/` directory.

## CLI Commands

This project provides three main CLI entry points, plus an MCP server for AI agent integration:

### 1. OAR CLI (`oar`)

Main CLI for z-stream release management:

```bash
# General syntax
oar -r <release-version> [OPTIONS] COMMAND [ARGS]

# Common commands (see AGENTS.md for full list)
oar -r 4.19.1 create-test-report
oar -r 4.19.1 take-ownership -e user@redhat.com
oar -r 4.19.1 update-bug-list
oar -r 4.19.1 check-greenwave-cvp-tests
oar -r 4.19.1 change-advisory-status

# Enable debug logging
oar -r 4.19.1 -v create-test-report
```

### 2. Controller CLI (`oarctl`)

CLI for automated agents and controllers:

```bash
# Start release detector
oarctl start-release-detector -r 4.19

# Start Jira notificator
oarctl jira-notificator --dry-run
oarctl jira-notificator --from-date 2025-01-15
```

### 3. Prow Job Controller (`jobctl`)

Entry point is `prow/setup.py` which installs `job` and `jobctl` commands:

```bash
# Run specific Prow job
job run <job_name> --payload $image_pullspec

# Start job controller (monitors builds and triggers tests)
jobctl start-controller -r 4.19 --nightly --arch amd64

# Start test result aggregator
jobctl start-aggregator --arch amd64
```

### 4. MCP Server (AI Integration)

Exposes all OAR commands as MCP tools for AI agents:

```bash
# Start MCP server
cd mcp_server
python3 server.py

# Access via AI agents (Claude Code, etc.)
# Server runs at http://localhost:8000 by default
```

See the "MCP Server" section under Architecture for detailed information.

## Architecture

### High-Level Structure

```
release-tests/
├── oar/                    # Main OAR package
│   ├── cli/               # Click-based CLI commands
│   ├── core/              # Core modules (see below)
│   ├── controller/        # Release detector agent
│   └── notificator/       # Jira notificator agent
├── prow/                  # Prow job controller system
│   └── job/              # Job orchestration, test aggregation
├── mcp_server/            # MCP server for AI agent integration
│   └── server.py          # FastMCP server exposing OAR commands as tools
├── tools/                 # Standalone tools (Slack bot, checkers)
├── tests/                 # Unit tests
└── _releases/            # GitHub-based persistent state (build tracking)
```

### Core Module Architecture (`oar/core/`)

The OAR system is built on a layered architecture where all modules depend on `ConfigStore` for configuration:

**Foundation:**
- `configstore.py` - Encrypted config management (JWE), release-specific settings
- `exceptions.py` - Custom exception types for all modules
- `util.py` - Shared utilities (version validation, URL builders, logging)

**External Service Integrations:**
- `advisory.py` - Errata Tool interactions (requires Kerberos)
- `jira.py` - Jira API client for issue tracking
- `statebox.py` - GitHub-backed YAML state management (primary for new releases)
- `worksheet.py` - Google Sheets test reports (backward compatibility for old releases)
- `notification.py` - Slack notifications
- `shipment.py` - GitLab MR management for Konflux workflow
- `jenkins.py` - Jenkins job triggering and monitoring
- `ldap.py` - LDAP lookups for manager hierarchy
- `git.py` - Git operations for shipment data

**Orchestration Layer:**
- `operators.py` - Composite operators that coordinate across multiple modules (ReleaseOwnershipOperator, BugOperator, ApprovalOperator, ReleaseShipmentOperator, etc.)

**Key Design Pattern:**
All core modules follow Manager/Helper pattern with:
- Integration with ConfigStore
- Custom exception handling
- Logging for observability

### Two Release Workflows

The system supports two distinct release workflows:

1. **Errata Flow** (traditional): Advisory-based using Errata Tool
2. **Konflux Flow** (newer): GitLab MR-based shipment workflow

OAR commands automatically detect and handle both flows based on ConfigStore configuration.

### Automated Agents

Six automated agents work together for end-to-end release automation (see AGENTS.md for details):

1. **Release Detector** (`oar/controller/detector.py`) - Detects new z-stream releases
2. **Job Controller** (`prow/job/controller.py`) - Monitors builds, triggers Prow tests
3. **Test Result Aggregator** (`prow/job/controller.py`) - Processes results, implements retry logic
4. **Jira Notificator** (`oar/notificator/jira_notificator.py`) - Escalates unverified bugs
5. **Slack Bot** (`tools/slack_message_receiver.py`) - Executes OAR commands via Slack
6. **Test Result Checker** (`tools/auto_release_test_result_checker.py`) - Notifies about rejected builds

### MCP Server (AI Agent Integration)

The MCP (Model Context Protocol) server (`mcp_server/server.py`) exposes OAR commands as structured tools for AI agents like Claude Code.

**What it does:**
- Wraps all OAR/oarctl/job/jobctl commands as MCP tools (27 total)
- Provides structured input/output for AI agent interaction
- Categorizes operations by safety (read-only, write, critical)
- Validates environment on startup
- Runs as HTTP server (SSE transport) for remote access
- Uses **direct Click invocation** (70-90% faster than subprocess)
- Implements **async concurrency** via ThreadPoolExecutor for handling multiple AI agent requests simultaneously

**Categories of tools:**
1. **Read-only tools** - Safe query operations (check-greenwave-cvp-tests, check-cve-tracker-bug, image-signed-check, is-release-shipped)
2. **Status check tools** - Query job status (image-consistency-check -n, stage-testing -n)
3. **Write operations** - Modify state (create-test-report, update-bug-list, take-ownership)
4. **Critical operations** - Production impact (push-to-cdn-staging, change-advisory-status)
5. **Controller tools** - Background agents (start-release-detector, jira-notificator)
6. **Job controller tools** - CI orchestration (start-controller, trigger-jobs-for-build)
7. **Generic runners** - Advanced usage (oar_run_command, jobctl_run_command)
8. **Configuration tools** - Metadata access (oar_get_release_metadata, is-release-shipped)
9. **Cache management tools** - Performance optimization (mcp_cache_stats, mcp_cache_invalidate, mcp_cache_warm)

**Running the server:**

```bash
# Navigate to MCP server directory
cd mcp_server

# Check environment setup
./check_env.sh

# Start server (default: localhost:8000)
python3 server.py

# For remote access
# Edit server.py line 759: mcp.run(transport="sse", host="0.0.0.0", port=8080)
```

**Health check endpoint:**

The server exposes an HTTP health check endpoint at `/health` for monitoring and load balancer compatibility:

```bash
# Check server health
curl http://localhost:8000/health

# Example response (200 OK if healthy, 503 if degraded):
{
  "status": "healthy",
  "server": "release-tests-mcp",
  "version": "1.0.0",
  "transport": "sse",
  "tools": {
    "total": 28,
    "cli": 17,
    "api": 11
  },
  "environment": {
    "valid": true,
    "missing_required": [],
    "missing_optional": []
  },
  "kerberos": {
    "valid": true,
    "status": "valid"
  },
  "cache": {
    "enabled": true,
    "size": 0,
    "max_size": 50,
    "hit_rate": "0.00%",
    "ttl_days": 7
  },
  "thread_pool": {
    "size": 20,
    "cpu_count": 10
  },
  "timestamp": "2025-12-22T10:30:00Z"
}
```

**Use cases:**
- Load balancer liveness checks
- Container orchestration health probes (Kubernetes/OpenShift)
- Monitoring tools (Prometheus, Datadog, etc.)
- Manual health verification during debugging

**Response codes:**
- `200 OK` - Server is healthy (all required environment variables configured AND valid Kerberos ticket)
- `503 Service Unavailable` - Server is degraded (missing required environment variables OR no Kerberos ticket)
- `500 Internal Server Error` - Health check itself failed (unexpected error)

**Environment requirements:**
- All OAR CLI environment variables (OAR_JWK, JIRA_TOKEN, GCP_SA_FILE, etc.)
- Server validates environment on startup and exits if critical vars missing

**Use cases:**
- AI-assisted release management workflows
- Automated release operations via Claude Code
- Interactive debugging and troubleshooting
- Documentation and training with AI guidance

**Safety features:**
- Operations clearly marked with warning emoji (⚠️ WRITE, ⚠️ CRITICAL)
- Read-only operations for safe exploration
- Timeout handling (default 10 minutes)
- Structured error reporting

**Development notes:**
- Built with FastMCP framework
- Tool definitions include comprehensive docstrings for AI context
- All tools wrap existing CLI commands (no new business logic)
- See AGENTS.md for complete tool reference

## Environment Variables

**Critical for OAR CLI:**
- `OAR_JWK` - Encryption key for config_store.json (from Bitwarden: *openshift-qe-trt-env-vars*)
- `JIRA_TOKEN` - Jira personal access token
- `GCP_SA_FILE` - Google Cloud service account credentials file path (optional for new releases using StateBox; required for old releases with Google Sheets)
- `SLACK_BOT_TOKEN` - Slack bot token
- `JENKINS_USER` / `JENKINS_TOKEN` - Jenkins credentials
- `GITLAB_TOKEN` - GitLab personal access token
- Kerberos ticket required: `kinit $kid@$domain`

**For Controllers/Agents:**
- `GITHUB_TOKEN` - GitHub API access
- `APITOKEN` - Prow/Gangway API token
- `GCS_CRED_FILE` - Google Cloud Storage credentials (for test artifacts)

**For Slack Bot:**
- `SLACK_APP_TOKEN` - Slack app-level token (Socket Mode)
- `SLACK_BOT_TOKEN` - Slack bot token

See AGENTS.md for complete environment variable breakdown by component.

## Important Concepts

### ConfigStore (`oar/core/configstore.py`)

Centralized configuration management:
- Loads encrypted `config_store.json` using JWE (decrypted via `OAR_JWK`)
- Stores release-specific data: advisory IDs, Jira tickets, Google Sheet URLs, shipment MR URLs
- All OAR commands access configuration through ConfigStore
- Supports both Errata and Konflux workflow modes

### ConfigStore Caching (MCP Server Only)

The MCP server implements intelligent caching of ConfigStore instances for performance optimization:

**Design:**
- **Scope**: Per z-stream release (e.g., "4.19.1")
- **TTL**: 7 days (aligns with weekly release schedule)
- **Max size**: 50 entries with LRU eviction
- **Thread-safe**: Uses `RLock` for concurrent AI agent requests
- **Implementation**: Built on `cachetools.TTLCache`

**Performance Impact:**
- **Cache miss** (first access): ~1000ms
  - JWE decryption: ~5-10ms
  - GitHub HTTP request: ~300-800ms (major bottleneck)
  - YAML parsing: ~10-50ms
- **Cache hit** (subsequent access): <10ms (3x-100x faster)

**Why Caching is Needed:**
ConfigStore data is **immutable** after ART announces a release. Without caching, every MCP tool call pays the full initialization cost even for the same release. For typical AI agent workflows accessing the same release multiple times, this results in significant latency reduction.

**Example Performance Gain:**
```
Without cache (3 tool calls for same release):
- oar_get_release_metadata('4.19.1'): 1000ms
- oar_is_release_shipped('4.19.1'): 1000ms
- oar_get_release_status('4.19.1'): 1000ms
Total: ~3000ms

With cache (3 tool calls for same release):
- oar_get_release_metadata('4.19.1'): 1000ms (cache miss)
- oar_is_release_shipped('4.19.1'): <10ms (cache hit)
- oar_get_release_status('4.19.1'): <10ms (cache hit)
Total: ~1020ms (3x faster)
```

**Cache Management Tools:**
- `mcp_cache_stats()` - View cache hit rate, size, and entries
- `mcp_cache_invalidate(release)` - Manually refresh cache for specific release
- `mcp_cache_warm(releases)` - Pre-populate cache before operations

**Manual Invalidation:**
Rarely needed since ConfigStore data is immutable. Only required if ART updates build data after initial announcement (exceptional case). Use `mcp_cache_invalidate("4.19.1")` to refresh.

**Note:** Caching is **only used in MCP server**, not in CLI commands (which are short-lived processes where caching provides no benefit).

### StateBox and Release State Tracking

**StateBox** is the primary state management system for new releases:
- GitHub-backed YAML storage at `_releases/{y-stream}/statebox/{release}.yaml`
- Tracks task status: "Not Started" → "In Progress" → "Pass" / "Fail"
- Records task execution results and timestamps
- Manages blocking/non-blocking issues with resolution tracking
- Automatic updates via `cli_result_callback` parsing command output

**Backward Compatibility:**
- Old releases (before StateBox migration) use Google Sheets test reports
- Commands automatically detect and use appropriate system
- Google Sheets still supported via `WorksheetManager` for legacy releases

**Task Status Logging:**
All CLI commands use `util.log_task_status()` to output status markers:
- Logs format: `"task [{Display Name}] status is changed to [{Status}]"`
- `cli_result_callback` parses last line to auto-update StateBox
- Ensures consistent status tracking without explicit StateBox calls

### State Persistence

The system uses GitHub repository (`_releases/` directory on `record` branch) for persistent state:
- Current build tracking files
- Test result JSON files
- Aggregation status markers

### Background Processing

The `ApprovalOperator` implements background scheduler with:
- File-based locking (`/tmp/oar_scheduler_*.lock`)
- Periodic metadata URL checks (every 30 minutes)
- Timeout handling (2 days default)
- Logs in `/tmp/oar_logs/metadata_checker_*.log`

## Typical Release Workflow

```bash
# 1. Initialize release tracking
oar -r 4.19.1 create-test-report

# 2. Assign ownership
oar -r 4.19.1 take-ownership -e owner@redhat.com

# 3. Sync bug status (run multiple times during release)
oar -r 4.19.1 update-bug-list

# 4. Verify payload images
oar -r 4.19.1 image-consistency-check
oar -r 4.19.1 image-consistency-check -n <build-number>  # Check status

# 5. Validate CVP tests
oar -r 4.19.1 check-greenwave-cvp-tests

# 6. Check CVE coverage
oar -r 4.19.1 check-cve-tracker-bug

# 7. Push to staging
oar -r 4.19.1 push-to-cdn-staging

# 8. Run stage tests
oar -r 4.19.1 stage-testing
oar -r 4.19.1 stage-testing -n <build-number>  # Check status

# 9. Verify signatures
oar -r 4.19.1 image-signed-check

# 10. Clean up unverified bugs
oar -r 4.19.1 drop-bugs

# 11. Finalize and approve
oar -r 4.19.1 change-advisory-status
```

## Code Navigation Tips

**Working with advisories:** Start in `oar/core/advisory.py` → `AdvisoryManager` class

**Understanding bug operations:** Check `oar/core/operators.py` → `BugOperator` for cross-module orchestration

**Modifying CLI commands:** Look in `oar/cli/` for Click command definitions

**Job controller logic:** `prow/job/controller.py` contains both `JobController` and `TestResultAggregator`

**Notification logic:** `oar/core/notification.py` → `MessageHelper` for message formatting templates

**Shipment/GitLab workflow:** `oar/core/shipment.py` → `ShipmentData` and `GitLabMergeRequest`

## Version Support

Currently supports OpenShift versions: 4.12.z through 4.20.z

When adding new version support, update:
1. Jira query filters (`oar/notificator/jira_notificator.py`)
2. Job registry configurations
3. Test report templates
4. Jenkins job parameters (stage-testing, image-consistency-check)
5. ConfigStore config (test template doc ID, Slack group alias)

## Authentication Notes

- **Kerberos required** for Errata Tool and LDAP access: `kinit $kid@$domain`
- **Bugzilla credentials** cached in `~/.config/python-bugzilla/bugzillarc`
- **GitHub token** needs `repo` scope for private repositories
- All tokens should be kept in secure storage (Bitwarden, environment variables)

## Common Pitfalls

1. **Missing `OAR_JWK`**: ConfigStore will fail to decrypt config
2. **Expired Kerberos ticket**: Errata Tool and LDAP operations will fail
3. **Stale lock files**: Background processes may appear stuck - check `/tmp/oar_scheduler_*.lock`
4. **Version format**: Release version must be z-stream format (e.g., 4.19.1, not 4.19)

## External Dependencies

**ART Tools** (installed from git):
- `artcommon` - Common ART utilities
- `pyartcd` - ART CD tooling
- `rh-elliott` - CVE tracker bug checking
- `rh-doozer` - Build data management

These are installed automatically from `openshift-eng/art-tools` repository.

## Documentation

- `AGENTS.md` - Comprehensive documentation of all agents, CLI commands, and core modules
- `README.md` - Quick start and installation
- `oar/README.md` - Additional OAR command details
- `docs/` - Additional documentation

## Development Guidelines

**When modifying OAR commands:**
1. Commands are defined in `oar/cli/`
2. Business logic should be in `oar/core/` modules
3. Complex multi-module operations belong in `oar/core/operators.py`
4. Always use `util.log_task_status()` for status tracking (auto-updates StateBox via cli_result_callback)
5. Add proper exception handling using custom exceptions from `oar/core/exceptions.py`
6. Use StateBox for explicit issue tracking when tasks detect blocking problems

**When adding new integrations:**
1. Create new module in `oar/core/`
2. Follow Manager/Helper pattern
3. Integrate with ConfigStore
4. Add custom exception types
5. Add unit tests in `tests/`

**For background processes:**
1. Use file-based locking to prevent duplicates
2. Implement proper timeout handling
3. Log to dedicated log files
4. Clean up resources on exit
