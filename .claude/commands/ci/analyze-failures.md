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
   - **Known Issues**: If failures match known patterns, reference similar issues
   - **Bug Triage**: If the failure appears to be a product bug, include a tip to contact the component team to confirm if it's a known issue or a new bug that needs to be filed
   - **Truncation Awareness**: If `is_truncated` is true, acknowledge that only representative samples are shown and mention the total failure count

4. **Generate Summary**: Create a concise summary report with:
   - Overall test results (total, passed, failed, skipped)
   - If truncated, clearly state: "Analyzed X representative failures out of Y total failures across Z unique patterns"
   - Top failure patterns with occurrence counts and affected test examples
   - Critical issues that need immediate attention
   - Links to GCS artifacts and detailed logs

5. **Present Results**: Show the analysis in a well-formatted markdown report
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
