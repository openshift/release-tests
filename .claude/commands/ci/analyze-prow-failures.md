---
description: Analyze OpenShift CI Prow job failures using AI
---

You are helping the user analyze failures from an OpenShift CI Prow job run.

The user has provided a Prow deck URL (or you should ask for it): {{args}}

Follow these steps:

1. **Parse the URL**: Extract the job name and run ID from the Prow deck URL
   - URL format: `https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/{bucket}/logs/{job_name}/{job_run_id}`
   - Example: `https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.20-automated-release-aws-ipi-f999/1979765746749673472`
   - Extract: bucket (e.g., `qe-private-deck`), job_name, and job_run_id

2. **Fetch test failures and setup must-gather**: Use the Python helper script to fetch JUnit XML files and optionally download/extract must-gather for cluster analysis
   ```bash
   python3 tools/ci_job_failure_fetcher.py <prow_deck_url> --setup-must-gather
   ```
   This will:
   - Output JSON with failure details including test names, error messages, and stack traces
   - Download must-gather.tar if available (from gather-must-gather step)
   - Extract to configured directory (default: `/tmp/must-gather-{job_run_id}/`)
   - Include `must_gather` field in JSON output with extraction status and path

   **Configure omc**: If `must_gather.available` is true in JSON output, run:
   ```bash
   omc use {must_gather.must_gather_dir}
   ```
   Example: `omc use /tmp/must-gather-1983618134094909440`

   **Note**: The `--setup-must-gather` flag is optional. If:
   - must-gather.tar not found: Job may not have gather-must-gather step (skip cluster analysis in step 7)
   - Extraction fails: Check logs and JSON output for error reason
   - Extraction succeeds: Proceed to step 7 for cluster state analysis with omc

3. **Extract Test Metadata** (for later use in Jira searches and code analysis):
   - **Case ID Extraction** (if openshift-tests-private tests detected):
     - Check if test names or stack traces contain `github.com/openshift/openshift-tests-private`
     - Find sequences of digits between dashes in the test name
     - Example: "Author:$uid-LEVEL0-Medium-64296-disable CORS" → case ID is `64296`
     - Look for pattern `-{digits}-` in test name (usually the longest digit sequence is the case ID)
     - Store extracted case IDs for use in steps 4 and 5

   - **Release Branch Extraction** (for code analysis):
     - Extract release version from job name
     - Job name pattern: `periodic-ci-openshift-openshift-tests-private-release-{X.Y}-...`
     - Example: `periodic-ci-openshift-openshift-tests-private-release-4.17-...` → use branch `release-4.17`
     - If no release version found, use `master` branch

4. **AI Analysis**: Analyze the test failures and provide:
   - **Data Handling Note**: The fetcher automatically groups failures by pattern and may truncate data if there are many failures (>50 by default). Check the `truncation_info` and `failure_patterns` fields in the JSON output.
   - **Failure Pattern Analysis**: Use the `failure_patterns` field to identify common root causes. Each pattern shows occurrence count and affected tests.
   - **Failure Categories**: Categorize failures (infrastructure, timeout, assertion, flaky test, etc.)
   - **Priority Assessment**: Identify which failures are most critical based on pattern frequency
   - **Root Cause Hypotheses**: Suggest potential root causes for each failure pattern
   - **Recommended Actions**: Suggest next steps (bug reports, retries, infrastructure fixes, etc.)
   - **Truncation Awareness**: If `is_truncated` is true, acknowledge that only representative samples are shown and mention the total failure count

5. **Query Known Issues from Jira** (Optional - requires Jira MCP):
   - **Checkpoint**: First verify if Jira MCP is available by checking if `mcp__mcp-atlassian__jira_search` tool exists
   - **If Jira MCP is NOT available**: Skip this step gracefully and continue to step 6. Mention in the final report that known issue lookup was skipped (MCP not configured).
   - **If Jira MCP IS available**: Search both OCPBUGS (product bugs) and OCPQE (QE automation issues)

   **A. Search OCPBUGS for Product Bugs**:
   - For each major failure pattern (top 3-5 by occurrence count):
     - Extract 2-3 key terms from error message (e.g., "ImagePullBackOff", "timeout", "authentication failed")
     - Focus on specific component/feature names and unique error keywords
     - Avoid generic terms like "error", "failed", "test", "timeout"
     - Search OCPBUGS using JQL focused on **summary field only** (issue titles):
       ```jql
       project = OCPBUGS AND (summary ~ "keyword1" OR summary ~ "keyword2")
       AND status NOT IN (Closed, Verified)
       ORDER BY updated DESC
       ```
     - **Why summary only**: The `text` field includes descriptions, comments, logs, and stack traces, creating too many false positives
     - Limit to 3-5 most recent/relevant bugs per pattern

   **B. Search OCPQE for QE Automation Issues**:

   - **By Case ID** (use case IDs extracted in step 3):
     ```jql
     project = OCPQE AND (summary ~ "{case_id}" OR description ~ "{case_id}")
     ORDER BY updated DESC
     ```

   - **By Test Name and Error Keywords**:
     - Extract test name (e.g., "OCP-12345") or unique error keywords
     - Focus on test infrastructure terms: "flaky", "intermittent", "race condition", "timeout", "automation"
     ```jql
     project = OCPQE AND (summary ~ "OCP-12345" OR summary ~ "keyword1" OR summary ~ "keyword2")
     ORDER BY updated DESC
     ```

   - **IMPORTANT**:
     - **Include Closed/Done issues** in OCPQE searches (fixes may not be backported to z-stream branches)
     - Limit to 3-5 most relevant issues per search
     - Assess relevance - only include issues that appear related

   **Present Findings**:
   ```markdown
   ### Known Product Bugs (OCPBUGS)
   {if found:}
   - **{BUG_KEY}** ({status}): {summary}
     - Relevance: {brief assessment}
     - Link: {jira_url}
   {if none:}
   - No related OCPBUGS issues found

   ### Known QE Automation Issues (OCPQE)
   {if found by case ID:}
   - **{OCPQE_KEY}** ({status}): {summary}
     - Case ID: {case_id}
     - Relevance: {brief assessment}
     - Link: {jira_url}
     - ⚠️ Note: If Closed/Done, fix may not be backported to this release branch

   {if found by keywords:}
   - **{OCPQE_KEY}** ({status}): {summary}
     - Keywords matched: {list}
     - Relevance: {brief assessment}
     - Link: {jira_url}

   {if none:}
   - No related OCPQE issues found

   **Jira Search Links** (for manual verification):
   - [Search OCPBUGS by keywords]({jira_search_url})
   - [Search OCPQE by case ID]({jira_search_url})
   - [Search OCPQE by keywords]({jira_search_url})
   ```
   - Present with "⚠️ Please manually verify" disclaimer
   - **Only include potentially relevant issues** - do not list clearly unrelated issues (adds noise)

6. **Analyze Cucushift/Cucumber Test Code** (if cucushift failures detected):

   **Detection**: Check if any failure has `cucushift-e2e` in the `source_file` field from JSON output.

   **Cucushift Test Analysis**:
   - Cucushift tests use Cucumber framework (NOT Ginkgo)
   - Test repositories:
     - **verification-tests**: https://github.com/openshift/verification-tests (public)
     - **cucushift**: https://github.com/openshift/cucushift (internal QE - may need auth)
   - **Feature files**: Tests defined in `.feature` files using Ginkgo/Cucumber BDD syntax
   - **Full trace logs**: Available in `cucushift_trace.full_trace` field (enriched from console log)

   **Analyze Cucushift Failures**:

   For each cucushift failure in the JSON output:

   a. **Check for enriched trace data**:
      ```json
      {
        "test_name": "Scenario name from feature file",
        "source_file": "artifacts/.../cucushift-e2e/junit_cucushift-e2e-combined-....xml",
        "cucushift_trace": {
          "full_trace": "... complete trace log from console ...",
          "error_snippet": "... key error messages ...",
          "feature_file": "features/path/to/file.feature",
          "line_number": "123"
        }
      }
      ```

   b. **Locate feature file** (if `feature_file` provided):
      - Clone verification-tests or cucushift repository
      - Navigate to the feature file path (e.g., `features/networking/sdn.feature`)
      - Read scenario at the specified line number

   c. **Analyze full trace log**:
      - Review `cucushift_trace.full_trace` for complete failure context
      - `error_snippet` contains key error messages (filtered for keywords like "error:", "expected:", "got:")
      - Trace includes ~550 lines of context (50 before, 500 after scenario start)

   d. **Root cause assessment workflow**:

      **Step 1: Identify Error Type**
      - Data type mismatches (number vs string, array vs object) → Usually **automation bug**
      - API errors, product crashes, unexpected behavior → Usually **product bug**
      - Setup/teardown errors, missing resources → Usually **infrastructure/automation**

      **Step 2: Locate Source Code**
      - Feature file: `verification-tests/features/<area>/<feature>.feature`
      - Step definitions: `verification-tests/lib/rules/` or `features/step_definitions/`
      - Helper code: `verification-tests/lib/`
      - Look for the feature file path and line number in `cucushift_trace.feature_file`

      **Step 3: Trace the Data Flow**
      - Find where test parameters are defined (feature file, example tables, scenario outline)
      - Find where parameters are processed (step definitions in Ruby)
      - Find where parameters are passed to OpenShift API (helper methods, kubectl/oc commands)

      **Step 4: Determine Root Cause**

      **Example: Type Mismatch Errors**
      ```
      Error: "json: cannot unmarshal number into Go struct field ObjectMeta.metadata.namespace of type string"

      Root Cause Analysis:
      1. Error shows namespace expected as STRING but received NUMBER
      2. Check feature file for namespace definition:
         Examples:
           | namespace |
           | 49831     |  # <-- YAML interprets this as integer

      3. Check step definition handling this parameter:
         When /^I run the :create command with:$/ do |table|
           opts = table.rows_hash
           # BUG: opts[:namespace] is Integer (49831) not String ("49831")
           run_command(:create, opts)
         end

      4. Conclusion: Test automation bug - needs type conversion
      ```

      **Step 5: Common Cucumber/Cucushift Anti-patterns**
      - Hardcoded waits without proper conditionals
      - Missing type conversions for parameters from example tables
      - Missing step error handling
      - Flaky element selectors or timing issues
      - Race conditions in async operations

   e. **Provide comprehensive analysis with fix proposal**:
      ```markdown
      ### Cucushift Test Failure Analysis

      **Scenario**: {test_name}
      **Feature File**: {feature_file}:{line_number}
      **Source Repository**: https://github.com/openshift/verification-tests

      **Error Summary**:
      {error_snippet from cucushift_trace}

      **Full Error Context**:
      {relevant portion of full_trace showing error and surrounding context}

      **Root Cause Analysis**:

      1. **Error Type**: {Data type mismatch / API error / etc.}

      2. **Data Flow Trace**:
         - Parameter defined in: {feature file location}
         - Parameter processed by: {step definition file/method}
         - Parameter passed to: {OpenShift API / kubectl command}

      3. **Root Cause**: {detailed explanation of what went wrong}

      4. **Evidence**:
         - Expected: {what the code expected}
         - Actual: {what was provided}
         - Why mismatch occurred: {explanation}

      **Assessment**:
      - **Classification**: {Automation Bug / Product Bug / Infrastructure Issue}
      - **Confidence**: {HIGH / MEDIUM / LOW}
      - **Reasoning**: {why this classification - reference error patterns}

      **Fix Proposal**:

      **Location**: `verification-tests/{file_path}`

      **Current Code** (estimated based on error):
      ```ruby
      When /^I run the :create command with:$/ do |table|
        opts = table.rows_hash
        # BUG: namespace comes as Integer from YAML example table
        run_command(:create, opts)
      end
      ```

      **Proposed Fix**:
      ```ruby
      When /^I run the :create command with:$/ do |table|
        opts = table.rows_hash
        # FIX: Convert all parameter values to strings for API compatibility
        opts = opts.transform_values(&:to_s)
        run_command(:create, opts)
      end
      ```

      **OR** (if only namespace needs conversion):
      ```ruby
      When /^I run the :create command with:$/ do |table|
        opts = table.rows_hash
        opts[:namespace] = opts[:namespace].to_s if opts[:namespace]
        run_command(:create, opts)
      end
      ```

      **Alternative Fix** (in feature file):
      ```gherkin
      Examples:
        | namespace |
        | "49831"   |  # Quote to force string in YAML
      ```

      **Recommended Action**:
      1. Clone verification-tests repository
      2. Locate the step definition handling this command
      3. Add type conversion as shown above
      4. Add test case to verify fix
      5. Submit PR to verification-tests

      **References**:
      - Test case: {test_name}
      - Feature file: {feature_file}:{line_number}
      - Prow job: {job_url}
      ```

   **Important Notes**:
   - **DO NOT** search openshift-tests-private for cucushift tests (that's for Ginkgo tests only)
   - **DO NOT** confuse Cucumber scenarios with Ginkgo test cases
   - Cucushift tests focus on operator/workload behavior, not core OpenShift APIs
   - If `cucushift_trace` field is missing: trace extraction failed (scenario not found in console log)

7. **Analyze Ginkgo QE Automation Test Code** (if openshift-tests-private detected):
   - Use case IDs and release branch extracted in step 3
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

7. **Cluster State Analysis with must-gather** (Optional - if must-gather is available):
   - **Check Availability**: Look for `must_gather` field in the JSON output from step 2
   - **If available = false**: Skip this step and note the reason in final report
   - **If available = true**: Use omc commands to analyze cluster state and debug failures

   **Supported omc Commands for Failure Analysis**:
   ```bash
   # View pods in all namespaces (check for CrashLoopBackOff, ImagePullBackOff, etc.)
   omc get pods -A

   # Check specific pod details
   omc get pod <pod-name> -n <namespace> -o yaml
   omc describe pod <pod-name> -n <namespace>

   # Check pod logs for failed test resources
   omc logs -n <namespace> <pod-name>
   omc logs -n <namespace> <pod-name> --previous  # Previous container logs

   # View events (shows root causes for resource failures)
   omc get events -A
   omc get events -n <namespace>

   # Check node status
   omc get nodes
   omc describe node <node-name>

   # View cluster operators status
   omc get co
   omc describe co <operator-name>

   # Check deployments, replicasets, statefulsets
   omc get deploy -A
   omc get rs -A
   omc get sts -A

   # Check services, routes, endpoints
   omc get svc -A
   omc get route -A
   omc get endpoints -A

   # Check PVCs and storage
   omc get pvc -A
   omc describe pvc <pvc-name> -n <namespace>

   # Check networking diagnostic events
   omc get events -n openshift-network-diagnostics
   ```

   **Analysis Strategy for Failed Tests**:
   1. **Identify test namespace**: Extract from failure details (e.g., test creates resources in specific namespace)
   2. **Check test resources**: Use `omc get pods -n <test-namespace>` to see pod status
   3. **Analyze pod failures**: Use `omc describe pod` and `omc logs` for failed pods
   4. **Check events**: Use `omc get events -n <test-namespace>` to see what happened
   5. **Verify dependencies**: Check if services, configmaps, secrets exist as expected
   6. **Cluster health**: Check nodes, cluster operators for infrastructure issues

   **Example Workflow for Failed Test Analysis**:
   ```bash
   # 1. Find pods related to failed test (e.g., test creates pods with specific labels)
   omc get pods -A | grep <test-identifier>

   # 2. Check pod status and events
   omc describe pod <test-pod> -n <namespace>

   # 3. Get pod logs to see actual error
   omc logs <test-pod> -n <namespace>

   # 4. Check related events
   omc get events -n <namespace> | tail -20

   # 5. If networking issue, check service/endpoints
   omc get svc -n <namespace>
   omc get endpoints -n <namespace>
   ```

   **Include in Report**:
   ```markdown
   ### Cluster State Analysis (must-gather)

   **Must-gather Status**: {available/not available - reason}

   {if available:}
   **Resources Analyzed for Failed Tests**:
   - Test namespace: {namespace}
   - Pods checked: {list of relevant pods and their status}
   - Key findings: {what omc commands revealed}

   **Root Cause Evidence from Cluster**:
   - {Finding 1 from omc - e.g., "Pod test-xyz-123 in CrashLoopBackOff, logs show ImagePullBackOff"}
   - {Finding 2 - e.g., "Events show 'Failed to pull image: unauthorized'"}
   - {Finding 3 - e.g., "Service endpoint missing for test workload"}

   **Correlation with Test Failures**:
   - {How cluster resource state explains the test failure}

   **Recommended Actions**:
   - {Actions based on cluster analysis - e.g., "Fix image pull secret", "Increase resource limits"}
   ```

8. **Generate Summary**: Create a concise summary report with:
   - Overall test results (total, passed, failed, skipped)
   - If truncated, clearly state: "Analyzed X representative failures out of Y total failures across Z unique patterns"
   - Top failure patterns with occurrence counts and affected test examples
   - QE Automation Issues (if any detected with test code analysis)
   - Known issues from OCPBUGS and OCPQE (if Jira MCP was available and matches were found)
   - Critical issues that need immediate attention
   - Links to GCS artifacts and detailed logs

9. **Present Results**: Show the analysis in a well-formatted markdown report
   - Use proper line breaks between sections (add blank lines)
   - Keep output concise and readable
   - Use bullet points instead of tables when possible
   - Ensure each field is on its own line with proper spacing

10. **Cleanup must-gather** (if must-gather was downloaded):
   - After completing the analysis, clean up the must-gather directory to free disk space
   - Use the path from `must_gather.must_gather_dir` field in JSON output
   - Example: `rm -rf /tmp/must-gather-{job_run_id}/`
   - **IMPORTANT**: Always include the cleanup command in your final report so the user can clean up manually if needed

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
