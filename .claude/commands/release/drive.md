---
description: Drive OpenShift z-stream release orchestration through the complete Konflux release workflow
---

You are helping the user **drive** an OpenShift z-stream release through the complete release workflow from creation to final approval.

**Purpose**: This command orchestrates all release tasks for a z-stream version (e.g., 4.20.1), executing tasks sequentially and managing async operations, with the goal of reaching final QE approval (advisory status changes from QE to REL_PREP).

The user has provided a release version: {{args}}

## CRITICAL: Validate Release Version

**BEFORE doing anything else, you MUST validate that a release version was provided:**

```python
release_version = "{{args}}".strip()

if not release_version:
    # No release version provided - ASK THE USER
    print("Error: No release version provided.")
    print("Usage: /release:drive <release-version>")
    print("Example: /release:drive 4.20.1")
    print()
    print("Please specify which z-stream release you want to drive.")
    STOP - Do not proceed, wait for user input
```

**IMPORTANT**: Never default to a hardcoded release version like 4.20.1. Always require explicit user input.

## Complete Workflow Specification

**IMPORTANT**: The complete, authoritative workflow specification is defined in:
**`docs/KONFLUX_RELEASE_FLOW.md`**

You MUST read and follow that document for:
- Task execution order and dependencies
- Build promotion checkpoint logic
- Test result evaluation (candidate vs promoted builds)
- Gate check criteria
- Async task orchestration
- Error handling and retry strategies
- All MCP tool usage patterns

## Quick Reference

Before executing ANY tasks, you MUST:

### 1. Retrieve Release State from StateBox

**ALWAYS start by retrieving release state (contains ALL data you need):**

```python
# Get complete release context (StateBox primary, Google Sheets fallback)
state = oar_get_release_status(release="4.20.1")
state_data = json.loads(state)

# StateBox contains EVERYTHING for workflow resumption:
# - metadata: advisories, jira_ticket, builds, shipment_mr, release_date
# - tasks: status, results, timestamps
# - issues: blockers, resolutions

# Extract metadata from StateBox (NO separate call to oar_get_release_metadata needed!)
metadata = state_data.get("metadata", {})
advisory_ids = metadata.get("advisory_ids", {})
jira_ticket = metadata.get("jira_ticket", "")
release_date = metadata.get("release_date", "")
candidate_builds = metadata.get("candidate_builds", {})
shipment_mr = metadata.get("shipment_mr", "")
```

**Data Source Priority:**
1. **StateBox (Primary)**: Complete state with metadata, tasks with results, and blocking issues
2. **Google Sheets (Fallback)**: Task status only (if StateBox doesn't exist)

**IMPORTANT**: StateBox should already exist (initialized by release detector when release is announced). If `oar_get_release_status` returns `"source": "worksheet"`, StateBox doesn't exist and you're running in **limited mode**:

**Limited Mode (Google Sheets fallback):**
- ✅ Can still execute workflow using task status from Google Sheets
- ✅ Task status updates via `oar_update_task_status` work (updates Google Sheets)
- ❌ No access to task execution results (can't extract Jenkins build numbers)
- ❌ No issue tracking (can't use `oar_add_issue`, `oar_resolve_issue`)
- ❌ No metadata access from StateBox

**How to handle limited mode:**

```python
state = oar_get_release_status(release="4.20.1")
state_data = json.loads(state)

if state_data.get("source") == "worksheet":
    Log: "⚠️ Running in LIMITED MODE - StateBox not found, using Google Sheets"
    Log: "Some features unavailable:"
    Log: "  - Cannot resume async tasks (no build numbers in results)"
    Log: "  - Cannot track blocking issues"
    Log: "  - Task results not available for context"
    Log: "  - No metadata in StateBox"

    # Get metadata separately (ONLY in limited mode)
    metadata_result = oar_get_release_metadata(release="4.20.1")
    metadata = json.loads(metadata_result)

    # Continue workflow with limitations
    # - Skip async task resumption (treat as "Not Started")
    # - Skip blocker checks (no issue tracking)
    # - Execute tasks normally, status updates still work
```

**Key Point**: When StateBox exists (normal case), you have ALL data in one call. DO NOT call `oar_get_release_metadata` separately - it's redundant and slower!

### 2. Determine Current Phase

Based on StateBox task status, identify which phase the release is in:

**Phase 1: Initialization**
- Take ownership
- Check CVE tracker bugs
- Check RHCOS security alerts (Konflux only)
- Trigger push-to-cdn-staging (async)
- Start candidate build analysis (parallel)

**Phase 2: Waiting for Build Promotion** (if build not promoted)
- Check Release Controller API for promotion status
- Report to user and ask them to re-invoke `/release:drive` later

**Phase 3: Async Task Triggering and Test Evaluation** (ENHANCED - if promoted)
- **TRIGGER async tasks immediately** after promotion detected:
  - image-consistency-check
  - stage-testing
- In parallel with async tasks:
  - Wait for test result file creation
  - Wait for test aggregation
  - Analyze test results (if accepted == false)
  - Perform gate check

**Phase 4: Final Sync Point** (if gate passed and async tasks complete)
- Wait for all 3 async tasks to complete:
  - push-to-cdn-staging (from Phase 1)
  - image-consistency-check (from Phase 3)
  - stage-testing (from Phase 3)

**Phase 5: Final Approval** (if all async tasks passed)
- Run image-signed-check
- Run change-advisory-status
- Call mcp tool oar_is_release_shipped to verify if all the release resources are in correct state

### 3. Task Execution Pattern

For EACH task you execute:

```python
# Execute MCP tool
result = mcp_tool(release=release, ...)

# Parse stdout for status
if "status is changed to [Pass]" in result:
    Log success and proceed to next task
elif "status is changed to [Fail]" in result:
    Report failure, STOP pipeline
elif "status is changed to [In Progress]" in result:
    Report to user, ask to check back later
```

### 4. Build Test Analysis Tasks (Special Handling)

**Why These Tasks Are Different:**

Tasks `analyze-candidate-build` and `analyze-promoted-build` have **NO dedicated OAR commands**. They require AI-driven analysis because:
- Test results stored externally in GitHub (`_releases/ocp-test-result-*.json` on `record` branch)
- Complex decision logic needed (BO3 verification, failure categorization, waiver assessment)
- Only AI can evaluate whether `accepted: false` should be waived or rejected

**CRITICAL: Read Full Execution Steps**

For complete step-by-step logic, read **`docs/KONFLUX_RELEASE_FLOW.md`**:
- **Section 6: analyze-candidate-build** (lines 471-548)
- **Section 7: analyze-promoted-build** (lines 550-643)

**Decision Flow:**

```
1. Fetch test result JSON from GitHub record branch (see KONFLUX_RELEASE_FLOW.md)
2. Check "aggregated": true (tests completed)
3. Check "accepted" field:

   IF accepted == true:
       → All tests passed BO3 verification
       → oar_update_task_status(release, task_name, "Pass",
             result="All blocking tests passed BO3 verification")
       → Continue pipeline

   IF accepted == false:
       → Trigger: /ci:analyze-build-test-results {build}
       → Present AI analysis to user

       IF AI recommendation == "RECOMMEND ACCEPT":
           → Present: "AI Analysis: Failures appear waivable (flaky, infra, known issues)"
           → Present: "Details: {AI summary}"
           → Ask user: "Accept this build? (y/n)"

           IF user accepts:
               → oar_update_task_status(release, task_name, "Pass",
                     result="Waivable failures accepted: {AI summary}")
               → Continue pipeline

           IF user rejects:
               → oar_add_issue(release,
                     issue="Test failures rejected by release lead: {summary}",
                     blocker=True,
                     related_tasks=[task_name])
               → oar_update_task_status(release, task_name, "Fail",
                     result="Rejected by release lead: {AI summary}")
               → STOP pipeline

       IF AI recommendation == "RECOMMEND REJECT":
           → Present: "⚠️ AI Analysis: Critical blockers detected"
           → Present: "Details: {AI summary}"
           → Ask user: "Override AI recommendation and accept anyway? (y/n)"

           IF user overrides (accepts):
               → Ask user: "Please provide justification for override:"
               → User provides: {justification}
               → oar_update_task_status(release, task_name, "Pass",
                     result="OVERRIDE: {justification}\n\nAI Analysis: {AI summary}")
               → Continue pipeline

           IF user confirms rejection:
               → oar_add_issue(release,
                     issue="Release blocker: {AI summary}",
                     blocker=True,
                     related_tasks=[task_name])
               → oar_update_task_status(release, task_name, "Fail",
                     result="Release blocker confirmed: {AI summary}")
               → STOP pipeline
```

**Evaluation Criteria (from /ci:analyze-build-test-results):**

**CAN WAIVE if:**
✅ Flaky tests, ✅ Infrastructure issues, ✅ Test automation bugs, ✅ Known OCPBUGS, ✅ Platform-specific non-critical

**CANNOT WAIVE if:**
❌ Product bugs, ❌ Cross-platform failures, ❌ Critical features affected, ❌ New unknown failures

**Important:**
- AI recommendation is **advisory only** - release lead makes final decision
- Release lead may have additional context not visible to AI
- **Only create issues for actual blockers** (user confirms rejection)
- Store all analysis + decisions in `task.result` for audit trail

**StateBox Integration:**
- Task status + result: `oar_update_task_status(release, task_name, status, result)`
- Blocking issues: `oar_add_issue(blocker=True)` only when build rejected

**Async Task Monitoring:**
- Re-execute the same MCP tool to check status
- Example: `oar_image_consistency_check(release, build_number=123)` to check progress

## Key Decision Points

### Build Promotion Checkpoint

**IMPORTANT**: WebFetch tool doesn't work with OpenShift Release Dashboard API. Use Bash tool with `curl` command instead.

**Check promotion status:**
```bash
curl -s "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/release/{release}" | jq -r '.phase'
```

**Expected output:**
- `"Accepted"` → Build is promoted, proceed to Phase 3 (trigger async tasks)
- Other values (e.g., `"Pending"`, `"Rejected"`) → Build not yet promoted

**Decision logic:**
```
IF phase != "Accepted":
    Report: "Build not yet promoted (current phase: {phase}), check again in 30 minutes"
    Ask user to re-invoke /release:drive later
    RETURN

IF phase == "Accepted":
    Report: "Build promoted successfully (phase: Accepted)"
    Proceed to Phase 3: Trigger async tasks (image-consistency-check, stage-testing)
```

### Gate Check (Critical - ENHANCED)
```python
# ENHANCED: Async tasks already triggered after build promotion
# Gate check now happens in parallel with async task execution

# After promoted build test analysis completes
if promoted_build_analysis == "Pass":
    # Async tasks already running - proceed to wait for completion
    Wait for all 3 async tasks: push-to-cdn-staging, image-consistency-check, stage-testing
else:
    Report blocking failures
    Update overall status to "Red"
    Note: Async tasks may still be running but pipeline cannot proceed
    STOP pipeline
```

## User Communication

**When tasks are running:**
- Tell user which tasks completed successfully
- Tell user which tasks are in progress
- Tell user estimated time to check back

**When waiting for external events:**
- Clearly explain what we're waiting for (build promotion, test aggregation, etc.)
- Provide estimated wait time
- Ask user to re-invoke `/release:drive {release}` later

**When errors occur:**
- Report specific error details
- Indicate whether it's transient (retry) or permanent (manual intervention)
- Provide next steps for resolution

## Example Invocation

```
/release:drive 4.20.1
```

AI will:
1. Check current state via `oar_get_release_status`
2. Determine which phase we're in
3. Execute next pending tasks
4. Report progress and next steps to user

## Important Notes

- **Read the full spec**: All detailed logic is in `docs/KONFLUX_RELEASE_FLOW.md`
- **Don't assume**: Always check actual task status before executing
- **Be transparent**: Tell user exactly what you're doing and why
- **Handle failures gracefully**: Provide clear error messages and recovery steps
- **Respect async operations**: Don't block on long-running tasks, tell user to check back

## Error Recovery

If you encounter errors:
1. Check `docs/KONFLUX_RELEASE_FLOW.md` Troubleshooting Guide
2. Report error details to user
3. Suggest manual intervention steps if needed
4. Don't retry destructive operations without user confirmation

---

## StateBox Workflow Resumption

**IMPORTANT**: StateBox provides AI-driven workflow resumption across multiple sessions.

### State Retrieval

**Always retrieve StateBox state at the start:**

```python
# Get complete release state (metadata, tasks with results, issues)
state = oar_get_release_status(release="4.20.1")
```

**StateBox state structure:**
```json
{
  "release": "4.20.1",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T14:45:00Z",
  "metadata": {
    "jira_ticket": "ART-12345",
    "advisory_ids": {"rpm": 12345, "rhcos": 12346},
    "release_date": "2025-Nov-04",
    "candidate_builds": {"x86_64": "4.20.0-0.nightly-..."},
    "shipment_mr": "https://gitlab.com/..."
  },
  "tasks": [
    {
      "name": "take-ownership",
      "status": "Pass",
      "started_at": "2025-01-15T10:35:00Z",
      "completed_at": "2025-01-15T10:36:00Z",
      "result": "Ownership assigned to rioliu@redhat.com..."
    },
    {
      "name": "image-consistency-check",
      "status": "In Progress",
      "started_at": "2025-01-15T14:00:00Z",
      "completed_at": null,
      "result": "Jenkins job #123 triggered..."
    }
  ],
  "issues": [
    {
      "issue": "CVE-2024-12345 not covered in advisory",
      "blocker": true,
      "related_tasks": ["check-cve-tracker-bug"],
      "reported_at": "2025-01-15T12:00:00Z",
      "resolved": false,
      "resolution": null
    }
  ]
}
```

### Task Resumption Logic

**For EACH task in the workflow, apply this decision tree:**

```python
# Parse state to get task information
state_data = json.loads(state)

# Handle limited mode (Google Sheets fallback)
if state_data.get("source") == "worksheet":
    # Limited mode - only have task status, no results or issues
    tasks = state_data.get("tasks", {})
    task_status = tasks.get(task_name, "Not Started")

    if task_status == "Pass":
        Log: f"✓ {task_name} already completed"
        Continue to next task
    elif task_status == "In Progress":
        # No build numbers available - treat as interrupted
        Log: f"⚠ {task_name} was interrupted (limited mode), retrying..."
        Execute task_name
    elif task_status == "Fail":
        # No blocker tracking - ask user
        Log: f"✗ {task_name} previously failed"
        Ask user: "Retry failed task? (y/n)"
        if yes: Execute task_name
        else: STOP
    else:
        # Not started - execute normally
        Execute task_name

    RETURN

# Full mode (StateBox) - complete decision tree
tasks = {t["name"]: t for t in state_data["tasks"]}
task = tasks.get(task_name)

if not task or task["status"] == "Not Started":
    # Check for general blockers before starting
    issues = [i for i in state.get("issues", [])
              if i.get("blocker") and not i.get("resolved")
              and not i.get("related_tasks")]

    if issues:
        Log: "✗ Release blocked by general issues:"
        for issue in issues:
            Log: f"  - {issue['issue']}"
        Ask user to resolve blockers
        STOP pipeline

    # Execute task normally
    Execute task_name

elif task["status"] == "Pass":
    # Skip completed tasks
    Log: f"✓ {task_name} already completed at {task['completed_at']}"
    Continue to next task

elif task["status"] == "In Progress":
    # Check if async task (Jenkins jobs)
    if task_name in ["image-consistency-check", "stage-testing"]:
        # Extract build number from task result
        build_number = extract_from_result(task["result"], r"Build number: (\d+)")

        if not build_number:
            Log: f"⚠ {task_name} in progress but no build number found, retrying..."
            Execute task_name
        else:
            # Query Jenkins job status
            result = execute_mcp_tool(task_name, build_number=build_number)

            if "status is changed to [Pass]" in result:
                Log: f"✓ {task_name} completed successfully"
                Continue to next task
            elif "status is changed to [Fail]" in result:
                Log: f"✗ {task_name} failed"
                STOP pipeline
            else:
                Log: f"⏳ {task_name} still running (job #{build_number})"
                Ask user to check back later
                RETURN
    else:
        # Non-async task stuck in progress - retry
        Log: f"⚠ {task_name} was interrupted, retrying..."
        Execute task_name

elif task["status"] == "Fail":
    # Check if task has unresolved blocker
    task_issues = [i for i in state.get("issues", [])
                   if i.get("blocker") and not i.get("resolved")
                   and task_name in i.get("related_tasks", [])]

    if task_issues:
        Log: f"✗ {task_name} blocked by:"
        for issue in task_issues:
            Log: f"  - {issue['issue']}"
        Ask user to resolve blockers and re-run /release:drive
        STOP pipeline
    else:
        # Blocker resolved or no blocker - retry task
        Log: f"↻ Retrying {task_name} (previous failure)..."
        Execute task_name
```

### Async Task Monitoring

**For long-running Jenkins tasks:**

```python
# Initial trigger (when task doesn't exist or has no build number)
result = oar_image_consistency_check(release=release)

if "Build number:" in result:
    build_number = extract_build_number(result)
    Log: f"⏳ Jenkins job #{build_number} triggered"
    Log: "Check back in 20-30 minutes with: /release:drive {release}"
    RETURN

# Status check on resume (when task has build number in result)
result = oar_image_consistency_check(release=release, build_number=build_number)

if "status is changed to [Pass]" in result:
    Log: f"✓ Job #{build_number} completed successfully"
    Continue to next task
elif "status is changed to [Fail]" in result:
    # Add issue to StateBox
    oar_add_issue(
        release=release,
        issue=f"image-consistency-check job #{build_number} failed: {extract_failure_reason(result)}",
        blocker=True,
        related_tasks=["image-consistency-check"]
    )
    Log: "✗ Job failed, blocker added to StateBox"
    STOP pipeline
else:
    Log: f"⏳ Job #{build_number} still running..."
    RETURN
```

### Issue Tracking Integration

**Adding blocking issues:**

```python
# When you encounter a blocking problem during execution
oar_add_issue(
    release=release,
    issue="CVE-2024-12345 not covered in advisory",
    blocker=True,
    related_tasks=["check-cve-tracker-bug"]
)
```

**Resolving issues (typically done by user manually):**

```python
# User fixes the problem, then resolves via MCP tool
oar_resolve_issue(
    release=release,
    issue="CVE-2024-12345",  # Supports partial/fuzzy matching
    resolution="Added CVE to advisory #12345, ART confirmed coverage"
)

# Next /release:drive invocation will retry the task
```

**Checking for blockers before starting workflow:**

```python
state = oar_get_release_status(release=release)

# Check for unresolved blocking issues
blockers = [i for i in state.get("issues", [])
            if i.get("blocker") and not i.get("resolved")]

if blockers:
    Log: "⚠ Found unresolved blocking issues:"
    for issue in blockers:
        related = issue.get("related_tasks", [])
        if related:
            Log: f"  - {issue['issue']} (affects: {', '.join(related)})"
        else:
            Log: f"  - {issue['issue']} (GENERAL BLOCKER - affects entire release)"

    Ask user: "Some tasks are blocked. Continue anyway? (y/n)"
    if user says no:
        STOP
```

### Workflow Phase Detection

**Use StateBox task statuses to determine current phase:**

```python
state = oar_get_release_status(release=release)
tasks = {t["name"]: t["status"] for t in state["tasks"]}

# Determine phase based on task completion
if tasks.get("take-ownership") != "Pass":
    phase = "PHASE 1: Initialization"
    next_steps = ["take-ownership", "check-cve-tracker-bug", ...]

elif not is_build_promoted(release):
    phase = "PHASE 2: Waiting for Build Promotion"
    next_steps = ["Check Release Controller API in 30 min"]

elif tasks.get("analyze-promoted-build") != "Pass":
    phase = "PHASE 3: Test Evaluation & Async Task Triggering"
    next_steps = ["Trigger async tasks", "Analyze test results"]

elif not all_async_tasks_pass(tasks):
    phase = "PHASE 4: Waiting for Async Tasks"
    pending = [t for t in ["push-to-cdn-staging", "image-consistency-check", "stage-testing"]
               if tasks.get(t) != "Pass"]
    next_steps = [f"Wait for {', '.join(pending)}"]

else:
    phase = "PHASE 5: Final Approval"
    next_steps = ["image-signed-check", "change-advisory-status"]

Log: f"Current Phase: {phase}"
Log: f"Next Steps: {next_steps}"
```

### Multi-Session Resumption Example

**Session 1 (interrupted after triggering async tasks):**
```
User: /release:drive 4.20.1
AI: Loading StateBox state for 4.20.1...
AI: Current Phase: PHASE 1 - Initialization
AI: ✓ take-ownership completed
AI: ✓ check-cve-tracker-bug completed
AI: ⏳ push-to-cdn-staging triggered (job #456)
AI: Build not yet promoted, check back in 30 minutes
```

**Session 2 (hours later, build promoted):**
```
User: /release:drive 4.20.1
AI: Loading StateBox state for 4.20.1...
AI: Resuming from PHASE 2...
AI: ✓ Skipping 2 completed tasks (take-ownership, check-cve-tracker-bug)
AI: ⏳ push-to-cdn-staging still running (job #456)
AI: ✓ Build promoted! Phase: PHASE 3 - Test Evaluation
AI: ⏳ image-consistency-check triggered (job #789)
AI: ⏳ stage-testing triggered (job #790)
AI: Waiting for test results, check back in 1 hour
```

**Session 3 (after async tasks complete):**
```
User: /release:drive 4.20.1
AI: Loading StateBox state for 4.20.1...
AI: Resuming from PHASE 4...
AI: ✓ Skipping 4 completed tasks
AI: ✓ push-to-cdn-staging completed (job #456)
AI: ✓ image-consistency-check completed (job #789)
AI: ✓ stage-testing completed (job #790)
AI: Analyzing promoted build test results...
AI: ✓ All tests passed, proceeding to PHASE 5
AI: ✓ image-signed-check completed
AI: ✓ change-advisory-status completed
AI: 🎉 Release 4.20.1 approved!
```

### Error Recovery

**When task fails with error:**

```python
try:
    result = execute_mcp_tool(task_name, release=release)

    if "status is changed to [Fail]" in result:
        # Task failed - determine if blocker should be added
        if is_permanent_failure(result):
            # Add blocking issue
            oar_add_issue(
                release=release,
                issue=f"{task_name} failed: {extract_error(result)}",
                blocker=True,
                related_tasks=[task_name]
            )
            Log: f"✗ {task_name} failed, blocker added"
            Log: "Please investigate and resolve, then re-run /release:drive"
            STOP
        else:
            # Transient failure - will retry on next invocation
            Log: f"⚠ {task_name} failed (transient), will retry on next invocation"
            RETURN

except Exception as e:
    # Unexpected error - add general blocker
    Log: f"✗ Unexpected error in {task_name}: {e}"
    oar_add_issue(
        release=release,
        issue=f"Unexpected error in {task_name}: {str(e)}",
        blocker=True,
        related_tasks=[task_name]
    )
    STOP
```

### Key Principles

1. **Idempotency**: Re-running `/release:drive` multiple times is safe
   - Completed tasks (Pass) are skipped
   - In-progress async tasks are checked, not re-triggered
   - Failed tasks are retried only after blockers resolved

2. **StateBox vs Google Sheets**:
   - **StateBox**: Primary source of truth for AI
     - Complete state (tasks + results + issues)
     - AI-readable task results for context
     - Issue tracking for blockers
   - **Google Sheets**: Still updated for backwards compatibility
     - Task status only (Pass/Fail/In Progress)
     - Human-readable format for manual review

3. **State Priority**:
   - Always check StateBox first (should exist for all active releases)
   - Fall back to Google Sheets only if StateBox doesn't exist (abnormal)

4. **Session Independence**:
   - Never rely on previous conversation context
   - Always load StateBox state at session start
   - StateBox persists across days, weeks, or machine restarts

---

**Remember**: StateBox enables true workflow resumption. Always check state first, respect task statuses, and track blockers properly.