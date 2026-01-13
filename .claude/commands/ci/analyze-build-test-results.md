---
description: Evaluate QE blocking test failures for OpenShift builds to determine if failures are critical blockers or can be waived
---

You are helping the user **evaluate** QE blocking test results for an OpenShift nightly or stable build.

**Purpose**: This command analyzes builds to determine their test status:
- If `accepted: true` - Provides quick summary showing all tests passed
- If `accepted: false` - Analyzes test failures to determine if they are **critical blockers** or can be **waived** due to:
  - Infrastructure issues (cloud platform problems, network issues, etc.)
  - Flaky tests (timing issues, race conditions, non-deterministic failures)
  - Known test automation bugs (issues in openshift-tests-private code)
  - Environmental/transient issues (quota limits, service outages, etc.)

**Key Concept**: `accepted: false` does NOT automatically mean the build should be rejected. Your analysis helps QE engineers decide whether to:
- **Accept the build** if failures are non-critical (flaky, infra, known issues)
- **Reject the build** if failures indicate genuine product bugs or critical regressions

The user has provided a build version (e.g., "4.20.0-0.nightly-2025-10-22-141500") or GitHub test result file path: {{args}}

Follow these steps:

## 1. Parse Input and Fetch Test Results

**If user provides a build version:**
- Parse the build version and architecture (default: amd64 if not specified)
- Construct the test result file path: `_releases/ocp-test-result-{build}-{arch}.json` on the `record` branch
- Example: `_releases/ocp-test-result-4.20.0-0.nightly-2025-10-22-141500-amd64.json`

**If user provides a GitHub URL or file path:**
- Extract build version and architecture from the path
- Example: `https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-4.20.0-0.nightly-2025-10-22-141500-amd64.json`

**Fetch the test result JSON:**
```bash
# Find the remote pointing to openshift/release-tests (where record branch lives)
RECORD_REMOTE=$(git remote -v | grep 'openshift/release-tests' | head -1 | awk '{print $1}')

# Fetch the record branch
git fetch "$RECORD_REMOTE" record

# Show the test result file
git show "$RECORD_REMOTE/record:_releases/ocp-test-result-{build}-{arch}.json" | jq '.'
```

## 2. Understand Test Result Structure

The test result JSON has this structure:
```json
{
  "accepted": true,
  "aggregated": true,
  "result": [
    {
      "jobName": "periodic-ci-openshift-...",
      "firstJob": {
        "jobStartTime": "2025-10-22T20:23:12Z",
        "jobID": "...",
        "jobURL": "https://qe-private-deck-ci.apps.ci...",
        "jobState": "success|failure|pending",
        "jobCompletionTime": "2025-10-22T23:06:52Z",
        "testResultSummary": {
          "openshift-extended-test": {
            "total": 116,
            "failures": 0,
            "errors": 0,
            "skipped": 24,
            "failingScenarios": ["OCP-XXXXX:Test Name"]
          }
        }
      },
      "retriedJobs": [
        {
          "jobStartTime": "...",
          "jobID": "...",
          "jobURL": "...",
          "jobState": "success|failure",
          "jobCompletionTime": "...",
          "testResultSummary": {...}
        }
      ]
    }
  ],
  "build": {
    "name": "4.20.0-0.nightly-2025-10-22-141500",
    "phase": "Accepted",
    "pullSpec": "registry.ci.openshift.org/ocp/release:...",
    "downloadURL": "https://..."
  }
}
```

**Key Properties:**
- **`accepted`** (boolean): `true` means ALL blocking test jobs passed BO3 verification ✅, `false` means failures ❌
- **`aggregated`** (boolean): `true` means test results have been processed by the aggregator
- **`build.phase`**: Release controller verification status (always "Accepted" for QE-tested builds)
- **`result`**: Array of all blocking test job results

**BO3 (Best of 3) Retry Logic:**
- If `firstJob.jobState == "success"` → Job passed ✅
- If `firstJob.jobState == "failure"` → Job controller triggers 2 retried jobs in parallel
  - If ≥2 out of 3 total attempts succeed → Job passed ✅
  - Otherwise → Job failed ❌
- The `accepted` property is set to `true` only when ALL jobs pass this BO3 verification

## 3. Overall Test Status Analysis

Parse the JSON and present high-level status:

```markdown
# OpenShift Build Test Results Analysis

## Build Information
- **Build**: {build.name}
- **Architecture**: {arch}
- **QE Test Verification**: {✅ ACCEPTED | ❌ REJECTED | ⏳ IN PROGRESS}
  - `accepted`: {true|false}
  - `aggregated`: {true|false}
- **Test Result File**: [View on GitHub](https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-{build}-{arch}.json)

## Overall Metrics
- **Total Jobs**: {count of result array}
- **Passed Jobs**: {count where job passed BO3}
- **Failed Jobs**: {count where job failed BO3}
- **Pending Jobs**: {count where firstJob.jobState == "pending"}
- **Jobs Requiring Retries**: {count where retriedJobs is not empty}

## Platform Distribution
{Extract platform from job names: aws-ipi, gcp-ipi, azure-ipi-fips, etc.}
- **AWS**: {count} jobs ({passed}/{total})
- **GCP**: {count} jobs ({passed}/{total})
- **Azure**: {count} jobs ({passed}/{total})
- **Other**: {count} jobs ({passed}/{total})
```

**Status Logic:**
- If `accepted == true`: Build **PASSED ALL BO3 TESTS** - no analysis needed
- If `accepted == false` AND `aggregated == true`: Build has **FAILED BO3 TESTS** - requires evaluation
- If `aggregated == false`: Build is **⏳ IN PROGRESS** (tests still running or pending aggregation)

**IMPORTANT**: `accepted: false` means test failures occurred, but does NOT automatically mean build rejection. Your analysis determines whether failures can be **waived** or are **critical blockers**.

## 4. Decision Point: Accepted vs Rejected

**If `accepted == true`:**
- Present summary showing all jobs passed
- Briefly note any jobs that required retries (for monitoring flakiness trends)
- **Skip detailed failure analysis** - no action needed
- Output example:
  ```markdown
  ## ✅ Build Accepted - All Tests Passed

  All {total_jobs} blocking test jobs have passed BO3 verification.

  ### Jobs That Required Retries ({count})
  {List jobs where retriedJobs.length > 0}
  - {jobName} on {platform}: firstJob failed, passed on retry (2/3 success)
    - This indicates potential flakiness - consider monitoring

  **Recommendation**: Build is ready for release. Monitor retry patterns for trends.
  ```

**If `accepted == false`:**
- Proceed to detailed failure analysis (steps 5-9)
- Analyze each failed job
- Run /ci:analyze-failures for root cause
- Provide cross-platform comparison
- Detect flaky tests
- Generate comprehensive failure report

## 5. Failed Jobs Analysis (Only if `accepted == false`)

For each job in `result` array, determine if it passed BO3:

```python
def is_job_passed(job):
    if job.firstJob.jobState == "success":
        return True
    if job.firstJob.jobState == "pending":
        return None  # Still running
    # firstJob failed, check retries
    success_count = sum(1 for retry in job.retriedJobs if retry.jobState == "success")
    return success_count >= 2  # Need 2/2 retries to succeed
```

**For each FAILED job, present:**

```markdown
### ❌ Failed Job: {jobName}

**Platform**: {extract from job name: AWS/GCP/Azure/Other}
**BO3 Result**: {success_count}/3 attempts passed (need ≥2)

#### Attempt 1 (First Run)
- **Status**: ❌ FAILED
- **URL**: {firstJob.jobURL}
- **Duration**: {jobCompletionTime - jobStartTime}
- **Test Summary**:
  {for each suite in testResultSummary:}
  - {suite_name}: {total} tests, {failures} failures, {errors} errors, {skipped} skipped
  {if failingScenarios exists:}
  **Failing Tests**:
    - {scenario1}
    - {scenario2}

#### Attempt 2 (Retry 1)
- **Status**: {✅ PASSED | ❌ FAILED | ⏳ PENDING | N/A}
- **URL**: {retriedJobs[0].jobURL if exists}
{if failed, show test summary}

#### Attempt 3 (Retry 2)
- **Status**: {✅ PASSED | ❌ FAILED | ⏳ PENDING | N/A}
- **URL**: {retriedJobs[1].jobURL if exists}
{if failed, show test summary}

**Failure Pattern**: {Consistent | Flaky-But-Failed-BO3 | Platform-Specific}
```

## 6. Cross-Platform Test Comparison (Only if `accepted == false`)

Collect all unique failing test scenarios from `testResultSummary.*.failingScenarios` across all jobs and attempts.

For each unique failing test:
- Identify which jobs/platforms it failed on
- Identify which jobs/platforms it passed on (by absence from failingScenarios)
- Determine if it's platform-specific or cross-platform

**Present analysis:**

```markdown
## Cross-Platform Test Comparison

### Test: OCP-20800:UserInterface Key/Value Secret
**Failure Distribution**:
- ❌ GCP: Failed on firstJob, passed on retry 1 & 2 (flaky)
- ✅ AWS: Passed all attempts
- ✅ Azure: Passed all attempts

**Assessment**: Flaky test specific to GCP platform - likely timing/race condition
**Severity**: Medium (fixed on retry, but failed BO3 if no other issues)

### Test: OCP-XXXXX:Another Failing Test
**Failure Distribution**:
- ❌ AWS: Failed all 3 attempts
- ✅ GCP: Passed all attempts
- ✅ Azure: Passed all attempts

**Assessment**: Platform-specific issue on AWS infrastructure
**Severity**: High (consistent failure, blocked BO3)
```

**Categorization:**
- **Platform-Specific**: Fails only on one platform (AWS/GCP/Azure)
- **Cross-Platform**: Fails on 2+ different platforms
- **Flaky**: Fails in some attempts but passes in retries on same platform
- **Consistent**: Fails across all retry attempts

## 7. Detailed Failure Analysis with /ci:analyze-prow-failures (Only if `accepted == false`)

For EACH failed job attempt (where `jobState == "failure"`):

**Invoke /ci:analyze-prow-failures:**
```bash
/ci:analyze-prow-failures {jobURL}
```

**Note**: We call `/ci:analyze-prow-failures` directly (not `/ci:analyze-failures`) because all QE blocking test jobs are Prow-based. This provides better visibility into parallel analysis execution and removes unnecessary dispatcher layer.

This provides:
- Detailed error messages and stack traces from JUnit XML
- Failure pattern grouping
- Known issue searches in OCPBUGS (via Jira MCP)
- QE automation code analysis (openshift-tests-private repository)
- Root cause hypotheses
- Recommended remediation actions

**Integration approach:**
- Run /ci:analyze-prow-failures for ALL failed attempts (firstJob + failed retries)
- Compare failure patterns across retries to identify:
  - **Consistent failures**: Same error across all attempts → likely product bug
  - **Flaky failures**: Different errors across attempts → likely test infrastructure or automation issue
- Present output inline under each failed job section
- Synthesize common patterns across multiple failed jobs

**Example integration:**

```markdown
### Root Cause Analysis (Attempt 1 - Failed)

{Output from /ci:analyze-prow-failures for firstJob.jobURL}

---

### Root Cause Analysis (Attempt 2 - Failed)

{Output from /ci:analyze-prow-failures for retriedJobs[0].jobURL}

**Comparison**: {Same failure pattern | Different failure | Infrastructure issue}
```

## 8. Flaky Test Detection & Evaluation (Only if `accepted == false`)

Analyze retry patterns to identify flaky tests:

**Flaky Test Indicators:**
- Test fails on firstJob but passes on retry (1/3 or 2/3 success rate)
- Different test failures across retry attempts (non-deterministic)
- Platform-specific flakiness (fails only on certain platforms intermittently)

**Categorize flaky tests:**

```markdown
## Flaky Test Analysis

### High-Severity Flakes (Failed BO3 - Blocked Build)

#### Job: {jobName} on {platform}
**Test**: {test_name from failingScenarios}
**Success Rate**: {X}/3 (need ≥2 to pass BO3)

**Retry Attempts**:
- Attempt 1: ❌ {brief error summary}
- Attempt 2: {✅ Passed | ❌ {error summary}}
- Attempt 3: {✅ Passed | ❌ {error summary}}

**Flaky Pattern**: {Timing Issue | Resource Contention | Platform-Specific | Test Framework Bug}

**Root Cause** (from /ci:analyze-failures):
{Synthesized summary of root cause analysis}

**Confidence**: {High | Medium | Low}

**Recommendation**:
- {File automation bug in openshift-tests-private}
- {Increase timeout in test code}
- {Investigate platform infrastructure}
- {File product bug if genuine race condition}

---

### Medium-Severity Flakes (Passed BO3 but Unreliable)

#### Job: {jobName} on {platform}
**Test**: {test_name}
**Success Rate**: 2/3 (passed BO3 but showed flakiness)

**Retry Attempts**:
- Attempt 1: ❌ {brief error}
- Attempt 2: ✅ Passed
- Attempt 3: ✅ Passed

**Recommendation**: Monitor for trends across future builds. Consider filing flake tracking issue.
```

## 9. Generate Comprehensive Summary Report

**Executive Summary:**

```markdown
# OpenShift Build QE Test Analysis Report

## Build Information
- **Build**: {build.name}
- **Architecture**: {arch}
- **QE Verification Status**: {✅ ACCEPTED | ❌ REJECTED | ⏳ IN PROGRESS}
- **Analysis Timestamp**: {current_date_time}
- **Test Result File**: [GitHub Link](https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-{build}-{arch}.json)

## Executive Summary

{if accepted:}
✅ **BUILD ACCEPTED** - All {total_jobs} blocking test jobs passed BO3 verification.

{X} jobs required retries to pass, indicating potential flakiness that should be monitored.

**Recommendation**: Build is ready for release. Review retry patterns for potential test improvements.

{if not accepted:}
❌ **BUILD REJECTED** - {failed_count} out of {total_jobs} blocking test jobs failed BO3 verification.

**Critical Blockers**: {count}
**Flaky Tests Detected**: {count}
**Platform-Specific Issues**: {count}
**Cross-Platform Issues**: {count}

**Key Findings**:
- {finding1}
- {finding2}
- {finding3}

## Detailed Analysis

{if accepted:}
### All Jobs Passed ✅

{Brief summary table of all jobs, platform, and status}

### Jobs That Required Retries
{List for monitoring purposes}

{if not accepted:}
### Failed Jobs Analysis
{From step 5}

### Cross-Platform Test Comparison
{From step 6}

### Root Cause Analysis
{From step 7}

### Flaky Test Detection
{From step 8}

## Build Acceptance Evaluation (Only if `accepted == false`)

Based on the comprehensive failure analysis above, provide a **recommendation** on whether the build can be accepted despite `accepted: false`:

### Evaluation Criteria

**Can WAIVE failures if:**
- ✅ All failures are due to known flaky tests (documented in past builds)
- ✅ All failures are infrastructure-related (cloud platform issues, network, quotas)
- ✅ All failures are test automation bugs (confirmed issues in openshift-tests-private)
- ✅ Failures have existing OCPBUGS issues tracking the problem
- ✅ Failures are platform-specific and non-critical features

**CANNOT WAIVE if:**
- ❌ Failures indicate genuine product bugs or regressions
- ❌ Failures occur across multiple platforms consistently (cross-platform issues)
- ❌ Failures affect critical features (API, authentication, networking, storage)
- ❌ Failures are new and previously unseen
- ❌ No clear root cause identified

### Recommendation Format

```markdown
## 🎯 Build Acceptance Recommendation

### Overall Assessment: [✅ RECOMMEND ACCEPT | ❌ RECOMMEND REJECT | ⚠️ NEEDS FURTHER INVESTIGATION]

**Rationale**:
{Explain the reasoning based on failure analysis}

**Summary**:
- Total Failed Jobs: {X}
- Waivable Failures: {Y} (flaky: {a}, infra: {b}, test automation: {c})
- Critical Blockers: {Z}

**Decision**:
{if waivable failures >= critical blockers:}
✅ **RECOMMEND ACCEPTING** this build despite `accepted: false`.

The {X} failed job(s) can be waived because:
1. {Reason 1 with evidence}
2. {Reason 2 with evidence}
3. {Reason 3 with evidence}

**Confidence Level**: {High | Medium | Low}

{if critical blockers > 0:}
❌ **RECOMMEND REJECTING** this build.

The following {Z} critical blocker(s) prevent acceptance:
1. {Blocker 1 description + impact}
2. {Blocker 2 description + impact}

These failures indicate genuine product issues that must be resolved.

{if uncertain:}
⚠️ **NEEDS FURTHER INVESTIGATION**

Unable to make a clear recommendation due to:
- {Uncertainty 1}
- {Uncertainty 2}

Suggested next steps:
1. {Investigation step 1}
2. {Investigation step 2}
```

## Recommended Actions

{if accepted:}
**No critical actions needed.** Monitor the following for trends:
1. {Jobs that required retries}
2. {Any patterns from retry analysis}

{if not accepted:}
### Immediate Actions
1. {Action for critical failure 1 with JIRA/GitHub issue link}
2. {Action for critical failure 2}

### Short-Term (Flaky Tests)
1. {Fix automation bug in test case XXXXX}
2. {Investigate platform infrastructure issue on AWS}

### Long-Term (Test Improvements)
1. {Improve test reliability for scenario X}
2. {Add retry logic for known flaky operation Y}

## Appendix

### Build Resources
- **Pull Spec**: `{build.pullSpec}`
- **Download URL**: {build.downloadURL}

### Failed Job URLs
{for each failed job:}
- **{jobName}**:
  - Attempt 1: {firstJob.jobURL}
  - Attempt 2: {retriedJobs[0].jobURL if exists}
  - Attempt 3: {retriedJobs[1].jobURL if exists}

### Known OCPBUGS Issues Found
{List any related bugs found from /ci:analyze-failures}

### QE Automation Issues Detected
{List any test code issues found from openshift-tests-private analysis}
```

## Important Notes

**Dependencies:**
- **OAR package**: Must be installed (`pip3 install -e .` from repository root)
- **Git access**: Requires read access to `openshift/release-tests` repository
- **GCS credentials**: `GCS_CRED_FILE` environment variable must be set for /ci:analyze-failures integration
- **Jira MCP** (optional): For known issue searches in OCPBUGS

**Key Concepts:**
- **`accepted` property**: Authoritative source for QE test verification status
- **BO3 Logic**: Best-of-3 retry strategy - need ≥2/3 successes to pass
- **`aggregated` property**: Indicates test result aggregator has processed the results
- **Blocking Tests**: Test jobs defined in `_releases/ocp-{version}-test-jobs-{arch}.json`

**Architecture Support:**
- amd64, arm64, ppc64le, s390x, multi

**Limitations:**
- If `aggregated == false`, results may be incomplete (jobs still running or pending aggregation)
- Some jobs may lack `testResultSummary` if JUnit artifacts are missing
- Historical results for recycled nightly builds may be deleted by aggregator

**Performance Tips:**
- For accepted builds: Skip detailed analysis, just show summary
- For rejected builds with many failures: Group similar failures to reduce /ci:analyze-failures calls
- Use jq for efficient JSON parsing instead of loading entire file

## Output Guidelines

- **Concise for accepted builds**: Just summary + any retry monitoring notes
- **Comprehensive for rejected builds**: Full analysis with all details
- **Visual indicators**: ✅ (pass), ❌ (fail), ⏳ (pending), 🔄 (retry)
- **Direct links**: Always provide clickable links to Prow jobs, GitHub files, JIRA issues
- **Actionable insights**: Prioritize recommendations over raw data
- **Clear formatting**: Use markdown headers, code blocks, lists properly
- **Blank lines**: Add spacing between major sections for readability
- **Confidence levels**: Include when making assessments (High/Medium/Low)