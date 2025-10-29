---
description: Drive OpenShift z-stream release orchestration through the complete Konflux release workflow
---

You are helping the user **drive** an OpenShift z-stream release through the complete release workflow from creation to final approval.

**Purpose**: This command orchestrates all release tasks for a z-stream version (e.g., 4.20.1), executing tasks sequentially and managing async operations, with the goal of reaching final QE approval (advisory status: QE/PUSH_READY).

The user has provided a release version: {{args}}

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

### 1. Retrieve Release State

Use TWO MCP tools to get complete state:

```python
# Get release configuration (advisories, candidate builds, etc.)
metadata = oar_get_release_metadata(release="4.20.1")

# Get task execution status from Google Sheets
status = oar_get_release_status(release="4.20.1")
```

### 2. Determine Current Phase

Based on task status, identify which phase the release is in:

**Phase 1: Initialization** (if create-test-report not started)
- Create test report
- Take ownership
- Check CVE tracker bugs
- Trigger push-to-cdn-staging (async)
- Start candidate build analysis (parallel)

**Phase 2: Waiting for Build Promotion** (if build not promoted)
- Check Release Controller API for promotion status
- Report to user and ask them to re-invoke `/release:drive` later

**Phase 3: Promoted Build Test Evaluation** (if promoted but tests not analyzed)
- Wait for test result file creation
- Wait for test aggregation
- Analyze test results (if accepted == false)
- Perform gate check

**Phase 4: Async Task Execution** (if gate passed)
- Trigger image-consistency-check and stage-testing
- Monitor all 3 async tasks (including push-to-cdn-staging from Phase 1)

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

### 4. Special Cases (M1 Limitations)

**Candidate/Promoted Build Analysis:**
- These tasks (B11/B12 in Google Sheets) always show "In Progress"
- You MUST check test result files from GitHub to determine actual status:
  ```bash
  git show record:_releases/ocp-test-result-{build}-amd64.json
  ```
- If `accepted == true`: Continue pipeline
- If `accepted == false`: Trigger `/ci:analyze-build-test-results {build}`
  - If AI recommends ACCEPT: Continue pipeline
  - If AI recommends REJECT: Report blocking issues, STOP pipeline, ask user to manually add bugs to Critical Issues table

**Async Task Monitoring:**
- Re-execute the same MCP tool to check status
- Example: `oar_image_consistency_check(release, build_number=123)` to check progress

## Key Decision Points

### Build Promotion Checkpoint
```python
response = WebFetch(
    url=f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/release/{release}",
    prompt="Extract the 'phase' field from the JSON response"
)

if phase != "Accepted":
    Report: "Build not yet promoted (current: {phase}), check again in 30 min"
    RETURN
```

### Gate Check (Critical)
```python
# After promoted build test analysis
if promoted_build_analysis == "Pass":
    Trigger async tasks: image-consistency-check, stage-testing
else:
    Report blocking failures
    Update overall status to "Red"
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

**Remember**: This is M1 implementation. StateBox is not yet implemented, so state is tracked via:
- Google Sheets for most tasks
- Test result files in GitHub for analysis tasks
- Claude Code conversation context for in-session state