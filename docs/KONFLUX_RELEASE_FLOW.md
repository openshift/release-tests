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
            └─→ [WAIT FOR TEST RESULT FILE - check GitHub until file exists]
                    ↓
                [WAIT FOR AGGREGATION - check until aggregated == true]
                    ↓
                analyze-promoted-build (conditionally - only if accepted == false)
                    ↓
                [GATE CHECK - promoted build must be acceptable]
                    ↓
                [WAIT FOR push-to-cdn-staging TO COMPLETE (status == "Pass")]
                    ↓
                stage-testing (async - triggered ONLY after push-to-cdn-staging passes)
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
  - `image-consistency-check` triggered immediately after build promotion is detected
  - `stage-testing` triggered ONLY after push-to-cdn-staging completes (status == "Pass")
- **Build Promotion Checkpoint:** Critical decision point - once detected, image-consistency-check triggers immediately
- **Test Result Checkpoints:** Must wait for file existence and aggregation (runs in parallel with async tasks)
- **Gate Check:** Promoted build must have acceptable test results before stage-testing can be triggered
- **CDN Push Dependency:** stage-testing MUST wait for push-to-cdn-staging to complete successfully
  - Rationale: Test environment pulls images from CDN staging, not intermediate locations
  - Testing before push completes would validate incorrect artifacts
- **Final Sync Point:** image-signed-check waits for:
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
    # Blocking security alert(s) found
    Report to user: """
    BLOCKING SECURITY ALERT(S) FOUND on RHCOS advisory {rhcos_advisory_id}

    Blocking alerts:
    {for each alert in blocking_alerts:
        - Name: {alert.name}
        - Text: {alert.text}
        - Description: {alert.description}
        - How to resolve: {alert.how_to_resolve}
    }

    ACTION REQUIRED:
    Please send an email to secalert@redhat.com to escalate this issue.
    Include the advisory ID ({rhcos_advisory_id}) and alert details in your email.

    Pipeline will continue but manual resolution is required before final approval.
    """

    # Log warning in Google Sheets (if possible)
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
  "id": 8885,
  "rhsa_id": 155455,
  "has_yet_to_be_fetched": false,
  "created_at": "2025-10-23T06:27:03Z",
  "updated_at": "2025-10-24T12:51:38Z",
  "alerts": {
    "erratum_id": "RHSA-2025:19002",
    "alerts": [
      {
        "name": "erratum_missing_notes_link",
        "text": "Erratum does not contain link to Release/Technical Notes in References",
        "description": "The References field of an erratum...",
        "how_to_resolve": "If an erratum refers to Technical or Release Notes...",
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
    # Update Google Sheets task status
    oar_update_task_status(release, "analyze-candidate-build", "Pass")
    Continue to next task

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {candidate_build} --arch amd64
    Parse AI recommendation from slash command output

    IF recommendation == ACCEPT:
        Log: "Candidate build failures are waivable - continuing"
        # Update Google Sheets task status
        oar_update_task_status(release, "analyze-candidate-build", "Pass")
        Continue to next task

    ELSE IF recommendation == REJECT:
        Report blocking issues to user
        Ask user to manually add critical bugs to Google Sheets if needed
        # Update Google Sheets task status to Fail
        oar_update_task_status(release, "analyze-candidate-build", "Fail")
        Update overall status to "Red" (automatically updated by oar_update_task_status)
        STOP pipeline - manual intervention required
```

**Success Criteria:**
```
accepted == true
OR
(accepted == false AND AI recommendation == ACCEPT)
```

**Google Sheets Behavior (M1 with oar_update_task_status):**
- B11 (Nightly build test) can now be updated by AI using `oar_update_task_status` MCP tool
- AI marks as "Pass" when tests pass or waivable failures detected
- AI marks as "Fail" when blocking failures detected
- If REJECT: Overall status → "Red" (automatically updated), critical bugs added manually
- Analysis results tracked via `oar_update_task_status` updates to Google Sheets

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
    # Update Google Sheets task status
    oar_update_task_status(release, "analyze-promoted-build", "Pass")
    Proceed to trigger async tasks (gate check passed)
    RETURN

ELSE IF file.accepted == false:
    Trigger: /ci:analyze-build-test-results {release}
    Parse AI recommendation from slash command output

    IF recommendation == ACCEPT:
        Log: "Promoted build failures are waivable - proceeding to async tasks"
        # Update Google Sheets task status
        oar_update_task_status(release, "analyze-promoted-build", "Pass")
        Proceed to trigger async tasks (gate check passed)
        RETURN

    ELSE IF recommendation == REJECT:
        Report blocking issues to user with failure details
        Ask user to manually add critical bugs to Google Sheets Critical Issues table
        # Update Google Sheets task status to Fail
        oar_update_task_status(release, "analyze-promoted-build", "Fail")
        Update overall status to "Red" (automatically updated by oar_update_task_status)
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

**Google Sheets Behavior (M1 with oar_update_task_status):**
- B12 (Signed build test) can now be updated by AI using `oar_update_task_status` MCP tool
- AI marks as "Pass" when tests pass or waivable failures detected
- AI marks as "Fail" when blocking failures detected
- If REJECT:
  - Overall status → "Red" (automatically updated)
  - QE manually adds critical bugs to Critical Issues table
  - Pipeline stops
- Analysis results tracked via `oar_update_task_status` updates to Google Sheets

**Expected Duration:**
- File creation: 10-120 minutes after promotion (user re-invokes /release:drive to check)
- Aggregation: 6 hours after file creation (user re-invokes /release:drive to check)
- Analysis (if needed): 2-5 minutes

**Total: 20 minutes - 6 hours**

**Next Action:** If gate check passes, trigger async tasks (image-consistency-check, stage-testing)

---

### 8. image-consistency-check (Async Task)

**Purpose:** Verify image consistency across architectures

**MCP Tool:** `oar_image_consistency_check(release, build_number=None)`

**Input:**
- `release`: Z-stream version
- `build_number`: Optional Jenkins build number (for status check)

**Prerequisites:**
- Build promotion detected (phase == "Accepted")
- **CRITICAL (Konflux flow only):** Shipment MR stage-release pipeline must succeed first

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_image_consistency_check(release)

# Possible outcomes:

# Success - Jenkins job triggered:
stdout contains: "task [Image consistency check] status is changed to [In Progress]"
AND
Capture Jenkins build number from stdout pattern

# OR

# Blocked - Stage-release pipeline not succeeded (Konflux flow only):
# The underlying code checks ShipmentData.check_component_image_health()
# which raises ShipmentDataException: "Stage release pipeline is not completed yet"
stderr/stdout contains error message or exception

IF stage-release pipeline error detected:
    Report to user: """
    BLOCKED: Shipment MR stage-release pipeline has not succeeded yet.

    Shipment MR: {metadata.shipment_mr}

    ACTION REQUIRED:
    1. Check shipment MR pipeline status (look for 'stage-release-triggers' stage)
    2. If stage-release failed, work with ART team to fix the issue
    3. Wait for stage-release pipeline to complete successfully
    4. Re-invoke /release:drive to retry triggering this task

    Pipeline will wait. This task cannot proceed until stage-release succeeds.
    """
    RETURN (do not mark as failed - this is a prerequisite wait state)
```

**Phase 2 - Check Status (when build_number available):**
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

**Expected Duration:**
- Stage-release pipeline wait: Variable (requires ART team intervention if failed)
- Jenkins job execution: 90-120 minutes after trigger succeeds
- User should check status every 10-15 minutes

**Failure Handling:**
- Stage-release pipeline not ready: Report to user, ask to work with ART, wait for user to re-invoke
- Jenkins job failure: Mark overall status "Red", notify owner

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
- **CRITICAL:** push-to-cdn-staging task must be in "Pass" status
  - Rationale: stage-testing validates the release artifacts pushed to CDN staging
  - The test environment pulls images from CDN staging, not from intermediate locations
  - Testing before push completes would validate incorrect/incomplete artifacts
  - AI MUST check push-to-cdn-staging status before triggering stage-testing

**Execution Phases:**

**Phase 1 - Trigger:**
```python
Execute: oar_stage_testing(release)

# Possible outcomes:

# Success - Jenkins job triggered:
stdout contains: "task [Stage testing] status is changed to [In Progress]"
AND
Capture Jenkins build number from stdout pattern

# OR

# Blocked - Stage-release pipeline not succeeded (Konflux flow only):
# The MCP tool will check stage-release status directly when invoked
stderr/stdout contains error message indicating stage-release not complete
Example: "MR stage-release pipeline has not succeeded yet"

IF stage-release pipeline error detected:
    Report to user: """
    BLOCKED: Shipment MR stage-release pipeline has not succeeded yet.

    Shipment MR: {metadata.shipment_mr}

    ACTION REQUIRED:
    1. Check shipment MR pipeline status (look for 'stage-release-triggers' stage)
    2. If stage-release failed, work with ART team to fix the issue
    3. Wait for stage-release pipeline to complete successfully
    4. Re-invoke /release:drive to retry triggering this task

    Pipeline will wait. This task cannot proceed until stage-release succeeds.
    """
    RETURN (do not mark as failed - this is a prerequisite wait state)
```

**Phase 2 - Check Status (when build_number available):**
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

**Expected Duration:**
- Stage-release pipeline wait: Variable (requires ART team intervention if failed)
- Jenkins job execution: 2-4 hours after trigger succeeds
- User should check status every 10-15 minutes

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

**Why timing matters:**
- The command approves the shipment MR
- It launches a background metadata URL checker process (2-day timeout)
- The checker waits for ART's prod-release pipeline to make the metadata URL accessible
- Once accessible, advisories automatically move from QE → REL_PREP
- Running too early (>2 days before release) causes timeout before ART triggers prod-release

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
The metadata URL checker process runs detached for up to 2 days:
- Checks every 30 minutes if metadata URL is accessible
- Monitored URL: `shipment.environments.prod.advisory.url` from shipment YAML
  - Path: `shipment/ocp/openshift-$y_release/openshift-$y_release/prod/$z_release.image.*.yaml`
  - Example: `$y_release = 4.20`, `$z_release = 4.20.1`
- Waits for: ART to trigger prod-release pipeline (makes URL accessible)
- Locks: `/tmp/oar_scheduler_<release>.lock` (Only available on the host that has OAR deployed)
- Logs: `/tmp/oar_logs/metadata_checker_<release>.log` (Only available on the host that has OAR deployed)

**Phase 3 - Completion Notifications:**

**On Success (Metadata URL becomes accessible):**
1. Advisories automatically moved from QE → REL_PREP
2. Google Sheets task status updated to "Pass"
3. Slack notifications sent to:
   - Original command thread 
   - Internal QE channel

**On Timeout/Failure (2 days elapsed without URL becoming accessible):**
1. Background process terminates
2. Google Sheets task status updated to "Fail"
3. Slack failure notifications sent to both channels

**If task times out:**
1. Verify ART has triggered prod-release pipeline on shipment MR
2. Check pipeline status in GitLab (look for 'prod-release-triggers' stage)
3. Once prod-release pipeline is triggered, re-execute the command:
   ```
   oar_change_advisory_status(release)
   ```
4. The checker will restart with a fresh 2-day timeout

**Monitoring Progress:**
- Check Slack notifications in original thread
- Check Google Sheets test report for task status updates
- Check background process logs: `/tmp/oar_logs/metadata_checker_<release>.log`
- Do NOT poll stdout - process returns immediately

**Expected Timeline:**
- Immediate: Shipment MR approval, background process launch
- Variable (minutes to 2 days): Waiting for ART's prod-release pipeline
- Automatic: Advisory status update + Slack notifications once URL accessible

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

**For Parallel Tasks After Build Promotion (ENHANCED):**
```
WHEN build promotion detected (phase == "Accepted"):
    Trigger 2 tasks immediately:
        - image-consistency-check
        - stage-testing

    # Handle stage-release pipeline dependency (Konflux flow only)
    IF either task fails due to stage-release pipeline not ready:
        Report to user: """
        Build promoted! Attempting to trigger async tasks...

        BLOCKED: Shipment MR stage-release pipeline has not succeeded yet.

        Shipment MR: {metadata.shipment_mr}

        ACTION REQUIRED:
        1. Check shipment MR pipeline status (look for 'stage-release-triggers' stage)
        2. If stage-release failed, work with ART team to fix the issue
        3. Wait for stage-release pipeline to complete successfully
        4. Re-invoke /release:drive to retry triggering async tasks

        Tests are still running/aggregating in parallel. Pipeline will wait for both:
        - Stage-release pipeline to succeed
        - Test result analysis to complete
        """
        RETURN (tasks not triggered yet, will retry on next invocation)

    # Both tasks triggered successfully
    Report to user: "Build promoted! 2 async tasks triggered (image-consistency-check, stage-testing). Tests are still running/aggregating in parallel, check status in 10-15 minutes"

    THEN proceed to check test results in parallel:
        - Wait for test result file
        - Wait for aggregation
        - Analyze if needed

When user re-invokes /release:drive:
    # First, retry triggering any tasks that failed due to stage-release not ready
    IF image-consistency-check or stage-testing not triggered yet:
        Retry trigger (stage-release may have completed since last attempt)
        IF still blocked:
            Report same blocking message, RETURN

    # Then check BOTH conditions for final approval

    1. Test analysis status:
        IF test result file not created yet:
            Report: "Tests still running, async tasks continue in background"
            RETURN

        IF aggregated != true:
            Report: "Tests still aggregating, async tasks continue in background"
            RETURN

        IF accepted == true OR AI recommendation == ACCEPT:
            Gate check PASSED
        ELSE:
            Gate check FAILED
            Update overall status to "Red"
            Report: "Promoted build has blocking failures - async tasks may still complete but pipeline stopped"
            STOP pipeline

    2. Async task status:
        Check all 3 tasks:
            - push-to-cdn-staging (triggered earlier, may already be complete)
            - image-consistency-check
            - stage-testing

        IF any task status == "Fail":
            STOP pipeline
            Notify owner

        IF any task status == "In Progress":
            Report to user: "Tasks still running, check again in 10-15 minutes"
            List which tasks are still in progress
            RETURN

    3. Final check:
        IF gate check PASSED AND all 3 async tasks == "Pass":
            Proceed to image-signed-check
        ELSE:
            Report current status and wait
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

**Step 6: Check Build Promotion and Trigger Async Tasks (ENHANCED)**
```python
response = fetch("https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/release/4.20.1")
IF response.phase != "Accepted":
    Report to user: "Build not yet promoted (current phase: {response.phase}), check again in 30 minutes"
    RETURN

# Build promoted! Trigger async tasks immediately
Report to user: "Build promoted (phase: Accepted)! Triggering async tasks now..."

oar_image_consistency_check(release="4.20.1")
oar_stage_testing(release="4.20.1")

# Capture Jenkins build numbers
consistency_build = parse_build_number(stdout)
stage_build = parse_build_number(stdout)

Report to user: """
2 async tasks triggered:
- image-consistency-check (build #{consistency_build})
- stage-testing (build #{stage_build})

These tasks are now running in parallel with test result analysis.
Check status in 10-15 minutes.
"""
RETURN
```

**User re-invokes `/release:drive 4.20.1` after 10-15 minutes...**

**Step 7: Check Async Tasks and Test Results in Parallel (ENHANCED)**
```python
# First check async task status
oar_push_to_cdn_staging(release="4.20.1")  # Check status
oar_image_consistency_check(release="4.20.1", build_number=consistency_build)
oar_stage_testing(release="4.20.1", build_number=stage_build)

async_tasks_status = {
    "push-to-cdn-staging": parse_status(stdout),
    "image-consistency-check": parse_status(stdout),
    "stage-testing": parse_status(stdout)
}

# Then check test result analysis
# Checkpoint 1: File exists from branch record
IF not file_exists(f"_releases/ocp-test-result-4.20.1-amd64.json"):
    Report to user: f"Test result file not yet created. Async tasks status: {async_tasks_status}. Check again in 10 minutes"
    RETURN

# Checkpoint 2: Aggregation complete
result_file = fetch_github(f"_releases/ocp-test-result-4.20.1-amd64.json")

IF 'aggregated' not in result_file:
    Report to user: f"Tests still running, aggregation not started. Async tasks status: {async_tasks_status}. Check again in 10 minutes"
    RETURN

IF result_file.aggregated != true:
    Report to user: f"Tests still aggregating. Async tasks status: {async_tasks_status}. Check again in 10 minutes"
    RETURN

# Checkpoint 3: Check acceptance (now we know aggregated == true)
gate_check_passed = False

IF result_file.accepted == true:
    gate_check_passed = True
    Report: "Promoted build tests passed - all tests successful"
ELSE:
    Execute: /ci:analyze-build-test-results 4.20.1
    IF recommendation == ACCEPT:
        gate_check_passed = True
        Report: "Promoted build failures are waivable - gate check passed"
    ELSE:
        Report to user: f"""
        GATE CHECK FAILED: Promoted build has blocking test failures.
        Async tasks status: {async_tasks_status}
        Async tasks may still complete but pipeline cannot proceed to final approval.
        Manual intervention required.
        """
        STOP pipeline

# Checkpoint 4: Wait for all async tasks
IF any task in async_tasks_status == "Fail":
    Report to user: "One or more async tasks failed - manual intervention required"
    STOP pipeline

IF any task in async_tasks_status == "In Progress":
    Report to user: f"Gate check passed! Waiting for async tasks to complete. Status: {async_tasks_status}. Check again in 10-15 minutes"
    RETURN

# All conditions met!
Report to user: "Gate check passed and all async tasks completed successfully!"
Proceed to final tasks
```

**User may need to re-invoke `/release:drive 4.20.1` multiple times until all async tasks complete...**

**Step 8: Final Tasks**
```python
# All async tasks passed and gate check passed
oar_image_signed_check(release="4.20.1")
oar_change_advisory_status(release="4.20.1")

# Release complete
Report to user: "Release 4.20.1 completed successfully!"
notify_slack(message="Release 4.20.1 completed successfully!")
```

## AI Orchestrator Decision Flow (ENHANCED)

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
Is this build promotion checkpoint? ──YES──→ Check promotion status (phase == "Accepted")?
  ↓ NO                                        ↓ NO → Report to user, RETURN
  ↓                                           ↓ YES
  ↓                                       TRIGGER async tasks immediately:
  ↓                                         - image-consistency-check
  ↓                                         - stage-testing
  ↓                                           ↓
  ↓                                       Report to user, RETURN (parallel execution started)
  ↓                                           ↓
  ↓←──────────────────────────────────────────┘
  ↓
Is this a test analysis task? ──YES──→ Check test result file exists?
  ↓ NO                                   ↓ NO → Report async status, RETURN
  ↓                                      ↓ YES
  ↓                                  Check async task status in parallel
  ↓                                      ↓
  ↓                                  aggregated == true?
  ↓                                      ↓ NO → Report async status, RETURN
  ↓                                      ↓ YES
  ↓                                  accepted == true? ──YES──→ Mark "Pass"
  ↓                                      ↓ NO                      ↓
  ↓                                  Trigger /ci:analyze-build-test-results
  ↓                                      ↓                          ↓
  ↓                                  Parse AI recommendation       ↓
  ↓                                      ↓                          ↓
  ↓                              ACCEPT → Mark "Pass" ──────────────┘
  ↓                              REJECT → Mark "Fail", STOP
  ↓                                      ↓
  ↓←─────────────────────────────────────┘
  ↓
Are there async tasks in progress? ──YES──→ Report status to user, RETURN
  ↓ NO (all 3 async tasks passed)
  ↓
Is gate check passed? ──NO──→ STOP (blocking test failures)
  ↓ YES
  ↓
Execute next task via MCP
  ↓
Parse stdout for status
  ↓
Status == "Pass"? ──NO──→ Mark "Fail", STOP
  ↓ YES
Update state
  ↓
More tasks remaining? ──NO──→ Mark overall "Green", DONE
  ↓ YES
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

### Issue: Stage-Release Pipeline Not Succeeded (Konflux Flow Only)

**Symptom:**
- image-consistency-check or stage-testing fails to trigger
- Error message: "Stage release pipeline is not completed yet" or "MR stage-release pipeline has not succeeded yet"

**Diagnosis:**
1. Check shipment MR pipeline status:
   - Get shipment MR URL from `oar_get_release_metadata(release).shipment_mr`
   - Open MR in browser
   - Navigate to Pipelines tab
   - Look for 'stage-release-triggers' stage status

2. Check for failure reasons:
   - If stage failed: Review pipeline logs for error details
   - If stage pending: Check if pipeline is still running
   - If stage skipped: Check MR approval/merge status

**Common Causes:**
- Advisory creation failed in stage environment
- Shipment YAML validation errors
- GitLab runner infrastructure issues
- Permission issues accessing Errata Tool or other services

**Resolution:**

**If stage-release failed:**
1. Review pipeline failure logs
2. Identify root cause (advisory creation, YAML errors, etc.)
3. Work with ART team to fix the issue:
   - For advisory issues: Contact ART team via Slack
   - For YAML issues: Fix in shipment MR and push update
   - For infrastructure: Escalate to GitLab/platform team
4. Retry pipeline once issue is fixed
5. Once stage-release succeeds, re-invoke `/release:drive` to trigger async tasks

**If stage-release still running:**
- Wait for pipeline to complete (typical: 10-30 minutes)
- Monitor progress in GitLab UI
- Re-invoke `/release:drive` periodically to check status

**Manual Workaround (if stage-release cannot be fixed):**
- Not recommended - stage-release must succeed for proper release
- Contact ART team for alternative approaches

**Prevention:**
- Ensure shipment YAML files are validated before MR creation
- Verify all required advisories exist before triggering pipeline
- Monitor ART team notifications for known issues

## References

- **OAR CLI Documentation:** `oar/README.md`
- **Agent Documentation:** `AGENTS.md`
- **MCP Server:** `mcp_server/server.py`
- **Slash Commands:** `.claude/commands/`
- **Test Result Analysis:** `.claude/commands/ci-analyze-build-test-results.md`
