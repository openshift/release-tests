# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ERT (Errata Reliability Team) Release Tests** - A Python-based automation framework for managing OpenShift z-stream releases. This project automates QE tasks throughout the release lifecycle, including advisory management, bug tracking, test execution, and release approval workflows.

**Key Technologies:**
- Python 3.11+
- Click framework (CLI)
- Google Sheets API (test report tracking)
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

This project provides two main CLI entry points:

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
- `worksheet.py` - Google Sheets test reports (requires GCP service account)
- `notification.py` - Slack notifications
- `shipment.py` - GitLab MR management for Konflux workflow
- `jenkins.py` - Jenkins job triggering and monitoring
- `ldap.py` - LDAP lookups for manager hierarchy
- `git.py` - Git operations for shipment data

**Orchestration Layer:**
- `operators.py` - Composite operators that coordinate across multiple modules (ReleaseOwnershipOperator, BugOperator, ApprovalOperator, etc.)

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

## Environment Variables

**Critical for OAR CLI:**
- `OAR_JWK` - Encryption key for config_store.json (from Bitwarden: *openshift-qe-trt-env-vars*)
- `JIRA_TOKEN` - Jira personal access token
- `GCP_SA_FILE` - Google Cloud service account credentials file path
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

### Test Report Workflow

Every OAR command integrates with Google Sheets test report:
- Task status auto-updated: "In Progress" → "Pass" / "Fail"
- Overall status tracked: "Green" / "Red"
- Provides real-time visibility into release progress

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
4. Always update task status in Google Sheets test report
5. Add proper exception handling using custom exceptions from `oar/core/exceptions.py`

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
