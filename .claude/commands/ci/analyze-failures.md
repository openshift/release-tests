---
description: Analyze OpenShift CI job failures using AI
---

You are helping the user analyze failures from an OpenShift CI Prow job run.

The user has provided a Prow deck URL (or you should ask for it): {{args}}

Follow these steps:

1. **Parse the URL**: Extract the job name and run ID from the Prow deck URL
   - URL format: `https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/{bucket}/logs/{job_name}/{job_run_id}`
   - Example: `https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.20-automated-release-aws-ipi-f999/1979765746749673472`
   - Extract: bucket (e.g., `qe-private-deck`), job_name, and job_run_id

2. **Fetch test failures**: Use the Python helper script to fetch JUnit XML files and extract failure details
   ```bash
   python3 tools/ci_job_failure_fetcher.py <prow_deck_url>
   ```
   This will output JSON with failure details including test names, error messages, and stack traces.

3. **AI Analysis**: Analyze the test failures and provide:
   - **Data Handling Note**: The fetcher automatically groups failures by pattern and may truncate data if there are many failures (>50 by default). Check the `truncation_info` and `failure_patterns` fields in the JSON output.
   - **Failure Pattern Analysis**: Use the `failure_patterns` field to identify common root causes. Each pattern shows occurrence count and affected tests.
   - **Failure Categories**: Categorize failures (infrastructure, timeout, assertion, flaky test, etc.)
   - **Priority Assessment**: Identify which failures are most critical based on pattern frequency
   - **Root Cause Hypotheses**: Suggest potential root causes for each failure pattern
   - **Recommended Actions**: Suggest next steps (bug reports, retries, infrastructure fixes, etc.)
   - **Truncation Awareness**: If `is_truncated` is true, acknowledge that only representative samples are shown and mention the total failure count

4. **Query Known Issues from OCPBUGS** (Optional - requires Jira MCP):
   - **Checkpoint**: First verify if Jira MCP is available by checking if `mcp__mcp-atlassian__jira_search` tool exists
   - **If Jira MCP is NOT available**: Skip this step gracefully and continue to step 5. Mention in the final report that known issue lookup was skipped (MCP not configured).
   - **If Jira MCP IS available**: For each major failure pattern (top 3-5 by occurrence count):
     - Extract 2-3 key terms from error message (e.g., "ImagePullBackOff", "timeout", "authentication failed")
     - Focus on specific component/feature names and unique error keywords
     - Avoid generic terms like "error", "failed", "test", "timeout"
     - Search OCPBUGS using JQL focused on **summary field only** (issue titles) for precise matching:
       ```
       project = OCPBUGS AND (summary ~ "keyword1" OR summary ~ "keyword2")
       AND status NOT IN (Closed, Verified)
       ORDER BY updated DESC
       ```
     - **Why summary only**: The `text` field includes descriptions, comments, logs, and stack traces, creating too many false positives. The `summary` field (issue title) is concise and more likely to match relevant issues.
     - Limit to 3-5 most recent/relevant bugs per pattern
     - **Important**: Don't rely on component names for matching - focus on error message keyword similarity only
     - For each matching bug, assess relevance by comparing error messages and failure symptoms
     - **Only include potentially relevant issues** - do not list issues that are clearly unrelated (adds noise)
     - Present findings as:
       - If relevant issues found: "Similarity query found X potentially related issues" with "⚠️ Please manually verify"
       - If no relevant issues: "Similarity query found N total issues, but none appear related to this specific failure"
     - Include for each relevant issue: bug key, status, summary, link to issue, and brief relevance assessment
     - Always provide direct Jira search links so users can verify and explore further

5. **Check for QE Automation Issues** (if openshift-tests-private detected):
   - **Detection**: Check if stack traces contain `github.com/openshift/openshift-tests-private`
   - **Extract Case ID**: Find sequences of digits between dashes in the test name
     - Example: "Author:$uid-LEVEL0-Medium-64296-disable CORS" → case ID is 64296
     - Look for pattern `-{digits}-` in test name (usually the longest digit sequence is the case ID)
   - **Determine Release Branch**: Extract release version from job name
     - Job name pattern: `periodic-ci-openshift-openshift-tests-private-release-{X.Y}-...`
     - Example: `periodic-ci-openshift-openshift-tests-private-release-4.17-automated-release-aws-ipi-f999` → use branch `release-4.17`
     - If no release version found, use `master` branch
   - **Setup Repository Access**:
     - Check if repo exists: `../openshift-tests-private` (parent directory of current repo)
     - If NOT exists: Clone the repository (user should have access via SSH/HTTPS credentials)
       ```bash
       cd .. && git clone git@github.com:openshift/openshift-tests-private.git
       ```
     - If exists: Update to ensure fresh code
       ```bash
       cd ../openshift-tests-private && git fetch origin
       ```
     - Checkout the correct branch:
       ```bash
       cd ../openshift-tests-private && git checkout {branch_name} && git pull
       ```
   - **Search Test Code**: Use Grep tool to search for the case ID in openshift-tests-private repository
     - Search path: `../openshift-tests-private`
     - Search pattern: `-{case_id}-` to find the test file containing this case
     - If found, use Read tool to get the test source code (focus on the test logic, typically 50-100 lines around the case ID)
     - **Important**: searching in `test/extended/` directory
   - **Analyze Test Code**: For each found test, analyze:
     - Test implementation quality (potential race conditions, hardcoded waits, flaky selectors)
     - Error handling robustness
     - Whether the failure indicates an automation bug vs product bug
     - Common automation anti-patterns: tight timeouts, missing retries, improper assertions
   - **Assessment**: Provide for each test:
     - `is_likely_automation_issue`: true/false/uncertain
     - `confidence`: high/medium/low
     - `reasoning`: why this appears to be automation vs product issue
     - `test_code_location`: file path (relative to repo root)
     - `recommended_action`: fix test code, file product bug, or investigate further
   - **Important**: Only flag as automation issue if there's clear evidence in the code. When uncertain, default to product bug investigation.

6. **Generate Summary**: Create a concise summary report with:
   - Overall test results (total, passed, failed, skipped)
   - If truncated, clearly state: "Analyzed X representative failures out of Y total failures across Z unique patterns"
   - Top failure patterns with occurrence counts and affected test examples
   - QE Automation Issues (if any detected with test code analysis)
   - Known issues from OCPBUGS (if Jira MCP was available and matches were found)
   - Critical issues that need immediate attention
   - Links to GCS artifacts and detailed logs

7. **Present Results**: Show the analysis in a well-formatted markdown report
   - Use proper line breaks between sections (add blank lines)
   - Keep output concise and readable
   - Use bullet points instead of tables when possible
   - Ensure each field is on its own line with proper spacing

Important notes:
- **Dependencies**: The OAR package must be installed for this command to work
  - If you see import errors, run: `pip3 install -e .` from the repository root
  - This installs the `prow.job.artifacts` module and other required dependencies
- **Required Environment Variable**: `GCS_CRED_FILE` must be set (path to Google Cloud service account credentials file)
  - Check if set with: `echo $GCS_CRED_FILE`
  - The script will fail if this variable is not set
- **Token Limit Management**: The fetcher implements automatic truncation to prevent token limit issues:
  - Individual error messages are limited to 500 characters, stack traces to 2000 characters
  - Failures are grouped by pattern to identify common issues
  - If there are >50 failures (configurable via `MAX_FAILURES_FOR_AI` env var), only representative samples are sent
  - The `failure_patterns` field provides grouped analysis even when truncated
- The helper script uses the existing `prow/job/artifacts.py` infrastructure
- Provide actionable insights, not just raw data
- If you encounter errors, check that dependencies are installed and GCS_CRED_FILE is properly configured
