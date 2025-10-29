# Konflux Release Flow Specification

## Overview

This document defines the complete workflow for OpenShift z-stream release orchestration under the Konflux release platform. All releases from 4.12 to 4.20 follow this flow.

**Target Audience:** AI agents (Claude Code) and human release engineers

**Execution Method:** All `oar` commands are executed via the MCP (Model Context Protocol) server, NOT local CLI. The MCP server exposes OAR commands as structured tools with proper input validation and output parsing.

## Architecture Components

### Google Sheets (Source of Truth for M1)
- Primary source of task execution state for M1
- Each OAR command updates its corresponding task status directly
- Task status: "Not Started" / "In Progress" / "Pass" / "Fail"
- Overall status: "Green" / "Red"
- **Special cases (M1):**
  - B11 (Nightly build test / analyze-candidate-build): Stays "In Progress" until final approval
  - B12 (Signed build test / analyze-promoted-build): Stays "In Progress" until final approval
  - Test analysis results tracked via test result files in GitHub, not in Sheets
  - AI re-checks test result files each session to determine if analysis needed

### StateBox (Future - M2)
- Centralized component for storing ALL task execution state
- Will persist in GitHub `_releases/state_box/{release}.json`
- Will include analysis task results (analyze-candidate-build, analyze-promoted-build)
- StateBox will be used by AI agent internally
- Google Sheets will by updated as usual
- **Not implemented in M1**

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
    ├─→ push-to-cdn-staging (async - runs independently in parallel)
    └─→ [WAIT FOR BUILD PROMOTION - check API until phase == "Accepted"]
            ↓
        [WAIT FOR TEST RESULT FILE - check GitHub until file exists]
            ↓
        [WAIT FOR AGGREGATION - check until aggregated == true]
            ↓
        analyze-promoted-build (conditionally - only if accepted == false)
            ↓
        [GATE CHECK - promoted build must be acceptable]
            ↓
            ├─→ image-consistency-check (async)
            └─→ stage-testing (async)
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
  - `push-to-cdn-staging` starts immediately after check-cve-tracker-bug (runs while waiting for build promotion)
  - 2 async tasks (image-consistency-check, stage-testing) run simultaneously after gate check
- **Build Promotion Checkpoint:** Critical decision point before proceeding
- **Test Result Checkpoints:** Must wait for file existence and aggregation
- **Gate Check:** Promoted build must have acceptable test results
- **Final Sync Point:** image-signed-check waits for all 3 async tasks (push-to-cdn-staging, image-consistency-check, stage-testing)
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
- Format: `4.20.1` (z-stream version)
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

**Condition to PROCEED:**
```
promoted_build_analysis == "Pass"
(either accepted == true OR AI recommendation == ACCEPT)
```

**Note:** Candidate build analysis runs independently and doesn't block the gate check. It's informational for context.

**If gate check FAILS:**
1. Update overall status to "Red"
2. Mark analyze-promoted-build task as "Fail"
3. Notify owner via Slack with failure details from test analysis
4. STOP pipeline - manual intervention required

**If gate check PASSES:**
1. Mark analyze-promoted-build task as "Pass"
2. Trigger 3 async tasks in parallel
3. Continue pipeline

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

**Next Action:**
- Trigger push-to-cdn-staging (async)
- Start checking for build promotion (parallel)

---

### 4. push-to-cdn-staging (Async Task)

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

### 5. analyze-candidate-build (Parallel Task)

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
    # Aggregation not yet started
    Report to user: "Candidate build tests still running, aggregation not started. Check again in 5-10 minutes"
    RETURN

IF file.aggregated != true:
    # Should rarely happen - tests complete before flow starts
    Report to user: "Candidate build tests still aggregating, check again in 5-10 minutes"
    RETURN
```

**Step 3: Check acceptance status and determine if pipeline can proceed**
```python
IF file.accepted == true:
    Log: "Candidate build tests passed - all tests successful"
    Continue to next task
    # Note: B11 (Nightly build test) remains "In Progress" in Google Sheets

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {candidate_build} --arch amd64
    Parse AI recommendation from slash command output

    IF recommendation == ACCEPT:
        Log: "Candidate build failures are waivable - continuing"
        Continue to next task
        # Note: B11 remains "In Progress" in Google Sheets

    ELSE IF recommendation == REJECT:
        Report blocking issues to user
        Ask user to manually add critical bugs to Google Sheets if needed
        Update overall status to "Red" (manual or via notification)
        STOP pipeline - manual intervention required
```

**Success Criteria:**
```
accepted == true
OR
(accepted == false AND AI recommendation == ACCEPT)
```

**Google Sheets Behavior (M1):**
- B11 (Nightly build test) stays "In Progress" throughout the flow
- Only updated to "Pass" by `change-advisory-status` at the end
- If REJECT: Overall status → "Red", critical bugs added manually
- Analysis results tracked in Claude Code session, NOT in Google Sheets

**Expected Duration:** 2-5 minutes (if analysis needed)

**Note:** This task runs independently and provides context. It doesn't block the main pipeline gate check.

---

### 6. analyze-promoted-build (Sequential Task)

**Purpose:** Evaluate test results from promoted stable build

**MCP Tool:** Uses slash command `/ci:analyze-build-test-results`

**Prerequisites:** Build promotion detected (`phase == "Accepted"`)

**Input:**
- `release`: The z-stream version (e.g., `4.20.1`)

**Execution Steps:**

**Step 1: Check for test result file**
```python
File: _releases/ocp-test-result-{release}-amd64.json
Location: GitHub repository on 'record' branch

When /release:drive invoked:
    IF file exists:
        Proceed to Step 2
    ELSE:
        Report to user: "Test result file not yet created, check again in 5-10 minutes"
        Expected wait time: 10-120 minutes after promotion
        RETURN
```

**Step 2: Check for aggregation**
```python
When /release:drive invoked:
    Read file

    IF 'aggregated' not in file:
        Report to user: "Tests still running, aggregation not started. Check again in 5-10 minutes"
        Expected wait time: 10-30 minutes after file creation
        RETURN

    IF file.aggregated != true:
        Report to user: "Tests still aggregating, check again in 5-10 minutes"
        Expected wait time: 10-30 minutes after file creation
        RETURN

    # Now we know aggregated == true
    Proceed to Step 3
```

**Step 3: Check acceptance status and gate check**
```python
IF file.accepted == true:
    Log: "Promoted build tests passed - all tests successful"
    Proceed to trigger async tasks (gate check passed)
    # Note: B12 (Signed build test) remains "In Progress" in Google Sheets
    RETURN

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {release}
    Parse AI recommendation from slash command output

    IF recommendation == ACCEPT:
        Log: "Promoted build failures are waivable - proceeding to async tasks"
        Proceed to trigger async tasks (gate check passed)
        # Note: B12 remains "In Progress" in Google Sheets
        RETURN

    ELSE IF recommendation == REJECT:
        Report blocking issues to user with failure details
        Ask user to manually add critical bugs to Google Sheets Critical Issues table
        Update overall status to "Red"
        Notify owner via Slack with analysis results
        BLOCK at gate check
        STOP pipeline - manual intervention required
```

**Success Criteria (Gate Check):**
```
accepted == true
OR
(accepted == false AND AI recommendation == ACCEPT)
```

**Google Sheets Behavior (M1):**
- B12 (Signed build test) stays "In Progress" throughout the flow
- Only updated to "Pass" by `change-advisory-status` at the end
- If REJECT:
  - Overall status → "Red"
  - QE manually adds critical bugs to Critical Issues table
  - Pipeline stops
- Analysis results tracked in Claude Code session, NOT in Google Sheets

**Expected Duration:**
- File creation: 10-120 minutes after promotion (user re-invokes /release:drive to check)
- Aggregation: 6 hours after file creation (user re-invokes /release:drive to check)
- Analysis (if needed): 2-5 minutes

**Total: 20 minutes - 6 hours**

**Next Action:** If gate check passes, trigger async tasks (image-consistency-check, stage-testing)

---

### 7. image-consistency-check (Async Task)

**Purpose:** Verify image consistency across architectures

**MCP Tool:** `oar_image_consistency_check(release, build_number=None)`

**Input:**
- `release`: Z-stream version
- `build_number`: Optional Jenkins build number (for status check)

**Prerequisites:** Gate check passed

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_image_consistency_check(release)

stdout contains: "task [Image consistency check] status is changed to [In Progress]"
AND
Capture Jenkins build number from stdout pattern
```

**Phase 2 - Check Status:**
```python
When user invokes /release:drive:
    Execute: oar_image_consistency_check(release, build_number={captured_build_number})
    Check stdout for status update
```

**Phase 3 - Complete:**
```
Success: stdout contains: "task [Image consistency check] status is changed to [Pass]"
Failure: stdout contains: "task [Image consistency check] status is changed to [Fail]"
```

**Expected Duration:** 90-120 minutes (user should check status every 5-10 minutes)

**Failure Handling:** If fails, mark overall status "Red", notify owner

---

### 8. stage-testing (Async Task)

**Purpose:** Run stage testing jobs on Jenkins

**MCP Tool:** `oar_stage_testing(release, build_number=None)`

**Input:**
- `release`: Z-stream version
- `build_number`: Optional Jenkins build number (for status check)

**Prerequisites:** Gate check passed

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_stage_testing(release)

stdout contains: "task [Stage testing] status is changed to [In Progress]"
AND
Capture Jenkins build number from stdout pattern
```

**Phase 2 - Check Status:**
```python
When user invokes /release:drive:
    Execute: oar_stage_testing(release, build_number={captured_build_number})
    Check stdout for status update
```

**Phase 3 - Complete:**
```
Success: stdout contains: "task [Stage testing] status is changed to [Pass]"
Failure: stdout contains: "task [Stage testing] status is changed to [Fail]"
```

**Expected Duration:** 2-4 hours (user should check status every 10-15 minutes)

**Failure Handling:** If fails, mark overall status "Red", notify owner

---

### 9. image-signed-check

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

### 10. change-advisory-status

**Purpose:** Change advisory status to QE/PUSH_READY (final approval)

**MCP Tool:** `oar_change_advisory_status(release)`

**Input:**
- `release`: Z-stream version

**Prerequisites:** All previous tasks must be "Pass"

**Success Detection:**
```
stdout contains: "task [Change advisory status] status is changed to [Pass]"
```

**Expected Duration:** 5 mins

**Final Action:** Mark overall status as "Green", notify owner of successful release

---

## Execution Rules for AI

### 1. State Retrieval

Before making ANY decisions, AI must retrieve current release state using TWO MCP tools:

**Tool 1: `oar_get_release_metadata(release)`** - Get release configuration
```json
{
  "release": "4.20.1",
  "advisories": {
    "rpm": "12345",
    "image": "12346",
    ...
  },
  "jira_ticket": "ART-12345",
  "candidate_builds": {
    "x86_64": "4.20.0-0.nightly-2025-01-28-123456"
  },
  "shipment_mr": "https://gitlab.com/..."
}
```

**Tool 2: `oar_get_release_status(release)`** - Get task execution status from Google Sheets
```json
{
  "release": "4.20.1",
  "overall_status": "Green",
  "tasks": {
    "take-ownership": "Pass",
    "image-consistency-check": "Not Started",
    "analyze-candidate-build": "In Progress",
    "analyze-promoted-build": "In Progress",
    "check-greenwave-cvp-tests": "Pass",
    "check-cve-tracker-bug": "Pass",
    "push-to-cdn-staging": "In Progress",
    "stage-testing": "Not Started",
    "image-signed-check": "Not Started",
    "change-advisory-status": "Not Started"
  }
}
```

**Note on analyze tasks (M1 limitation):**
- `analyze-candidate-build` and `analyze-promoted-build` always show "In Progress" in Google Sheets
- AI must check test result files from GitHub to determine actual analysis status
- See "Test Result Evaluation" section for detailed logic

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
# Fetch test result file from GitHub
result_file = fetch_from_github(f"_releases/ocp-test-result-{build}-amd64.json")

# Check file exists
IF file does not exist:
    Report to user: "Test result file not yet created, check again later"
    RETURN

# Check aggregation - handle missing key
IF 'aggregated' not in result_file:
    Report to user: "Tests still running, aggregation not started. Check again in 5-10 minutes"
    RETURN

IF result_file.aggregated != true:
    Report to user: "Tests still aggregating, check again in 5-10 minutes"
    RETURN

# Check acceptance (now we know aggregated == true)
IF result_file.accepted == true:
    Mark task "Pass"
    No analysis needed
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
    Capture Jenkins build_number from stdout (if applicable)
    Report to user: "Task triggered, check status in X minutes"

WHEN user re-invokes /release:drive:
    Execute command with build_number parameter (if applicable)
    Parse stdout for status

    IF status == "In Progress":
        Report to user: "Task still running, check again in X minutes"
    ELSE IF status == "Pass":
        Mark task complete
        Proceed to next task
    ELSE IF status == "Fail":
        Mark overall status "Red"
        Notify owner
        STOP pipeline
```

**For Parallel Tasks After Gate Check:**
```
Trigger 2 tasks simultaneously:
    - image-consistency-check
    - stage-testing

Report to user: "2 async tasks triggered (image-consistency-check, stage-testing), check status in 10-15 minutes"

When user re-invokes /release:drive:
    Check status of all 3 async tasks:
        - push-to-cdn-staging (triggered earlier, may already be complete)
        - image-consistency-check
        - stage-testing

    IF all 3 tasks status == "Pass":
        Proceed to image-signed-check

    ELSE IF any task status == "Fail":
        STOP pipeline
        Notify owner

    ELSE:
        Report to user: "Tasks still running, check again in 10-15 minutes"
        List which tasks are still in progress
```

### 3. Error Handling

**Transient Errors (Retry):**
- Network timeouts
- API rate limits
- Temporary service unavailability

**Retry Strategy:**
- Max retries: 3
- Backoff: Exponential (1min, 2min, 4min)

**Permanent Errors (STOP):**
- Authentication failures
- Invalid release version
- Missing prerequisites
- Task execution failures

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

## Manual Workflow Example

### Scenario: Driving Release 4.20.1

**User Command:**
```
/release:drive 4.20.1
```

**AI Execution Sequence:**

**Step 1: Retrieve State**
```python
state = oar_get_release_metadata(release="4.20.1")
```

**Step 2: Determine Next Action**
```
IF state.tasks["create-test-report"] == "Not Started":
    Execute: oar_create_test_report(release="4.20.1")
```

**Step 3: Parse Output**
```
stdout: "task [Create test report] status is changed to [Pass]"
→ Task succeeded, proceed to next
```

**Step 4: Continue Sequential Tasks**
```python
Execute: oar_take_ownership(release="4.20.1", email="user@redhat.com")
Execute: oar_check_cve_tracker_bug(release="4.20.1")

# After check-cve-tracker-bug completes, trigger push-to-cdn-staging
Execute: oar_push_to_cdn_staging(release="4.20.1")
Report to user: "push-to-cdn-staging triggered, will run in parallel with build promotion check"
```

**Step 5: Start Candidate Build Analysis (Parallel)**
```python
# This runs independently while waiting for build promotion
candidate_build = state.candidate_builds.x86_64
result_file = fetch_github(f"_releases/ocp-test-result-{candidate_build}-amd64.json")

IF result_file.accepted == true:
    Mark analyze-candidate-build as "Pass"
ELSE:
    # Trigger analysis via slash command
    Execute: /ci:analyze-build-test-results {candidate_build} --arch amd64
    # Parse recommendation and mark task accordingly
```

**Step 6: Check Build Promotion**
```python
response = fetch("https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/release/4.20.1")
IF response.phase != "Accepted":
    Report to user: "Build not yet promoted (current phase: {response.phase}), check again in 30 minutes"
    RETURN
```

**User re-invokes `/release:drive 4.20.1` after 30 minutes...**

**Step 7: Check Promoted Build Test Results**
```python
# Checkpoint 1: File exists from branch record
IF not file_exists(f"_releases/ocp-test-result-4.20.1-amd64.json"):
    Report to user: "Test result file not yet created, check again in 10 minutes"
    RETURN

# Checkpoint 2: Aggregation complete
result_file = fetch_github(f"_releases/ocp-test-result-4.20.1-amd64.json")

IF 'aggregated' not in result_file:
    Report to user: "Tests still running, aggregation not started. Check again in 10 minutes"
    RETURN

IF result_file.aggregated != true:
    Report to user: "Tests still aggregating, check again in 10 minutes"
    RETURN

# Checkpoint 3: Check acceptance (now we know aggregated == true)
IF result_file.accepted == true:
    Mark analyze-promoted-build as "Pass"
    Proceed to gate check
ELSE:
    Execute: /ci:analyze-build-test-results 4.20.1
    IF recommendation == ACCEPT:
        Mark analyze-promoted-build as "Pass"
        Proceed to gate check
    ELSE:
        Mark analyze-promoted-build as "Fail"
        Report to user: "Promoted build has blocking test failures - manual intervention required"
        STOP pipeline
```

**Step 8: Trigger Remaining Async Tasks**
```python
# Gate check passed - trigger remaining 2 async tasks
# Note: push-to-cdn-staging was already triggered in Step 4
oar_image_consistency_check(release="4.20.1")
oar_stage_testing(release="4.20.1")

# Capture Jenkins build numbers
consistency_build = parse_build_number(stdout)
stage_build = parse_build_number(stdout)

Report to user: "2 async tasks triggered (image-consistency-check, stage-testing). Check status in 10-15 minutes."
RETURN
```

**User re-invokes `/release:drive 4.20.1` periodically...**

**Step 9: Check Async Task Status**
```python
# Check all 3 tasks
oar_push_to_cdn_staging(release="4.20.1")  # Check status
oar_image_consistency_check(release="4.20.1", build_number=consistency_build)
oar_stage_testing(release="4.20.1", build_number=stage_build)

IF any task == "Fail":
    Report to user: "Task failed - manual intervention required"
    STOP pipeline
ELSE IF any task == "In Progress":
    Report to user: "Tasks still running, check again in 10-15 minutes"
    RETURN
ELSE:
    # All tasks passed
    Proceed to final tasks
```

**Step 10: Final Tasks**
```python
# All async tasks passed
oar_image_signed_check(release="4.20.1")
oar_change_advisory_status(release="4.20.1")

# Release complete
Report to user: "Release 4.20.1 completed successfully!"
notify_slack(message="Release 4.20.1 completed successfully!")
```

## AI Orchestrator Decision Flow

```
START
  ↓
Retrieve current release state
  ↓
Identify next pending task
  ↓
Check prerequisites satisfied? ──NO──→ Report to user, RETURN
  ↓ YES
  ↓
Is this a test analysis task? ──YES──→ Check test result file exists?
  ↓ NO                                   ↓ NO → Report to user, RETURN
  ↓                                      ↓ YES
  ↓                                  aggregated == true?
  ↓                                      ↓ NO → Report to user, RETURN
  ↓                                      ↓ YES
  ↓                                  accepted == true? ──YES──→ Mark "Pass"
  ↓                                      ↓ NO
  ↓                                  Trigger /ci:analyze-build-test-results
  ↓                                      ↓
  ↓                                  Parse AI recommendation
  ↓                                      ↓
  ↓                              ACCEPT → Mark "Pass"
  ↓                              REJECT → Mark "Fail", STOP
  ↓                                      ↓
  ↓←─────────────────────────────────────┘
  ↓
Execute task via MCP
  ↓
Parse stdout for status
  ↓
Status == "Pass"? ──NO──→ Mark "Fail", STOP
  ↓ YES
Update state
  ↓
More tasks remaining? ──NO──→ Mark overall "Green", DONE
  ↓ YES
  ↓
Are there async tasks in progress? ──YES──→ Report to user, RETURN
  ↓ NO
Loop back to retrieve state
```

## Troubleshooting Guide

### Issue: Task Stuck in "In Progress"

**Diagnosis:**
- Check Jenkins job status directly
- Review MCP server logs
- Verify network connectivity

**Resolution:**
- Manually complete task via OAR CLI
- Re-trigger task if safe to retry
- Escalate to platform team if infrastructure issue

### Issue: Gate Check Fails

**Diagnosis:**
- Review test result analysis from `/ci:analyze-build-test-results`
- Check if failures are known issues
- Verify BO3 retry logic executed correctly

**Resolution:**
- If failures waivable: Manually override gate check
- If blocking issues: Work with dev team to fix, wait for new build
- Update test result tracking in GitHub

### Issue: Build Not Promoting

**Diagnosis:**
- Check Release Controller status
- Verify ART team has promoted build
- Check for infrastructure outages
- Do failure analysis for failed blocking job runs

**Resolution:**
- Contact ART team for promotion status
- Check ART team notifications in Slack
- Manual intervention if promotion failed, If test failure can be waived, ask ART to promote it manually

### Issue: Test Result File Not Created

**Diagnosis:**
- Check if JobController agent is running
- Verify Prow jobs were triggered
- Check GitHub repository access

**Resolution:**
- Manually trigger JobController if needed
- Check JobController logs for job trigger failures

### Issue: Test Results Never Aggregate

**Diagnosis:**
- Check if all test jobs completed
- Review TestAggregator logs for errors
- Verify BO3 retry logic completed

**Resolution:**
- Wait for in-progress jobs to finish
- Manually mark jobs as complete if stuck
- Re-run aggregation manually

### Issue: MCP Server Unresponsive

**Diagnosis:**
- Check MCP server process running
- Review server logs

**Resolution:**
- Restart MCP server: `cd mcp_server && python3 server.py`
- Check firewall/network settings

## References

- **OAR CLI Documentation:** `oar/README.md`
- **Agent Documentation:** `AGENTS.md`
- **MCP Server:** `mcp_server/server.py`
- **Slash Commands:** `.claude/commands/`
- **Test Result Analysis:** `.claude/commands/ci-analyze-build-test-results.md`
