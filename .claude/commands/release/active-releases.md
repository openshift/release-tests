---
description: Show all currently active z-stream releases and their status
---

You are helping the user view all currently active OpenShift z-stream releases and their progress.

## Overview

This command provides a team-wide view of active releases with status and progress from StateBox.

**Auto-discovery approach:**
- Discovers y-streams from `_releases/` directory structure (z-stream branch)
- Finds latest z-stream release per y-stream from tracking files (`4.X.z.yaml`)
- Filters by release date using ConfigStore (excludes releases older than 1 day past release_date)
- Fetches detailed status from StateBox for each release
- No hardcoded version lists

**Timing note:** Releases appear after ART announces them and build data is available in ConfigStore.

## Steps

### 1. Auto-Discover Active Releases

Call the MCP discovery tool:

```python
result = json.loads(discover_active_releases())
if "error" in result:
    raise Exception(f"Failed to discover active releases: {result['error']}")
releases = result["releases"]
```

Example result: `{"releases": ["4.14.63", "4.16.59", "4.17.52"]}`

### 2. Fetch Status for Each Release

For each release, call the MCP tools (in parallel for all releases):

```python
# For each release:
status_data = oar_get_release_status(release=version)
shipped_data = oar_is_release_shipped(release=version)
```

**From `oar_get_release_status()`:**
- `tasks` - List of task objects (name, status, started_at, completed_at)
- `issues` - List of all issues (blocker and non-blocker)
- `metadata` - Contains:
  - `release_date` - Release date string in format "2026-Mar-26" (use for countdown calculation)
  - Advisory IDs, shipment MR, Jira ticket, etc.

**From `oar_is_release_shipped()`:**
- `shipped` - Boolean indicating if release is live in production
- `flow_type` - "errata" or "konflux"
- `details` - Component-specific shipment status

### 3. Analyze and Format Output

For each release, extract:

**From `oar_get_release_status()`:**
- `tasks` - Task list for counting and phase determination
- `metadata.release_date` - Parse this to calculate `days_until_release`:
  ```python
  from datetime import datetime
  release_date = datetime.strptime(metadata["release_date"], "%Y-%b-%d").date()
  days_until_release = (release_date - datetime.now().date()).days
  ```
- `issues` - Use ONLY the issues array from StateBox
  - **CRITICAL:** If `issues` is empty array `[]`, there are NO issues - show `"-"`
  - **NEVER infer or create issues from task result text** - only use the explicit issues array
  - Filter for unresolved issues: `resolved=false`
  - Separate into blocking (`blocker=true`) and non-blocking (`blocker=false`)

**Determine status (check in this exact order):**
1. **SHIPPED** (🚀): `oar_is_release_shipped()` returns `shipped: true` (release is live in production)
2. **COMPLETE** (✅): `change-advisory-status` task = "Pass" (approved, waiting to ship)
3. **BLOCKED** (🔴): Has unresolved blocking issues OR any task status = "Fail"
4. **IN PROGRESS** (🟢 or 🟠): `take-ownership` task = "Pass"
   - Use 🟠 emoji if has unresolved non-blocking issues
   - Use 🟢 emoji if no issues
5. **NOT STARTED** (⚪): Otherwise

**CRITICAL RULES:**
- Use `issues` array from StateBox for issue descriptions - NEVER infer issues from task result text
- Also check task status: if any task has `status="Fail"`, add it to Issues field as `[TASK FAILED] {task_name}`
- Filter for unresolved issues: `resolved=false`
- If StateBox shows `issues: []` AND no failed tasks, show `"-"` in Issues field

**Determine phase:**
Show task name(s) with status from StateBox:
- If any task = "In Progress": Show ALL In Progress tasks comma-separated with status
  - Format: `"task1 (In Progress), task2 (In Progress)"`
  - Example: `"stage-testing (In Progress)"` or `"stage-testing (In Progress), image-consistency-check (In Progress)"`
- If no "In Progress" tasks: Show the most recently completed task with its status (latest by `completed_at` timestamp)
  - Format: `"task_name (status)"`
  - Example: `"change-advisory-status (Pass)"` or `"check-cve-tracker-bug (Fail)"`
- If no tasks started: `"Not started"`

**Task names** (exact as in StateBox):
- `take-ownership`
- `check-cve-tracker-bug`
- `analyze-candidate-build`
- `analyze-promoted-build`
- `image-consistency-check`
- `push-to-cdn-staging`
- `stage-testing`
- `image-signed-check`
- `change-advisory-status`

**Construct StateBox link:**
Extract y-stream from version (e.g., "4.21.7" → "4.21"), then:
```
https://github.com/openshift/release-tests/blob/z-stream/_releases/{y_stream}/statebox/{version}.yaml
```

**Get issues:**
- Start with unresolved issues from StateBox: filter `resolved=false`
- Add failed tasks: for any task with `status="Fail"`, add `[TASK FAILED] {task_name}`
- Separate into blocking and non-blocking:
  - Blocking: StateBox issues with `blocker=true` + all failed tasks
  - Non-blocking: StateBox issues with `blocker=false`
- Show blockers first, then non-blocking issues
- Format: Single line, comma-separated with type prefix
  - `[BLOCKER] {description}` for blocking issues from StateBox
  - `[TASK FAILED] {task_name}` for failed tasks
  - `[NON-BLOCKING] {description}` for non-blocking issues from StateBox
  - Truncate each description to 80 chars if needed
- If no issues and no failed tasks: show `"-"`

**Sort releases (multi-level):**
1. **Primary**: Status priority
   - BLOCKED (0)
   - Overdue - days_until_release < 0 (1)
   - IN PROGRESS (2)
   - NOT STARTED (3)
   - COMPLETE (4)
   - SHIPPED (5)

2. **Secondary**: Version number (descending - newer first)
   - Sort by full version: 4.21.7 > 4.21.6 > 4.20.17 > 4.20.16 > 4.19.10

## Output Format

Format the output exactly as shown below:

```
============================================================
Active Z-Stream Releases:

{emoji} {version}
   Status: {status}
   Release: {release_date_str} ({release_countdown})
   Tasks: {tasks_complete}/{task_count}
   Phase: {phase_task_name}
   StateBox: {statebox_link}
   Issues: {issues_list}

{...repeat for each release...}

============================================================
```

**Field details:**
- `{emoji}`: 🚀 SHIPPED, ✅ COMPLETE, 🔴 BLOCKED, 🟠 IN PROGRESS (with non-blocking issues), 🟢 IN PROGRESS (no issues), ⚪ NOT STARTED
- `{status}`: SHIPPED, COMPLETE, BLOCKED, IN PROGRESS, NOT STARTED
- `{release_countdown}`:
  - If days_until_release > 0: "in {days_until_release} days"
  - If days_until_release == 0: "TODAY"
  - If days_until_release < 0: "{abs(days_until_release)} days OVERDUE"
- `{phase_task_name}`: Task name(s) with status from StateBox
  - Examples: `"change-advisory-status (Pass)"`, `"stage-testing (In Progress)"`, `"check-cve-tracker-bug (Fail)"`, `"Not started"`
  - Multiple In Progress: `"stage-testing (In Progress), image-consistency-check (In Progress)"`
- `{statebox_link}`: GitHub link to StateBox YAML
- `{issues_list}`: Single line, comma-separated unresolved issues with type prefix
  - Format: `[BLOCKER] desc1, [BLOCKER] desc2, [NON-BLOCKING] desc3`
  - Or `"-"` if no unresolved issues
  - Blockers listed first, then non-blocking issues

**Example:**
```
============================================================
Active Z-Stream Releases:

🔴 4.21.7
   Status: BLOCKED
   Release: 2026-Mar-24 (1 days OVERDUE)
   Tasks: 8/9
   Phase: change-advisory-status (In Progress)
   StateBox: https://github.com/openshift/release-tests/blob/z-stream/_releases/4.21/statebox/4.21.7.yaml
   Issues: [BLOCKER] Metadata URL not accessible - background checker running

🔴 4.20.17
   Status: BLOCKED
   Release: 2026-Mar-25 (TODAY)
   Tasks: 5/9
   Phase: check-cve-tracker-bug (Fail)
   StateBox: https://github.com/openshift/release-tests/blob/z-stream/_releases/4.20/statebox/4.20.17.yaml
   Issues: [BLOCKER] CVE-2024-12345 not covered in advisory, [TASK FAILED] check-cve-tracker-bug

🟠 4.19.10
   Status: IN PROGRESS
   Release: 2026-Mar-25 (TODAY)
   Tasks: 7/9
   Phase: image-consistency-check (Pass)
   StateBox: https://github.com/openshift/release-tests/blob/z-stream/_releases/4.19/statebox/4.19.10.yaml
   Issues: [NON-BLOCKING] Jenkins job timeout - retry succeeded

🟢 4.18.36
   Status: IN PROGRESS
   Release: 2026-Mar-25 (TODAY)
   Tasks: 8/9
   Phase: change-advisory-status (In Progress)
   StateBox: https://github.com/openshift/release-tests/blob/z-stream/_releases/4.18/statebox/4.18.36.yaml
   Issues: -

✅ 4.14.63
   Status: COMPLETE
   Release: 2026-Mar-26 (in 1 days)
   Tasks: 9/9
   Phase: change-advisory-status (Pass)
   StateBox: https://github.com/openshift/release-tests/blob/z-stream/_releases/4.14/statebox/4.14.63.yaml
   Issues: -

============================================================
```

## Important Notes

- **Auto-discovery**: Automatically finds releases from tracking files (no hardcoded lists)
- **Date filtering**: Excludes releases with release_date older than 2 days
- **StateBox required**: Only shows releases with StateBox (ready for QE work)
- **Timing**: Releases appear 1-2 days after cut-off when ART creates StateBox
- **Single MCP call per release**: Only `oar_get_release_status()` - contains all needed data
- **Parallel execution**: Call MCP tools in parallel for all releases for performance
- **Sorting**: Priority order: blocked → overdue → in-progress → not started → complete
- **StateBox link**: Single source of truth for all release details (advisories, MR, Jira, builds, task history)

## Advanced Options (Future)

To filter by team (ERT vs Sustaining), add optional parameter:
- **ERT releases**: Typically 4.17+ (Full Support + Maintenance Support)
- **Sustaining releases**: Typically 4.12-4.16 (Extended Update Support)
- See: https://access.redhat.com/product-life-cycles?product=OpenShift%20Container%20Platform%204