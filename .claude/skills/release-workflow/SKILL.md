---
name: release-workflow
description: OpenShift z-stream release workflow and orchestration expert. Use when discussing release tasks, build promotion, test analysis, advisory workflows, or any aspect of the Konflux/Errata release pipeline. Provides context on task sequencing, checkpoints, and MCP execution for releases 4.12-4.20.
allowed-tools: Read
---

# Konflux Release Flow Specification

## Overview

This document defines the complete workflow for OpenShift z-stream release orchestration under the Konflux release platform. All releases from 4.12 to 4.20 follow this flow.

**Target Audience:** AI agents (Claude Code) and human release engineers

**Execution Method:** All `oar` commands are executed via the MCP (Model Context Protocol) server, NOT local CLI. The MCP server exposes OAR commands as structured tools with proper input validation and output parsing.

## Architecture Components

### StateBox (M2 - Primary Source of Truth)
- **Primary source of truth** for AI workflow resumption and task execution state
- Persists in GitHub: `_releases/{y-stream}/statebox/{release}.yaml`
- Stores complete release context:
  - Metadata (advisories, builds, Jira ticket, release date, shipment MR)
  - Task execution history with AI-readable results (sensitive data masked)
  - Blocking issues with resolution tracking
- Enables workflow resumption across multiple AI sessions (hours/days/weeks apart)
- Supports concurrent access via SHA-based optimistic locking
- Automatically updated by all OAR CLI commands (transparent to AI)
- **AI MUST retrieve StateBox state at start of each session**: `oar_get_release_status(release)`

### Google Sheets (Legacy - Human Interface)
- Still updated for backwards compatibility and human visibility
- Each OAR command updates its corresponding task status directly
- Task status: "Not Started" / "In Progress" / "Pass" / "Fail"
- Overall status: "Green" / "Red"
- **Used as fallback** if StateBox doesn't exist (abnormal situation)
- **Note**: AI should always check StateBox first, Google Sheets second

### MCP Server
- Exposes 27 OAR tools for command execution
- Handles authentication, environment setup, error handling
- Returns stdout/stderr for status detection

### Test Result Files
- Stored in GitHub: `_releases/ocp-test-result-{build}-amd64.json`
- Key attributes:
  - `aggregated: true/false` - All test jobs completed and results collected
  - `accepted: true/false` - BO3 verification passed

## Task Graph

```
create-test-report
    ↓
take-ownership
    ↓
check-cve-tracker-bug (always passes, notifies ART)
    ↓
check-rhcos-security-alerts (Konflux only - checks blocking security alerts)
    ↓
    ├─→ push-to-cdn-staging (async - runs independently in parallel)
    └─→ [WAIT FOR BUILD PROMOTION - check API until phase == "Accepted"]
            ↓
            ├─→ image-consistency-check (async - triggered immediately after promotion)
            ├─→ stage-testing (async - triggered immediately after promotion)
            └─→ [WAIT FOR TEST RESULT FILE - check GitHub until file exists]
                    ↓
                [WAIT FOR AGGREGATION - check until aggregated == true]
                    ↓
                analyze-promoted-build (conditionally - only if accepted == false)
                    ↓
                [GATE CHECK - promoted build must be acceptable]
                    ↓
                [WAIT FOR ALL 3 ASYNC TASKS TO COMPLETE]
                (push-to-cdn-staging, image-consistency-check, stage-testing)
                    ↓
                image-signed-check
                    ↓
                change-advisory-status (final approval)

[PARALLEL TRACK - can start immediately]
analyze-candidate-build (conditionally - only if accepted == false)
```

**Key Characteristics:**
- **Sequential:** Most tasks run one after another
- **Parallel Execution:**
  - `analyze-candidate-build` runs independently (tests already completed when flow starts)
  - `push-to-cdn-staging` starts immediately after check-rhcos-security-alerts (runs while waiting for build promotion)
  - **ENHANCED:** 2 async tasks (image-consistency-check, stage-testing) triggered immediately after build promotion is detected, running in parallel with test result analysis
- **Build Promotion Checkpoint:** Critical decision point - once detected, async tasks trigger immediately
- **Test Result Checkpoints:** Must wait for file existence and aggregation (runs in parallel with async tasks)
- **Gate Check:** Promoted build must have acceptable test results before proceeding to final approval
- **Final Sync Point:** image-signed-check waits for BOTH:
  1. All 3 async tasks complete (push-to-cdn-staging, image-consistency-check, stage-testing)
  2. Gate check passes (promoted build analysis acceptable)
- **Default Architecture:** amd64 (x86_64) unless specified otherwise

## Build Promotion Checkpoint

### Build States

**Candidate Build:**
- Nightly build initially selected by ART
- Format: `4.20.0-0.nightly-2025-01-28-123456`
- Retrieved from: `oar_get_release_metadata(release)` → `candidate_builds.x86_64`
- **Test status:** Tests already completed when release flow starts

**Promoted Build:**
- Stable build after ART promotion
- Format: `X.Y.Z` (z-stream version, e.g., 4.20.1)
- Checked via Release Controller API
- **Test status:** Tests triggered after promotion, must wait for completion

### Promotion Detection

**API Endpoint:**
```
https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/release/{release}
```

**Success Criteria:**
```json
{
  "phase": "Accepted"
}
```

**MCP Execution:**
Not a direct OAR command - AI must fetch URL and parse JSON response.

**When to Check:**
- User invokes `/release:drive {release}` command
- AI checks current promotion status
- If not yet promoted (`phase != "Accepted"`), AI reports status to user
- User should re-invoke `/release:drive` periodically until promotion completes
- Typical promotion time: 6-24 hours

## Test Result Evaluation

### Candidate Build Analysis

**When to run:** Can start immediately when release flow begins (tests already completed)

**Execution Flow:**
```
1. Retrieve candidate build from oar_get_release_metadata(release).candidate_builds.x86_64
2. Fetch test result file from GitHub: _releases/ocp-test-result-{candidate_build}-amd64.json
3. Check attributes:
   IF aggregated == false:
       Report to user: "Candidate build tests still aggregating, check again later"
       (Should rarely happen - tests complete before flow starts)

   IF aggregated == true AND accepted == true:
       Mark analyze-candidate-build as "Pass" (all tests passed)
       No further action needed

   IF aggregated == true AND accepted == false:
       Trigger /ci:analyze-build-test-results {candidate_build}
       Parse AI recommendation:
         - ACCEPT: Mark task "Pass" (failures are waivable)
         - REJECT: Mark task "Fail" (blocking issues found)
```

**Slash Command:**
```bash
/ci:analyze-build-test-results {candidate_build}
```

The slash command provides:
- BO3 (Best of 3) verification status for blocking jobs
- Acceptance recommendation (ACCEPT/REJECT)
- Root cause analysis for failures
- Waiver guidance

### Promoted Build Analysis

**When to run:** After build promotion detected (`phase == "Accepted"`)

**Execution Flow:**
```
1. [CHECKPOINT 1] Check for test result file existence
   File: _releases/ocp-test-result-{release}-amd64.json

   When user invokes /release:drive:
     IF file does not exist:
         Report to user: "Test result file not yet created, check again in 5-10 minutes"
         Typical wait time: 10-120 minutes after promotion
     ELSE:
         Proceed to Checkpoint 2

2. [CHECKPOINT 2] Check for test aggregation
   Read file and check: aggregated == true

   When user invokes /release:drive:
     IF aggregated == false:
         Report to user: "Tests still running/aggregating, check again in 5-10 minutes"
         Typical wait time: 10-30 minutes after file creation
     ELSE:
         Proceed to Checkpoint 3

3. [CHECKPOINT 3] Check acceptance status
   IF accepted == true:
       Mark analyze-promoted-build as "Pass" (all tests passed)
       Proceed to gate check

   IF accepted == false:
       Trigger /ci:analyze-build-test-results {release}
       Parse AI recommendation:
         - ACCEPT: Mark task "Pass" (failures are waivable)
         - REJECT: Mark task "Fail" (blocking issues found)
```

**Slash Command:**
```bash
/ci:analyze-build-test-results {release}
```

### Gate Check Logic

**ENHANCED LOGIC (Early Async Task Triggering):**

The gate check has been optimized to trigger async tasks as soon as the stable build is promoted, without waiting for blocking tests analysis to complete.

**Condition to Trigger Async Tasks:**
```
Build promotion detected (phase == "Accepted")
```

**Rationale:** Once the stable build is accepted by ART and promoted to the release stream, we can immediately start parallel async tasks (image-consistency-check, stage-testing) to save time. The blocking tests analysis happens independently and doesn't need to gate these operations.

**Condition to PROCEED to Final Approval:**
```
promoted_build_analysis == "Pass"
(either accepted == true OR AI recommendation == ACCEPT)
AND
all 3 async tasks complete successfully
```

**Note:** Candidate build analysis runs independently and doesn't block the gate check. It's informational for context.

**If promoted build test analysis FAILS:**
1. Update overall status to "Red"
2. Mark analyze-promoted-build task as "Fail"
3. Notify owner via Slack with failure details from test analysis
4. STOP pipeline - manual intervention required
5. **Async tasks may still be running** - they will complete but won't proceed to final approval

**If promoted build test analysis PASSES:**
1. Mark analyze-promoted-build task as "Pass"
2. **Async tasks already triggered** - wait for completion
3. Continue to final approval when all tasks complete

## Task Definitions

### 1. create-test-report

**Purpose:** Initialize Google Sheets test report and ConfigStore entry

**MCP Tool:** `oar_create_test_report(release)`

**Input:**
- `release`: Z-stream version (e.g., `4.20.1`)

**Success Detection:**
```
stdout contains: "task [Create test report] status is changed to [Pass]" OR exiting report url
```

**Failure Detection:**
```
stdout contains: "task [Create test report] status is changed to [Fail]"
```

**Expected Duration:** 5 mins

**Next Action:** Proceed to take-ownership

---

### 2. take-ownership

**Purpose:** Assign release ownership to QE team member

**MCP Tool:** `oar_take_ownership(release, email)`

**Input:**
- `release`: Z-stream version
- `email`: Owner email (e.g., `user@redhat.com`)

**AI Decision Logic:**
- If user provided email in `/release:drive` command: Use that email
- Otherwise: Query `oar_get_release_metadata(release)` for current owner
- If no owner: Prompt user for email

**Success Detection:**
```
stdout contains: "task [Take ownership] status is changed to [Pass]"
```

**Expected Duration:** 10 seconds

**Next Action:** Proceed to check-cve-tracker-bug

---

### 3. check-cve-tracker-bug

**Purpose:** Verify CVE tracker bug coverage for release

**MCP Tool:** `oar_check_cve_tracker_bug(release)`

**Input:**
- `release`: Z-stream version

**Behavior:**
- Check if there is any missed CVE tracker bugs
- Sends missed trackers to ART via Slack
- Updates test report with all missed trackers
- **ALWAYS PASSES** - does not block pipeline

**Success Detection:**
```
stdout contains: "task [Check CVE tracker bugs] status is changed to [Pass]"
```

**Expected Duration:** 1 minute

**Next Action:** Proceed to check-rhcos-security-alerts

---

### 4. check-rhcos-security-alerts

**Purpose:** Check for blocking security alerts on RHCOS advisory (Konflux flow only)

**When to run:** Konflux release flow only (releases with shipment_mr in metadata)

**Prerequisites:** check-cve-tracker-bug completed

**Implementation:** Uses curl with Kerberos authentication (no existing MCP tool)

**Execution Steps:**

**Step 1: Verify Kerberos ticket exists**
```bash
klist
```

If no ticket or ticket expired:
- Report to user: "No valid Kerberos ticket found. Please run: kinit $kid@$domain"
- STOP task execution

**Step 2: Get RHCOS advisory ID**
```python
metadata = oar_get_release_metadata(release)
rhcos_advisory_id = metadata.advisories.rhcos
```

**Step 3: Fetch security alerts from Errata Tool**
```bash
curl -s -u : --negotiate 'https://errata.devel.redhat.com/api/v1/erratum/{rhcos_advisory_id}/security_alerts'
```

**Step 4: Parse response and check for blocking alerts**
```python
response = json.loads(curl_output)

# Filter blocking alerts from the alerts array
blocking_alerts = [alert for alert in response.alerts.alerts if alert.blocking == true]

IF len(blocking_alerts) > 0:
    Report to user with alert details and ask to email secalert@redhat.com
    # Continue pipeline - this is not a hard blocker, but requires follow-up

ELSE:
    Report to user: "No blocking security alerts found on RHCOS advisory"
```

**Success Detection:**
```
Task always passes - this is an informational check
Blocking alerts require manual follow-up but don't stop the pipeline
```

**Expected Duration:** 10 seconds

**Errata Tool API Response Format:**
```json
{
  "alerts": {
    "alerts": [
      {
        "name": "erratum_missing_notes_link",
        "text": "...",
        "description": "...",
        "how_to_resolve": "...",
        "blocking": false
      }
    ],
    "blocking": false
  }
}
```

**Key Fields:**
- `.alerts.alerts[]` (array) - List of individual alerts
- `.alerts.alerts[].blocking` (boolean) - Per-alert blocking status (THIS is what we check)
- `.alerts.blocking` (boolean) - Top-level blocking status (informational only)

**Next Action:**
- Trigger push-to-cdn-staging (async)
- Start checking for build promotion (parallel)

---

### 5. push-to-cdn-staging (Async Task)

**Purpose:** Push release images to CDN staging environment

**MCP Tool:** `oar_push_to_cdn_staging(release)`

**Input:**
- `release`: Z-stream version

**Prerequisites:** check-cve-tracker-bug completed

**Execution Phases:**

**Phase 1 - Trigger:**
```
stdout contains: "task [Push to CDN staging] status is changed to [In Progress]"
```

**Phase 2 - Check Status:**
When user invokes `/release:drive`, re-execute `oar_push_to_cdn_staging(release)` to check current status

**Phase 3 - Complete:**
```
Success: stdout contains: "task [Push to CDN staging] status is changed to [Pass]"
Failure: stdout contains: "task [Push to CDN staging] status is changed to [Fail]"
```

**Expected Duration:** 30-60 minutes (user should check status every 5-10 minutes)

**Note:** This task runs in parallel with build promotion waiting. It doesn't depend on promotion status.

**Failure Handling:** If fails, mark overall status "Red", notify owner

---

### 6. analyze-candidate-build (Parallel Task)

**Purpose:** Evaluate test results from candidate nightly build

**MCP Tool:** Uses slash command `/ci:analyze-build-test-results`

**Prerequisites:** None - can run immediately when release flow starts

**Input:**
- `candidate_build`: Retrieved from `oar_get_release_metadata(release).candidate_builds.x86_64`

**Execution Steps:**

**Step 1: Fetch test result file**
```
File: _releases/ocp-test-result-{candidate_build}-amd64.json
Location: GitHub repository on 'record' branch
```

**Step 2: Check aggregation status**
```python
IF 'aggregated' not in file:
    Report to user: "Candidate build tests still running, aggregation not started. Check again in 5-10 minutes"
    RETURN

IF file.aggregated != true:
    Report to user: "Candidate build tests still aggregating, check again in 5-10 minutes"
    RETURN
```

**Step 3: Check acceptance status**
```python
IF file.accepted == true:
    oar_update_task_status(release, "analyze-candidate-build", "Pass")
    Continue to next task

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {candidate_build} --arch amd64
    Parse AI recommendation

    IF recommendation == ACCEPT:
        oar_update_task_status(release, "analyze-candidate-build", "Pass")
        Continue to next task

    ELSE IF recommendation == REJECT:
        Report blocking issues to user
        oar_update_task_status(release, "analyze-candidate-build", "Fail")
        STOP pipeline - manual intervention required
```

**Expected Duration:** 2-5 minutes (if analysis needed)

**Note:** This task runs independently and provides context. It doesn't block the main pipeline gate check.

---

### 7. analyze-promoted-build (Sequential Task)

**Purpose:** Evaluate test results from promoted stable build

**MCP Tool:** Uses slash command `/ci:analyze-build-test-results`

**Prerequisites:** Build promotion detected (`phase == "Accepted"`)

**Input:**
- `release`: The z-stream version (e.g., `4.20.1`)

**Execution Steps:**

**Step 1: Check for test result file**
```python
File: _releases/ocp-test-result-{release}-amd64.json

IF file exists: Proceed to Step 2
ELSE: Report "Test result file not yet created, check again in 5-10 minutes", RETURN
```

**Step 2: Check for aggregation**
```python
IF 'aggregated' not in file:
    Report "Tests still running, aggregation not started. Check again in 5-10 minutes", RETURN

IF file.aggregated != true:
    Report "Tests still aggregating, check again in 5-10 minutes", RETURN
```

**Step 3: Check acceptance status and gate check**
```python
IF file.accepted == true:
    oar_update_task_status(release, "analyze-promoted-build", "Pass")
    Proceed to trigger async tasks (gate check passed)

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {release}

    IF recommendation == ACCEPT:
        oar_update_task_status(release, "analyze-promoted-build", "Pass")
        Proceed to trigger async tasks

    ELSE IF recommendation == REJECT:
        oar_update_task_status(release, "analyze-promoted-build", "Fail")
        Notify owner via Slack
        BLOCK at gate check - manual intervention required
```

**Expected Duration:**
- File creation: 10-120 minutes after promotion
- Aggregation: 6 hours after file creation
- Analysis (if needed): 2-5 minutes

**Next Action:** If gate check passes, trigger async tasks (image-consistency-check, stage-testing)

---

### 8. image-consistency-check (Async Task)

**Purpose:** Verify payload images match shipment MR

**MCP Tool:** `oar_image_consistency_check(release, job_id=None)`

**Input:**
- `release`: Z-stream version
- `job_id`: Optional Prow job ID (for status check)

**Prerequisites:**
- Build promotion detected (phase == "Accepted")
- **CRITICAL (Konflux flow only):** Shipment MR stage-release pipeline must succeed first

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_image_consistency_check(release)

# Success - Prow job triggered:
stdout contains: "task [Image consistency check] status is changed to [In Progress]"
AND capture Prow job ID from stdout (pattern: "Triggered image consistency check Prow job: {job_id}")

# Blocked - Stage-release pipeline not succeeded:
IF stage-release pipeline error detected:
    Report to user with shipment MR URL and action steps
    RETURN (do not mark as failed - this is a prerequisite wait state)
```

**Phase 2 - Check Status:**
```python
Execute: oar_image_consistency_check(release, job_id={captured_job_id})
```

**Phase 3 - Complete:**
```
Success: stdout contains: "task [Image consistency check] status is changed to [Pass]"
Failure: stdout contains: "task [Image consistency check] status is changed to [Fail]"
```

**Expected Duration:** 90-120 minutes after trigger succeeds

**Failure Handling:**
- Stage-release pipeline not ready: Report to user, ask to work with ART, wait for user to re-invoke
- Prow job failure: Mark overall status "Red", notify owner

---

### 9. stage-testing (Async Task)

**Purpose:** Run stage testing jobs on Jenkins

**MCP Tool:** `oar_stage_testing(release, build_number=None)`

**Input:**
- `release`: Z-stream version
- `build_number`: Optional Jenkins build number (for status check)

**Prerequisites:**
- Build promotion detected (phase == "Accepted")
- **CRITICAL (Konflux flow only):** Shipment MR stage-release pipeline must succeed first

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_stage_testing(release)

# Success - Jenkins job triggered:
stdout contains: "task [Stage testing] status is changed to [In Progress]"
AND capture Jenkins build number from stdout

# Blocked - Stage-release pipeline not succeeded:
IF stage-release pipeline error detected:
    Report to user with shipment MR URL and action steps
    RETURN (do not mark as failed - this is a prerequisite wait state)
```

**Phase 2 - Check Status:**
```python
Execute: oar_stage_testing(release, build_number={captured_build_number})
```

**Phase 3 - Complete:**
```
Success: stdout contains: "task [Stage testing] status is changed to [Pass]"
Failure: stdout contains: "task [Stage testing] status is changed to [Fail]"
```

**Expected Duration:** 2-4 hours after trigger succeeds

**Failure Handling:**
- Stage-release pipeline not ready: Report to user, ask to work with ART, wait for user to re-invoke
- Jenkins job failure: Mark overall status "Red", notify owner

---

### 10. image-signed-check

**Purpose:** Verify release images are properly signed

**MCP Tool:** `oar_image_signed_check(release)`

**Input:**
- `release`: Z-stream version

**Prerequisites:** All 3 async tasks (push-to-cdn-staging, image-consistency-check, stage-testing) must complete successfully

**Success Detection:**
```
stdout contains: "task [Image signature check] status is changed to [Pass]"
```

**Expected Duration:** 2 minutes

**Next Action:** Proceed to change-advisory-status

---

### 11. change-advisory-status

**Purpose:** Change advisory status from QE to REL_PREP (final QE approval)

**MCP Tool:** `oar_change_advisory_status(release)`

**Input:**
- `release`: Z-stream version

**Prerequisites:** All previous tasks must be "Pass"

**Timing Guidance:**
This task should be run **1 day before the scheduled release date** for optimal results.

**How to determine release date:**
```python
metadata = oar_get_release_metadata(release)
release_date = metadata.release_date  # Format: "2025-Nov-04"

# Calculate optimal execution date: release_date - 1 day
# If today < optimal_date: Wait to execute
# If today >= optimal_date: Safe to execute
```

**Execution Flow:**

**Phase 1 - Trigger (Immediate Return):**
```
Execute: oar_change_advisory_status(release)
Action: Approves shipment MR + launches detached background process
Return: "SCHEDULED" - parent process terminates immediately
Google Sheets: Task status updated to "In Progress"
```

**IMPORTANT - Asynchronous Execution:**
- The parent process returns immediately after launching the background checker
- You CANNOT get "[Pass]" status from stdout during execution
- The background process runs independently with a 2-day timeout
- Status updates happen via Slack notifications and Google Sheets (not stdout)

**Phase 2 - Background Process (Runs Independently):**
- Checks every 30 minutes if metadata URL is accessible
- Waits for: ART to trigger prod-release pipeline
- Logs: `/tmp/oar_logs/metadata_checker_<release>.log`

**Phase 3 - Completion:**
- On Success: Advisories move QE → REL_PREP, Google Sheets updated to "Pass", Slack notifications sent
- On Timeout (2 days): Google Sheets updated to "Fail", Slack failure notifications sent

**If task times out:**
1. Verify ART has triggered prod-release pipeline on shipment MR
2. Re-execute `oar_change_advisory_status(release)` - checker restarts with fresh 2-day timeout

**Final Action:** When background process succeeds, overall status marked "Green" and Slack notifications sent

---

## Execution Rules for AI

### 1. State Retrieval

Before making ANY decisions, AI must retrieve release state:

```python
state = oar_get_release_status(release="{release}")
```

This returns task statuses, metadata, and any blocking issues from StateBox (or Google Sheets as fallback).

### 2. Decision Logic

**For Sequential Tasks:**
```
IF previous_task.status == "Pass":
    Execute next_task
ELSE IF previous_task.status == "In Progress":
    Report to user: "Task still in progress, check again later"
ELSE IF previous_task.status == "Fail":
    Report to user: "Pipeline blocked - manual intervention required"
    STOP pipeline
```

**For Test Result Analysis:**
```
result_file = fetch_from_github(f"_releases/ocp-test-result-{build}-amd64.json")

IF file does not exist:
    Report to user: "Test result file not yet created, check again later"
    RETURN

IF 'aggregated' not in result_file:
    Report to user: "Tests still running, aggregation not started. Check again in 5-10 minutes"
    RETURN

IF result_file.aggregated != true:
    Report to user: "Tests still aggregating, check again in 5-10 minutes"
    RETURN

IF result_file.accepted == true:
    Mark task "Pass"
ELSE:
    Trigger /ci:analyze-build-test-results {build}
    IF AI_recommendation == ACCEPT:
        Mark task "Pass" (with waiver)
    ELSE:
        Mark task "Fail"
        STOP pipeline
```

**For Async Tasks:**
```
WHEN trigger phase:
    Execute command
    Capture job ID from stdout (Prow job ID or Jenkins build number)
    Report to user: "Task triggered, check status in X minutes"

WHEN user re-invokes /release:drive:
    Execute command with job ID (Prow job ID or Jenkins build number)
    Parse stdout for status

    IF status == "In Progress":
        Report to user: "Task still running, check again in X minutes"
    ELSE IF status == "Pass":
        Mark task complete, proceed to next task
    ELSE IF status == "Fail":
        Mark overall status "Red", notify owner, STOP pipeline
```

**For Parallel Tasks After Build Promotion (ENHANCED):**
```
WHEN build promotion detected (phase == "Accepted"):
    Trigger 2 tasks immediately:
        - image-consistency-check
        - stage-testing

    IF either task fails due to stage-release pipeline not ready:
        Report blocking message with shipment MR and action steps
        RETURN (tasks not triggered yet, will retry on next invocation)

    # Both tasks triggered successfully
    Report to user: "Build promoted! 2 async tasks triggered. Check status in 10-15 minutes"

    THEN proceed to check test results in parallel

When user re-invokes /release:drive:
    # Retry triggering any tasks blocked by stage-release
    IF image-consistency-check or stage-testing not triggered yet:
        Retry trigger
        IF still blocked: Report same blocking message, RETURN

    # Check BOTH conditions for final approval

    1. Test analysis status - check file, aggregation, acceptance
    2. Async task status - check all 3 tasks

    IF gate check PASSED AND all 3 async tasks == "Pass":
        Proceed to image-signed-check
    ELSE:
        Report current status and wait
```

### 3. Error Handling

**Transient Errors (Retry):**
- Network timeouts, API rate limits, temporary service unavailability
- Max retries: 3, Backoff: Exponential (1min, 2min, 4min)

**Permanent Errors (STOP):**
- Authentication failures, invalid release version, missing prerequisites, task execution failures

**Error Response:**
```
1. Mark task as "Fail"
2. Update overall status to "Red"
3. Notify owner via Slack with error details
4. Report to user: "Pipeline stopped - manual intervention required"
```

### 4. Notification Strategy

**Success Notifications:**
- Task completion: Update Google Sheets (automatic)
- Pipeline completion: Slack message to owner + channel

**Failure Notifications:**
- Task failure: Slack message to owner with error details
- Gate check failure: Slack message with test result analysis

## Troubleshooting Guide

### Issue: Task Stuck in "In Progress"
- Check Jenkins job status directly
- Review MCP server logs
- Manually complete task via OAR CLI or re-trigger if safe

### Issue: Gate Check Fails
- Review test result analysis from `/ci:analyze-build-test-results`
- Check if failures are known issues
- If waivable: Manually override gate check
- If blocking: Work with dev team to fix, wait for new build

### Issue: Build Not Promoting
- Check Release Controller status
- Verify ART team has promoted build
- Contact ART team for promotion status
- If test failure can be waived, ask ART to promote manually

### Issue: Test Result File Not Created
- Check if JobController agent is running
- Verify Prow jobs were triggered
- Manually trigger JobController if needed

### Issue: Test Results Never Aggregate
- Check if all test jobs completed
- Review TestAggregator logs for errors
- Wait for in-progress jobs, or re-run aggregation manually

### Issue: Stage-Release Pipeline Not Succeeded (Konflux Flow Only)

**Symptom:** image-consistency-check or stage-testing fails to trigger

**Diagnosis:**
1. Get shipment MR URL from `oar_get_release_metadata(release).shipment_mr`
2. Navigate to MR Pipelines tab
3. Look for 'stage-release-triggers' stage status

**Common Causes:**
- Advisory creation failed in stage environment
- Shipment YAML validation errors
- GitLab runner infrastructure issues

**Resolution:**
- If stage-release failed: Review logs, work with ART team to fix
- If stage-release still running: Wait (typical: 10-30 minutes), re-invoke `/release:drive`
- For infrastructure issues: Escalate to GitLab/platform team

### Issue: MCP Server Unresponsive
- Restart: `cd mcp_server && python3 server.py`
- Check firewall/network settings
