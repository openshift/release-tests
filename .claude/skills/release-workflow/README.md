# Release Workflow Skill

Expert knowledge of OpenShift z-stream release orchestration workflow (Konflux/Errata flow).

## Overview

This skill provides comprehensive understanding of the release pipeline for OpenShift z-stream releases (4.12-4.20), including task sequencing, checkpoints, build lifecycle, and MCP execution patterns.

## What This Skill Knows

- **Complete task graph** - All 11+ tasks and their dependencies
- **Build lifecycle** - Candidate vs promoted builds
- **Checkpoint logic** - Build promotion, test aggregation, gate checks
- **State management** - Google Sheets, test result files, MCP server
- **Async task orchestration** - Parallel execution patterns
- **Konflux prerequisites** - Stage-release pipeline dependencies
- **Timing guidance** - Optimal execution windows (e.g., change-advisory-status)
- **Wait states** - When to re-invoke commands

## Automatic Activation

This skill is automatically invoked when:

- Discussing release tasks or pipeline stages
- Asking "where are we in the release?"
- Understanding build promotion lifecycle
- Troubleshooting workflow blockages
- Determining next steps in release
- Analyzing test results in release context

## Benefits for the Team

### 1. Shared Knowledge Across Commands

**Before (without skill):**
```
Each slash command references KONFLUX_RELEASE_FLOW.md separately
Updates require changing multiple commands
Workflow knowledge siloed to specific commands
```

**After (with skill):**
```
All commands automatically access workflow knowledge
Single source of truth for workflow understanding
Consistent answers across all team interactions
```

### 2. Context-Aware Responses

**Example:**
```
User: "Why is the build test failing?"

Without skill:
"Check the test logs for errors."

With release-workflow skill:
"This appears to be the promoted build test (analyze-promoted-build task).
The build is at the gate check phase - this is a critical checkpoint.
Failure here blocks final approval. Let me analyze if this is waivable..."
```

### 3. Workflow Integration

Works seamlessly with other skills:

```
release-workflow + openshift-expert:
"Stage-testing is in the post-promotion async phase (release-workflow).
The failure is due to CatalogSource operator issues (openshift-expert).
This is likely a product bug requiring OCPBUGS ticket."
```

## Use Cases

### Use Case 1: Understanding Current State

**User asks:** "Where are we in the X.Y.Z release?" (example: "Where are we in the 4.20.1 release?")

**Skill provides:**
- Current task phase
- Completed tasks
- In-progress tasks
- Next actions required
- Expected timeline

### Use Case 2: Troubleshooting Blockages

**User asks:** "Why can't image-consistency-check start?"

**Skill explains:**
- Prerequisites: Build promotion + stage-release pipeline (Konflux)
- Current status check
- If blocked: Specific action to unblock
- Expected wait time

### Use Case 3: Test Analysis Context

**User asks:** "Is this test failure from candidate or promoted build?"

**Skill determines:**
- Build identifier format (nightly vs z-stream)
- Which analysis task applies
- Impact on pipeline (candidate = informational, promoted = gate check)
- Appropriate response strategy

### Use Case 4: Multi-Command Integration

**Commands leveraging this skill:**
- `/release:drive` - Main orchestration
- `/ci:analyze-build-test-results` - Understands build context
- `/ci:analyze-prow-failures` - Knows if analyzing candidate vs promoted tests
- Any ad-hoc release questions

## Key Workflow Concepts

### Task Graph
```
Sequential pipeline with parallel async tracks
11+ tasks from create-test-report to change-advisory-status
Critical checkpoints: build promotion, test aggregation, gate check
```

### Build Lifecycle
```
Candidate Build (nightly) → ART Selection → Promoted Build (z-stream)
Tests on candidate: Pre-completed, analysis immediate
Tests on promoted: Post-promotion, must wait for aggregation
```

### Async Tasks
```
3 parallel tasks after build promotion:
- push-to-cdn-staging (starts early)
- image-consistency-check (post-promotion)
- stage-testing (post-promotion)
Final sync point: All must complete before approval
```

### Gate Check
```
Promoted build test analysis must pass
All async tasks must complete successfully
Blocks final approval if either fails
```

## Integration with Existing Tools

### With Slash Commands

**`/release:drive`:**
- Orchestrates full workflow
- Uses skill for decision logic
- Provides workflow context in responses

**`/ci:analyze-build-test-results`:**
- Understands if analyzing candidate or promoted build
- Knows impact on pipeline (informational vs gate check)
- Provides release-context recommendations

**`/ci:analyze-prow-failures`:**
- Knows which build is being tested
- Understands where in pipeline this occurs
- Contextualizes failure severity

### With Other Skills

**`openshift-expert` skill:**
- release-workflow: Provides process context
- openshift-expert: Provides technical expertise
- Together: Complete analysis with workflow impact

**Example:**
```
Question: "Why is authentication operator degraded in stage-testing?"

release-workflow: "Stage-testing is a critical async task that runs after
                   build promotion. Failure here blocks final approval."

openshift-expert: "Authentication operator degradation is likely due to
                   OAuth server deployment issues. Check oauth pods..."

Combined: "This is a blocking issue in the post-promotion phase. The
          authentication operator degradation needs immediate attention
          as stage-testing must pass for release approval."
```

## Source of Truth

**Primary Reference:** `docs/KONFLUX_RELEASE_FLOW.md`

The skill distills this 1500+ line specification into:
- Actionable decision logic
- Context-aware guidance
- Integration patterns
- Workflow awareness

## Updates

When `docs/KONFLUX_RELEASE_FLOW.md` is updated:

1. Review changes in workflow specification
2. Update SKILL.md if major concepts change
3. Restart Claude Code to reload skill
4. All commands benefit immediately

## Verification

Check if skill is loaded:

```
# In Claude Code
"What skills are available?"

# Should list: release-workflow
```

Test the skill:

```
"What tasks run after build promotion?"
"Explain the gate check logic"
"When should I run change-advisory-status?"
```

Expected: Detailed, workflow-aware responses with task context.

## Team Benefits Summary

✅ **Single source of truth** - One skill, all commands
✅ **Consistent workflow understanding** - Same answers across team
✅ **Context-aware analysis** - Knows release phase impact
✅ **No duplicate documentation** - Reference once, use everywhere
✅ **Easy updates** - Update skill, all commands benefit
✅ **Automatic invocation** - No manual skill calling
✅ **Integration ready** - Works with other skills seamlessly

---

**This skill makes release workflow knowledge universally accessible across all commands and team conversations.**