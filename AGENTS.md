# Automated Agents and Services

This document describes the automated agents, controllers, and background services used in the ERT (Errata Reliability Team) release-tests project. These automated systems help manage OpenShift z-stream releases by handling testing, notifications, and release workflows.

## Table of Contents

- [Overview](#overview)
- [Automated Agents and Services](#automated-agents-and-services)
  - [1. Release Detector](#1-release-detector)
  - [2. Job Controller](#2-job-controller)
  - [3. Test Result Aggregator](#3-test-result-aggregator)
  - [4. Jira Notificator](#4-jira-notificator)
  - [5. Slack Message Receiver (Release Bot)](#5-slack-message-receiver-release-bot)
  - [6. Test Result Checker](#6-test-result-checker)
- [OAR CLI Tool (OpenShift Automatic Release)](#oar-cli-tool-openshift-automatic-release)
  - [Available Commands](#available-commands)
  - [Command Workflow](#command-workflow)
- [OAR Core Modules](#oar-core-modules)
  - [Core Module Architecture](#core-module-architecture)
  - [Module List](#module-list)
- [Integration and Workflow](#integration-and-workflow)
- [Deployment Considerations](#deployment-considerations)
- [Monitoring and Observability](#monitoring-and-observability)
- [Troubleshooting](#troubleshooting)
- [Version Compatibility](#version-compatibility)

## Overview

The ERT release-tests project contains several automated agents and services that work together to streamline the OpenShift release process. These systems monitor release streams, trigger tests, aggregate results, send notifications, and support release operations.

## Automated Agents and Services

### 1. Release Detector

**Location:** `oar/controller/detector.py`

**Purpose:** Automatically detects new z-stream releases by comparing the latest z-stream version from ART (OpenShift ART team) with the latest stable version from the release stream.

**How it works:**
- Fetches the latest z-stream version from a GitHub repository file maintained by ART
- Fetches the latest stable version from the OpenShift release stream API
- Compares versions using semantic versioning
- When a new z-stream release is detected, automatically creates a test report to kickoff the QE release flow (see [create-test-report](#1-create-test-report) CLI command)

**Trigger:** Can be run on-demand via CLI command:
```bash
oarctl start-release-detector -r <minor-release>
```

**Key Components:**
- `ReleaseDetector.get_latest_zstream_version()` - Gets latest version from ART
- `ReleaseDetector.get_latest_stable_version()` - Gets latest stable from release stream
- `ReleaseDetector.compare_versions()` - Compares versions
- `ReleaseDetector.start()` - Entry point that orchestrates detection and report creation

---

### 2. Job Controller

**Location:** `prow/job/controller.py`

**Purpose:** Monitors OpenShift release streams for new builds (nightly or stable) and automatically triggers Prow test jobs when new builds are detected.

**How it works:**
- Continuously monitors release streams for new builds across multiple architectures (amd64, arm64, multi, ppc64le, s390x)
- Compares the latest build with the current tracked build
- When a new build is detected:
  - Updates the current build tracking file in GitHub
  - Triggers configured Prow jobs based on the job registry
  - Saves test result tracking files to GitHub
- Supports both nightly builds and stable builds
- Handles upgrade jobs and regular installation jobs

**Trigger:** Can be run as a continuous monitoring service or on-demand:
```bash
jobctl start-controller -r <release> --nightly --arch <architecture>
```

**Key Components:**
- `JobController` - Main controller class
- `JobController.get_latest_build()` - Fetches latest build from release stream
- `JobController.get_current_build()` - Gets currently tracked build from GitHub
- `JobController.trigger_prow_jobs()` - Triggers all configured test jobs for a build
- `TestJobRegistry` - Manages test job definitions per release/architecture
- `GithubUtil` - Handles file operations in the GitHub repository

**Environment Variables Required:**
- `GITHUB_TOKEN` - GitHub authentication
- `APITOKEN` - Prow/Gangway API authentication

---

### 3. Test Result Aggregator

**Location:** `prow/job/controller.py`

**Purpose:** Continuously processes test results from Prow jobs, determines pass/fail status, implements retry logic for failed tests, and promotes builds when all required tests pass.

**How it works:**
- Scans GitHub repository for test result files
- For each test result file:
  - Checks if all jobs are completed
  - Fetches detailed test results from GCS artifacts
  - Implements retry logic for failed non-optional jobs
  - Calculates metrics (total, success, failed, pending, required)
  - Determines if build is QE accepted (all required jobs pass)
  - Updates releasepayload with QE acceptance label in OpenShift cluster
  - Marks result files as aggregated when complete
- Deletes result files for recycled/old nightly builds

**Trigger:** Runs as a continuous monitoring service:
```bash
jobctl start-aggregator --arch <architecture>
```

**Key Components:**
- `TestResultAggregator` - Main aggregator class
- `TestResultAggregator.start()` - Main processing loop
- `TestMetrics` - Tracks test result statistics
- `ProwJobResult` - Represents individual Prow job results
- `TestJobResult` - Represents test job with retries
- `Artifacts` - Fetches test reports from GCS

**Environment Variables Required:**
- `GITHUB_TOKEN` - GitHub authentication
- `APITOKEN` - Prow/Gangway API authentication
- `GCS_CRED_FILE` - Google Cloud Storage credentials for artifact access

**Acceptance Criteria:**
A build is marked as "QE Accepted" when all required (non-optional) jobs pass, either on first run or after retries.

---

### 4. Jira Notificator

**Location:** `oar/notificator/jira_notificator.py`

**Purpose:** Automatically monitors Jira issues in ON_QA status and sends escalating notifications to QA contacts, team leads, and managers when issues remain unverified for extended periods.

**How it works:**
- Queries Jira for OCPBUGS issues in ON_QA status for active z-stream releases
- Tracks when issues transitioned to ON_QA status
- Implements a three-tier escalation process based on weekday hours:
  1. After 24 weekday hours: Notifies QA Contact
  2. After 48 weekday hours: Notifies Team Lead (currently still notifies QA contact)
  3. After 72 weekday hours: Notifies Manager
- If contacts are missing, falls back to notifying assignee and their manager
- Integrates with LDAP to look up manager information
- Only counts weekday hours (Monday-Friday) for time calculations
- Adds Jira comments with @mentions to notify responsible people

**Trigger:** Can be run on-demand or scheduled via cron:
```bash
oarctl jira-notificator [--dry-run] [--from-date YYYY-MM-DD]
```

**Key Components:**
- `NotificationService` - Main notification service class
- `NotificationType` - Enum defining notification types (QA_CONTACT, TEAM_LEAD, MANAGER, ASSIGNEE)
- `NotificationService.check_issue_and_notify_responsible_people()` - Main logic
- `NotificationService.is_more_than_24_weekday_hours()` - Calculates weekday hours
- `NotificationService.get_on_qa_issues()` - Queries Jira for ON_QA issues
- `LdapHelper` - LDAP integration for manager lookup

**Environment Variables Required:**
- `JIRA_TOKEN` - Jira authentication token

**Options:**
- `--dry-run` - Test mode that doesn't send actual Jira comments
- `--from-date` - Only process issues that transitioned to ON_QA after this date
- `--search-batch-size` - Number of issues to fetch per batch (default: 100)

---

### 5. Slack Message Receiver (Release Bot)

**Location:** `tools/slack_message_receiver.py`

**Purpose:** Provides a Slack bot interface that listens for messages in Slack channels and executes OAR CLI commands or answers questions using an AI model.

**How it works:**
- Connects to Slack using Socket Mode (WebSocket connection)
- Listens for messages and @mentions in configured channels
- Detects OAR commands (messages starting with `oar` or `oarctl`)
- Executes OAR commands and posts results back to Slack thread
- Optionally integrates with LLM (Language Model) to answer general questions
- Sets environment variables to enable background Slack notifications from OAR commands
- Splits large command outputs into multiple messages to avoid Slack limits

**Trigger:** Runs as a long-running service/daemon:
```bash
python tools/slack_message_receiver.py
```

**Key Components:**
- `SocketModeClient` - Slack WebSocket client
- `process()` - Main message handler
- `is_oar_related_message()` - Detects OAR commands
- `send_prompt_to_ai_model()` - Optional LLM integration
- `get_username()` - Fetches Slack user information

**Environment Variables Required:**
- `SLACK_APP_TOKEN` - Slack app-level token for Socket Mode
- `SLACK_BOT_TOKEN` - Slack bot token for API calls

**Optional (for AI features):**
- `MODEL_API_BASE` - OpenAI-compatible API endpoint
- `MODEL_API_KEY` - API authentication key
- `MODEL_API_NAME` - Model name to use

**Features:**
- Command execution in Slack threads
- Automatic code formatting of command output
- Thread-based responses to keep conversations organized
- Optional AI-powered question answering

---

### 6. Test Result Checker

**Location:** `tools/auto_release_test_result_checker.py`

**Purpose:** Monitors the GitHub repository for rejected test results and sends Slack notifications when builds fail QE acceptance criteria.

**How it works:**
- Scans the `_releases` directory in GitHub repository for test result JSON files
- Checks if test results have `"accepted": false` (build rejected)
- Ignores manually promoted builds
- Tracks previously notified files to avoid duplicate notifications
- Sends Slack notifications with links to rejected build result files
- Limits initial notifications when first run
- Sorts files by name (reverse order) to process newest first

**Trigger:** Typically run on a schedule (cron job):
```bash
python tools/auto_release_test_result_checker.py \
  --repo-name openshift/release-tests \
  --slack-channel <channel-name> \
  [--notified-file-path notified_files.txt] \
  [--limit 5]
```

**Key Components:**
- `TestResultChecker` - Main checker class
- `TestResultChecker.iterate_test_result_files()` - Scans and processes files
- `TestResultChecker.check_file()` - Checks individual result file
- `TestResultChecker.send_slack_notification()` - Sends notification
- File tracking system to avoid duplicate notifications

**Environment Variables Required:**
- `GITHUB_TOKEN` - GitHub authentication
- `SLACK_BOT_TOKEN` - Slack bot token

**Options:**
- `--repo-name` - GitHub repository (format: owner/repo)
- `--slack-channel` - Target Slack channel for notifications
- `--notified-file-path` - File to track previously notified builds (default: `notified_files.txt`)
- `--limit` - Maximum notifications on first run (default: 5)
- `--path` - Path in repo to scan (default: `_releases`)
- `--branch` - Branch to scan (default: `record`)

---

## OAR CLI Tool (OpenShift Automatic Release)

The OAR CLI is the primary command-line interface for managing OpenShift z-stream releases. It provides a comprehensive set of commands that automate QE tasks throughout the release lifecycle.

### Overview

**Location:** `oar/cli/`

**Purpose:** Provides interactive commands for release managers and QE engineers to execute release tasks, manage advisories, handle bug tracking, trigger tests, and coordinate release workflows.

### Installation

```bash
git clone git@github.com:openshift/release-tests.git
cd release-tests
pip3 install -e .
```

### Configuration

#### Required Environment Variables

**OAR CLI:**
- **OAR_JWK** - Encryption key for config_store.json (stored in Bitwarden: *openshift-qe-trt-env-vars*)
- **JIRA_TOKEN** - Jira personal access token for API access
- **GCP_SA_FILE** - Google Cloud Platform service account credentials file path (optional for new releases using StateBox; required for old releases with Google Sheets)
- **SLACK_BOT_TOKEN** - Slack bot token for sending notifications
- **JENKINS_USER** - Jenkins username (email)
- **JENKINS_TOKEN** - Jenkins API token
- **GITLAB_TOKEN** - GitLab personal access token for shipment MR operations
- **Kerberos ticket** - Required for Errata Tool and LDAP access: `kinit $kid@$domain`
- **Bugzilla credentials** - Cached in `~/.config/python-bugzilla/bugzillarc`

**Release Detector:**
- All OAR CLI environment variables (calls `create-test-report` command)
- **GITHUB_TOKEN** - GitHub personal access token for monitoring repository file changes

**Job Controller:**
- **GITHUB_TOKEN** - GitHub personal access token for repository operations
- **APITOKEN** - Prow/Gangway API token for triggering test jobs

**Test Result Aggregator:**
- **GITHUB_TOKEN** - GitHub personal access token for repository operations
- **APITOKEN** - Prow/Gangway API token for triggering test jobs
- **GCS_CRED_FILE** - Google Cloud Storage credentials file path for test artifact access

**Jira Notificator:**
- **JIRA_TOKEN** - Jira personal access token for API access
- **Kerberos ticket** - For LDAP manager lookup

**Slack Message Receiver (Release Bot):**
- **SLACK_APP_TOKEN** - Slack app-level token for Socket Mode
- **SLACK_BOT_TOKEN** - Slack bot token for API calls
- All OAR CLI environment variables (executes OAR commands)

**Test Result Checker:**
- **GITHUB_TOKEN** - GitHub personal access token for repository operations
- **SLACK_BOT_TOKEN** - Slack bot token for sending notifications

**Note:** `OAR_SLACK_CHANNEL` and `OAR_SLACK_THREAD` are set internally by the Slack bot when executing commands and should not be configured manually by users.

### CLI Architecture

The OAR CLI is built using Click framework with a group-based command structure:

```bash
oar -r <release-version> [OPTIONS] COMMAND [ARGS]
```

**Global Options:**
- `-r, --release` - z-stream release version (e.g., 4.13.6) - **Required**
- `-v, --debug` - Enable debug logging
- `-V, --version` - Show version information
- `-h, --help` - Show help message

### Available Commands

#### 1. create-test-report

**Command:** `oar -r <release> create-test-report`

**Purpose:** Initializes release state tracking for a new z-stream release.

**What it does:**
- **For new releases:** Creates StateBox at `_releases/{y-stream}/statebox/{release}.yaml` with:
  - Metadata from ConfigStore (advisories, JIRA ticket, candidate builds, shipment MR)
  - Initial task status (all "Not Started")
  - Empty issues list for tracking blocking problems
  - Sends Slack notification to QE release team
- **For old releases:** Detects existing Google Sheets test report (backward compatibility)
- Automatically determines whether to use StateBox or Google Sheets

**Output:**
- New releases: StateBox GitHub URL
- Old releases: Google Sheets URL (if exists)

**Note:** StateBox is the primary system for new releases. Google Sheets only used for legacy releases created before StateBox migration.

---

#### 2. take-ownership

**Command:** `oar -r <release> take-ownership -e <owner-email>`

**Purpose:** Assigns ownership of advisory and related JIRA subtasks to a specified person.

**Options:**
- `-e, --email` - Email address of the new owner

**What it does:**
- Takes ownership of the release advisory in Errata Tool
- Updates ownership of QE-related JIRA subtasks created by ART team
- Ensures proper assignment throughout the release workflow

---

#### 3. update-bug-list

**Command:** `oar -r <release> update-bug-list`

**Purpose:** Synchronizes bug status between Bugzilla/Jira and the test report, and sends notifications.

**⚠️ DEPRECATED:** This command is not needed in Konflux release flow. Kept for backward compatibility with Errata flow releases only.

**What it does:**
- Fetches latest bug status from Bugzilla/Jira
- Updates test report with current bug states (Verified/Closed)
- Appends newly attached bugs to the report
- Sends Slack notifications to QA Contacts for bugs needing attention
- Should be run multiple times throughout the release cycle

**Use Case:** Run periodically to keep bug tracking up-to-date (Errata flow only).

**Note:** Will raise error if executed for Konflux flow releases.

---

#### 4. image-consistency-check

**Command:**
```bash
oar -r <release> image-consistency-check
oar -r <release> image-consistency-check -n <build-number>
```

**Purpose:** Verifies that images in the release payload are consistent with advisory contents.

**Options:**
- `-n, --build-number` - Jenkins build number to check status (for subsequent runs)

**What it does:**
- Triggers a Jenkins job to verify image consistency
- Compares images in release payload with images in advisories
- Returns build number on first run
- Can check job status on subsequent runs with build number

**Workflow:**
1. First run: Triggers job, returns build number
2. Subsequent runs: Check status using `-n <build-number>`

---

#### 5. check-greenwave-cvp-tests

**Command:** `oar -r <release> check-greenwave-cvp-tests`

**Purpose:** Validates that all Greenwave CVP (Container Verification Pipeline) tests have passed or been waived.

**What it does:**
- Checks CVP test status for all advisories in the release
- Reports tests with status: PASSED, WAIVED, or FAILED
- Provides test IDs and advisory numbers for failed tests
- Enables triggering "Refetch" for failed tests

**Expected Result:** All tests should be PASSED or WAIVED before proceeding.

**Note:** If tests fail after refetch, contact CVP team via Google Spaces [CVP].

---

#### 6. check-cve-tracker-bug

**Command:** `oar -r <release> check-cve-tracker-bug`

**Purpose:** Identifies any CVE tracker bugs that may have been missed for the current release.

**What it does:**
- Calls `rh-elliott` to scan for CVE tracker bugs
- Checks if all CVE tracker bugs are properly tracked
- Sends Slack notification to ART team if any bugs are found missing
- Helps ensure security vulnerabilities are properly tracked

---

#### 7. push-to-cdn-staging

**Command:** `oar -r <release> push-to-cdn-staging`

**Purpose:** Triggers the push job to promote release artifacts to CDN staging environment.

**Prerequisites:** All Greenwave CVP tests must be PASSED or WAIVED.

**What it does:**
- Triggers push job for default "stage" target
- Does not interrupt existing running jobs
- Prepares release for stage testing

---

#### 8. stage-testing

**Command:**
```bash
oar -r <release> stage-testing
oar -r <release> stage-testing -n <build-number>
```

**Purpose:** Triggers the stage pipeline to perform testing in the staging environment.

**Options:**
- `-n, --build-number` - Jenkins build number to check status (for subsequent runs)

**What it does:**
- Triggers Jenkins stage testing pipeline
- Returns build number on first run
- Can check job status on subsequent runs with build number

**Workflow:**
1. First run: Triggers job, returns build number
2. Subsequent runs: Check status using `-n <build-number>`

---

#### 9. image-signed-check

**Command:** `oar -r <release> image-signed-check`

**Purpose:** Verifies that the release payload images are properly signed.

**What it does:**
- Automatically retrieves digest of stable build
- Checks if the signed image can be found on the mirror site
- Validates signature integrity
- Ensures release meets signing requirements

---

#### 10. drop-bugs

**Command:** `oar -r <release> drop-bugs`

**Purpose:** Manages bugs that are not yet verified, intelligently handling high-severity cases.

**What it does:**
- Scans all bugs from advisories that are not verified
- Identifies "high severity" bugs:
  - Critical priority bugs
  - CVE Tracker bugs
  - Customer Case-related bugs
- For high severity bugs: Sends Slack notification to bug owner for confirmation
- For other bugs: Automatically drops them from the advisory
- Helps clean up advisory before release

---

#### 11. change-advisory-status

**Command:** `oar -r <release> change-advisory-status`

**Purpose:** Changes advisory status (e.g., to REL_PREP) and finalizes QE tasks.

**What it does:**
- Changes advisory status in Errata Tool
- Closes QE-related JIRA subtasks
- Checks for blocking secalerts (for RHSA advisories)
- Throws appropriate error messages if validation fails
- Final step before release approval

---

### Command Workflow

A typical z-stream release workflow using OAR commands:

```
1. create-test-report          # Initialize release tracking
2. take-ownership              # Assign ownership
3. update-bug-list             # First bug sync
   (wait for builds/testing)
4. update-bug-list             # Periodic bug updates (run multiple times)
5. image-consistency-check     # Verify payload images
6. check-greenwave-cvp-tests   # Validate CVP tests
7. check-cve-tracker-bug       # Verify CVE coverage
8. push-to-cdn-staging         # Push to staging
9. stage-testing               # Run stage tests
10. image-signed-check         # Verify signatures
11. drop-bugs                  # Clean up unverified bugs
12. change-advisory-status     # Finalize and approve
```

### ConfigStore

**Location:** `oar/core/configstore.py`

The ConfigStore class manages release-specific configuration:
- Loads encrypted configuration from `config_store.json`
- Stores advisory information, Jira references, Google Sheet URLs
- Provides context for all OAR commands
- Uses JWE encryption for sensitive data (decrypted using `OAR_JWK` environment variable)

### Task Status Tracking

**StateBox (Primary for New Releases):**
All OAR commands use `util.log_task_status()` to output status markers:
- Logs format: `"task [{Display Name}] status is changed to [{Status}]"`
- `cli_result_callback` automatically parses last line of command output
- Auto-updates StateBox task status without explicit StateBox calls
- Task states: "Not Started" → "In Progress" → "Pass" / "Fail"
- Task results and timestamps recorded in StateBox YAML
- Issues tracked with blocker/non-blocker classification

**Google Sheets (Legacy Releases Only):**
- Old releases use `WorksheetManager` for test report tracking
- Task status updated via explicit `report.update_task_status()` calls
- Overall status tracked as "Green" / "Red"
- Provides backward compatibility for releases before StateBox migration

### Integration with Automated Agents

The OAR CLI can be:
- **Executed manually** by release managers and QE engineers
- **Triggered automatically** by the Slack bot (via `tools/slack_message_receiver.py`)
- **Called programmatically** by automated agents (e.g., Release Detector calls `create-test-report`)

---

## OAR Core Modules

The OAR CLI is built on a foundation of core modules located in `oar/core/` that provide essential functionality for interacting with external systems and managing release workflows.

### Core Module Architecture

All core modules follow a consistent pattern:
- Manager/Helper classes that encapsulate API interactions
- Exception handling with custom exception types
- Integration with ConfigStore for configuration management
- Logging for observability

### 1. Advisory Module (`oar/core/advisory.py`)

**Purpose:** Manages interactions with Red Hat Errata Tool for advisory operations.

**Key Classes:**
- `AdvisoryManager` - High-level manager for advisory operations
- `Advisory` - Wrapper around Erratum with extended functionality

**Key Functionality:**
- Get/update advisories for a release
- Change advisory ownership (QE email)
- Check Greenwave CVP test status
- Push advisories to CDN (stage/live)
- Change advisory status (QE → REL_PREP → SHIPPED LIVE)
- Drop bugs from advisories
- Check CVE tracker bugs using Elliott
- Validate advisory health grades (A/B/C/D/F)
- Check for blocking security alerts
- Manage advisory dependencies (blocking advisories)

**Key Methods:**
- `get_advisories()` - Get all advisories for current release
- `change_ad_owners()` - Change QA owner across all advisories
- `check_greenwave_cvp_tests()` - Validate CVP test results
- `push_to_cdn_staging()` - Trigger CDN push jobs
- `change_advisory_status()` - Move advisory through workflow states
- `drop_bugs()` - Remove unverified non-CVE bugs
- `check_cve_tracker_bug()` - Find missing CVE tracker bugs

**Dependencies:** Requires Kerberos ticket for Errata Tool access

---

### 2. Worksheet Module (`oar/core/worksheet.py`)

**Purpose:** Manages Google Sheets test reports for tracking release progress.

**Key Classes:**
- `WorksheetManager` - Creates and manages test report worksheets
- `TestReport` - Wrapper for worksheet operations

**Key Functionality:**
- Create test reports from templates
- Update advisory/shipment information
- Update candidate build information
- Track bug status (ON_QA, Verified, Closed, Dropped)
- Update task checklist status (Pass/Fail/In Progress)
- Manage overall status (Green/Red)
- Add hyperlinks with advanced formatting
- Track CVE tracker bugs
- Support both Errata and Konflux workflows

**Key Methods:**
- `create_test_report()` - Create new report from template
- `update_bug_list()` - Sync bug status with Jira/Bugzilla
- `update_task_status()` - Update checklist item status
- `are_all_bugs_verified()` - Check if all bugs are verified
- `update_cell_with_hyperlinks()` - Advanced cell formatting with links

**Dependencies:** Requires Google Service Account credentials

---

### 3. Jira Module (`oar/core/jira.py`)

**Purpose:** Manages interactions with Red Hat Jira for issue tracking.

**Key Classes:**
- `JiraManager` - Jira API client wrapper
- `JiraIssue` - Wrapper for Jira issue with helper methods

**Key Functionality:**
- Get/create/update Jira issues
- Query issue status and metadata
- Change issue assignees
- Manage ART subtasks
- Identify high-severity issues (Critical, Blocker, Customer Cases, CVE)
- Filter issues by verification status
- Create CVP failure tracking issues

**Key Methods:**
- `get_issue()` - Fetch issue by key
- `create_issue()` - Create new Jira issue
- `get_sub_tasks()` - Get subtasks from parent ticket
- `change_assignee_of_qe_subtasks()` - Reassign QE subtasks
- `close_qe_subtasks()` - Close QE subtasks when release completes
- `get_unverified_cve_issues()` - Find unverified CVE bugs
- `get_high_severity_and_can_drop_issues()` - Categorize bugs for dropping

**Issue Classification:**
- `is_cve_tracker()` - CVE security bugs
- `is_critical_issue()` - Critical/Blocker priority or TestBlocker label
- `is_customer_case()` - Has SFDC cases attached
- `is_high_severity_issue()` - Any of the above

---

### 4. Notification Module (`oar/core/notification.py`)

**Purpose:** Sends notifications via Slack (and optionally email) for release events.

**Key Classes:**
- `NotificationManager` - High-level notification orchestrator
- `SlackClient` - Slack API wrapper
- `MessageHelper` - Formats messages for different notification types

**Key Functionality:**
- Send Slack messages to channels and threads
- User/group ID lookup for @mentions
- Format messages with hyperlinks
- Split large messages to respect Slack limits
- Support for threaded responses (OAR_SLACK_CHANNEL/OAR_SLACK_THREAD env vars)
- Message template system for consistent formatting

**Notification Types:**
- New StateBox creation (new releases)
- New test report creation (legacy releases)
- Ownership changes (advisories/subtasks)
- Bug verification requests
- High severity bug confirmations
- CVE tracker bug alerts
- Advisory health warnings
- Jenkins build status
- Shipment MR updates
- Release approval completion

**Key Methods:**
- `share_new_statebox()` - Notify about new StateBox creation (new releases)
- `share_new_report()` - Notify about new test report (legacy releases)
- `share_bugs_to_be_verified()` - Remind QA contacts to verify bugs
- `share_high_severity_bugs()` - Confirm dropping high-severity bugs
- `share_new_cve_tracker_bugs()` - Alert about missing CVE trackers
- `share_release_approval_completion()` - Notify about release completion

---

### 5. Shipment Module (`oar/core/shipment.py`)

**Purpose:** Manages GitLab merge requests for Konflux shipment data.

**Key Classes:**
- `ShipmentData` - Main interface for shipment operations
- `GitLabMergeRequest` - GitLab MR wrapper with rich functionality
- `GitLabServer` - Server-level GitLab operations
- `ImageHealthData` - Container for image health check results

**Key Functionality:**
- Parse and interact with shipment YAML files
- Extract Jira issues from shipment data
- Add QE approval to shipment MRs
- Check pipeline status (stage-release, prod-release)
- Create/update "drop bugs" merge requests
- Check container image health via Pyxis API
- Add comments and suggestions to MRs
- Support for forked repository workflows

**Key Methods:**
- `get_jira_issues()` - Extract Jira issues from shipment YAMLs
- `add_qe_approval()` - Approve shipment MR
- `is_stage_release_success()` - Check if stage release completed
- `drop_bugs()` - Create MR to remove unverified bugs
- `check_component_image_health()` - Validate container image freshness grades
- `add_image_health_summary_comment()` - Report image health to MR
- `check_cve_tracker_bug()` - Find missing CVE trackers in shipment

**GitLab Features:**
- File content retrieval with caching
- Pipeline and stage monitoring
- Auto-merge support
- Comment and suggestion management
- Branch creation and management

---

### 6. Jenkins Module (`oar/core/jenkins.py`)

**Purpose:** Triggers and monitors Jenkins CI/CD jobs.

**Key Classes:**
- `JenkinsHelper` - Jenkins job orchestration

**Key Functionality:**
- Trigger stage testing pipeline
- Trigger image consistency check jobs
- Monitor job queue and execution
- Validate job parameters match release version
- Get build status with detailed error handling

**Supported Jobs:**
- `stage-pipeline` - Stage environment testing
- `image-consistency-check` - Verify payload images match advisories

**Key Methods:**
- `call_stage_job()` - Trigger stage testing
- `call_image_consistency_job()` - Trigger image consistency validation
- `get_build_status()` - Check job status by build number
- `is_job_enqueue()` - Check if job is queued

---

### 7. Utility Module (`oar/core/util.py`)

**Purpose:** Common utility functions used across OAR.

**Key Functions:**
- **Version validation:** `is_valid_z_release()`, `validate_release_version()`, `get_y_release()`
- **URL builders:** `get_jira_link()`, `get_advisory_link()`, `get_ocp_test_result_url()`
- **Email validation:** `is_valid_email()`
- **MR parsing:** `parse_mr_url()` - Extract project/MR ID from GitLab URLs
- **Logging:** `init_logging()` - Configure logging with SSL warning suppression
- **Message splitting:** `split_large_message()` - Split content for Slack limits
- **Payload validation:** `is_payload_metadata_url_accessible()` - Check if release metadata is available

---

### 8. ConfigStore Module (`oar/core/configstore.py`)

**Purpose:** Centralized configuration management for releases.

**Key Functionality:**
- Load/decrypt `config_store.json` using JWE encryption (OAR_JWK env var)
- Store release-specific settings (advisories, Jira tickets, builds, owners)
- Provide access to external service credentials
- Support both Errata and Konflux workflow modes

**Configuration Data:**
- Release version and metadata
- Advisory IDs (image, extras, metadata, rpm, microshift)
- ART Jira ticket reference
- Candidate nightly builds
- Owner email address
- Google Sheets template and service account
- External service URLs and tokens
- Slack channels and user groups
- Shipment MR URL (Konflux flow)

---

### 9. Git Module (`oar/core/git.py`)

**Purpose:** Git repository operations for shipment data management.

**Key Classes:**
- `GitHelper` - Git command wrapper

**Key Functionality:**
- Clone repositories with authentication
- Create and checkout branches
- Configure remote repositories
- Commit and push changes
- Support for forked repository workflows

---

### 10. LDAP Module (`oar/core/ldap.py`)

**Purpose:** LDAP queries for organizational hierarchy.

**Key Classes:**
- `LdapHelper` - LDAP client for Red Hat directory

**Key Functionality:**
- Look up manager email by employee email
- Support Jira notification escalation workflows

---

### 11. Operators Module (`oar/core/operators.py`)

**Purpose:** Provides composite operator classes that orchestrate operations across multiple core modules for complex workflows.

**Key Classes:**
- `ReleaseOwnershipOperator` - Handles ownership updates across advisories and shipments
- `BugOperator` - Manages bug operations across both advisory and shipment sources
- `ApprovalOperator` - Handles approval operations based on release flow type (Errata or Konflux)
- `ImageHealthOperator` - Checks image container health for both advisory and shipment data
- `CVETrackerOperator` - Handles CVE tracker bug checking across both sources
- `NotificationOperator` - Manages notifications based on release flow type
- `LogCaptureHandler` - Custom logging handler to capture log messages for background processes

**Key Functionality:**
- Orchestrate complex operations across multiple modules
- Support both Errata and Konflux workflow modes
- Handle background processes with proper locking mechanisms
- Schedule periodic checks with timeout handling
- Aggregate data from multiple sources (advisories + shipments)

**Key Methods:**
- `ReleaseOwnershipOperator.update_owners()` - Update ownership across all sources
- `BugOperator.get_jira_issues()` - Get combined Jira issues from all sources
- `BugOperator.drop_bugs()` - Execute bug drop across advisories and shipments
- `ApprovalOperator.approve_release()` - Execute approval with metadata URL checking
- `ImageHealthOperator.check_image_health()` - Check container health across sources
- `CVETrackerOperator.check_cve_tracker_bugs()` - Find missed CVE tracker bugs

**Background Processing:**
- Implements scheduler with file-based locking to prevent duplicate instances
- Periodic metadata URL accessibility checking (every 30 minutes)
- Automatic advisory status changes when metadata becomes accessible
- Timeout handling (2 days default)
- Proper cleanup and notification on completion/timeout/error

**Dependencies:** Integrates AdvisoryManager, ShipmentData, JiraManager, NotificationManager, WorksheetManager

---

### Module Dependencies

```
ConfigStore (foundation)
    ├── AdvisoryManager
    ├── WorksheetManager
    ├── JiraManager
    ├── NotificationManager
    ├── ShipmentData
    ├── JenkinsHelper
    └── Utility functions

External APIs:
    ├── Errata Tool (advisory.py) → Kerberos auth
    ├── Jira (jira.py) → JIRA_TOKEN
    ├── Google Sheets (worksheet.py) → Service Account
    ├── Slack (notification.py) → SLACK_BOT_TOKEN
    ├── GitLab (shipment.py) → GITLAB_TOKEN
    ├── Jenkins (jenkins.py) → JENKINS_USER/JENKINS_TOKEN
    └── LDAP (ldap.py) → Kerberos auth
```

### Exception Handling

Custom exception types in `oar/core/exceptions.py`:
- `AdvisoryException` - Errata Tool errors
- `StateBoxException` - StateBox YAML state management errors
- `WorksheetException` - Google Sheets errors
- `JiraException` / `JiraUnauthorizedException` - Jira errors
- `NotificationException` - Slack/email errors
- `ShipmentDataException` - GitLab/shipment errors
- `GitLabMergeRequestException` / `GitLabServerException` - GitLab API errors
- `JenkinsException` - Jenkins errors

---

## Integration and Workflow

These automated agents work together to provide an end-to-end automated release workflow:

1. **Release Detector** identifies new z-stream releases and creates initial test reports
2. **Job Controller** monitors for new builds and triggers Prow test jobs
3. **Test Result Aggregator** processes test results, retries failures, and accepts builds
4. **Test Result Checker** notifies the team about rejected builds via Slack
5. **Jira Notificator** ensures bugs in ON_QA status are verified in a timely manner
6. **Slack Bot** provides interactive access to OAR commands from Slack

## Deployment Considerations

Most of these agents are designed to run as:
- **Continuous services** (controllers, aggregator, Slack bot) - typically deployed in containers or as systemd services
- **Scheduled jobs** (detectors, checkers, notificators) - typically deployed as cron jobs or Kubernetes CronJobs

### Recommended Deployment:

**Continuous Services:**
- Job Controller (per architecture)
- Test Result Aggregator (per architecture)
- Slack Message Receiver

**Scheduled Jobs:**
- Release Detector (e.g., every 4-6 hours)
- Jira Notificator (e.g., every 2-4 hours)
- Test Result Checker (e.g., every 30 minutes)

## Monitoring and Observability

All agents use Python's standard `logging` module with configurable log levels. Key events to monitor:

- New releases detected
- New builds found
- Test jobs triggered
- Test results aggregated
- Builds accepted/rejected
- Notifications sent
- Errors and exceptions

## Configuration

Most agents rely on:
- **Environment variables** for credentials and API tokens
- **GitHub repository** for persistent state (build tracking, test results)
- **Job registry files** in the repository to define which tests to run
- **OAR configuration** for release-specific settings

See individual agent sections above for specific environment variables required.

---

## Troubleshooting

### Common Issues and Solutions

#### Authentication Issues

**Problem:** `JIRA_TOKEN` authentication fails
- **Solution:** Regenerate your Jira personal access token at https://issues.redhat.com
- **Verify:** Test with `curl -H "Authorization: Bearer $JIRA_TOKEN" https://issues.redhat.com/rest/api/2/myself`

**Problem:** Kerberos ticket expired for Errata Tool access
- **Solution:** Renew your Kerberos ticket: `kinit $kid@$domain`
- **Verify:** Check ticket status with `klist`

**Problem:** GitHub token permissions insufficient
- **Solution:** Ensure token has `repo` scope for private repositories
- **Verify:** Test with `gh auth status`

#### Agent-Specific Issues

**Release Detector**
- **Problem:** Cannot detect new releases
- **Check:** Verify GitHub repository access and ART's version file location
- **Debug:** Run with `-v` flag for verbose logging: `oarctl start-release-detector -r 4.19 -v`

**Job Controller**
- **Problem:** Prow jobs not triggering
- **Check:** Verify `APITOKEN` for Gangway authentication
- **Check:** Ensure job registry files are properly configured in the repository
- **Debug:** Check GitHub tracking files in `_releases` directory

**Test Result Aggregator**
- **Problem:** Results not being aggregated
- **Check:** Verify `GCS_CRED_FILE` path and credentials
- **Check:** Ensure result files exist in GitHub repository
- **Debug:** Check for errors in aggregator logs regarding GCS access

**Jira Notificator**
- **Problem:** Notifications not sent to Jira
- **Check:** Verify Jira token has permission to comment on issues
- **Check:** Confirm LDAP connectivity for manager lookups
- **Debug:** Use `--dry-run` flag to test without sending actual comments

**Slack Bot**
- **Problem:** Bot not responding to commands
- **Check:** Verify both `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` are set
- **Check:** Ensure bot is invited to the channel
- **Debug:** Check WebSocket connection logs for Socket Mode

#### OAR CLI Issues

**Problem:** ConfigStore cannot decrypt configuration
- **Solution:** Verify `OAR_JWK` environment variable is set correctly
- **Location:** JWK is stored in Bitwarden: *openshift-qe-trt-env-vars*

**Problem:** Google Sheets API access fails
- **Solution:** Verify Google Service Account credentials are properly configured
- **Check:** Ensure service account has edit permissions on the spreadsheet

**Problem:** Advisory operations fail
- **Solution:** Ensure you have a valid Kerberos ticket: `kinit $kid@$domain`
- **Check:** Test Errata Tool access: visit https://errata.devel.redhat.com

**Problem:** CVE tracker bug check fails
- **Solution:** Verify `elliott` command is available in PATH
- **Check:** Ensure ocp-build-data repository is accessible

#### Background Process Issues

**Problem:** Approval operator background process not running
- **Check:** Look for lock file in `/tmp/oar_scheduler_*.lock`
- **Debug:** Check logs in `/tmp/oar_logs/metadata_checker_*.log`
- **Solution:** Remove stale lock file if process is not actually running

**Problem:** Metadata URL accessibility check times out
- **Expected:** Default timeout is 2 days
- **Solution:** Check if advisory metadata URL is actually accessible for the release
- **Debug:** Manually test URL: `curl -I https://access.redhat.com/errata/RHBA-2025:17662`
- **Expected Response:** HTTP 200 OK indicates the advisory page is accessible

### Debugging Tips

1. **Enable verbose logging:** Most commands support `-v` or `--debug` flag
2. **Check environment variables:** `env | grep -E '(JIRA|SLACK|GITHUB|OAR)'`
3. **Review recent logs:** Agents use Python logging module with timestamps
4. **Test individual components:** Use dry-run modes where available
5. **Verify external service status:** Check status pages for Jira, GitHub, Slack
6. **Check network connectivity:** Ensure access to internal Red Hat services

---

## Version Compatibility

This project supports the following OpenShift versions for z-stream releases:

**Currently Supported Versions:**
- OpenShift 4.12.z
- OpenShift 4.13.z
- OpenShift 4.14.z
- OpenShift 4.15.z
- OpenShift 4.16.z
- OpenShift 4.17.z
- OpenShift 4.18.z
- OpenShift 4.19.z
- OpenShift 4.20.z

**Workflow Support:**
- **Errata Flow:** Traditional advisory-based workflow (all supported versions)
- **Konflux Flow:** GitLab MR-based shipment workflow (newer versions)

**Note:** Version support is configured in:
- Jira Notificator query filters (`oar/notificator/jira_notificator.py`)
- Job registry files for test definitions
- ConfigStore release validation

When adding support for new OpenShift versions, update:
1. Jira query filters in the notificator
2. Job registry configurations
3. Test report templates
4. Add new ci-profile for stage-testing pipeline
5. Add new release version to parameter `VERSION` of image-consistency-check job
6. Update configstore config to add new test template doc ID and slack group alias for release leads
