---
description: Analyze Jenkins job failures (image-consistency-check, stage-testing) using AI
---

You are helping the user analyze failures from a Jenkins job run (typically image-consistency-check or stage-testing jobs used in z-stream release testing).

The user has provided a Jenkins job URL: {{args}}

## Overview

Jenkins jobs used in OAR z-stream release workflow:
- **image-consistency-check**: Verifies payload image consistency
- **stage-testing** (Stage-Pipeline): Runs E2E tests for optional operators shipped with Openshift

Each job has its own custom console log format. This command fetches the raw console log and analyzes it based on the job type.

## Steps

### 1. Validate and Parse Jenkins URL

Expected URL patterns:
- `https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/{job_name}/{build_number}/`

Extract:
- **Base URL**: e.g., `https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com`
- **Job name**: e.g., `image-consistency-check` or `zstreams/Stage-Pipeline`
- **Build number**: e.g., `3436`

### 2. Fetch Job Parameters via API

Jenkins provides a JSON API to get job parameters (more reliable than parsing console logs).

**Construct the API URL**:

For simple job names:
```
{base_url}/job/{job_name}/{build_number}/api/json
```

For folder-based job names (e.g., `zstreams/Stage-Pipeline`):
```
{base_url}/job/zstreams/job/Stage-Pipeline/{build_number}/api/json
```

**Fetch job metadata and parameters**:
```bash
curl -s "{api_url}"
```

**Extract key parameters from JSON response**:

The response contains `actions` array with a `hudson.model.ParametersAction` object containing all build parameters:

```json
{
  "actions": [
    {
      "_class": "hudson.model.ParametersAction",
      "parameters": [
        {
          "_class": "hudson.model.StringParameterValue",
          "name": "VERSION",
          "value": "v4.20"
        },
        {
          "_class": "hudson.model.StringParameterValue",
          "name": "PAYLOAD_URL",
          "value": "quay.io/openshift-release-dev/ocp-release:4.20.1-x86_64"
        },
        {
          "_class": "hudson.model.StringParameterValue",
          "name": "SHIPMENT_MR_ID",
          "value": "189"
        }
      ]
    }
  ],
  "result": "SUCCESS" | "FAILURE" | "UNSTABLE" | "ABORTED",
  "building": false,
  "duration": 5668839,
  "timestamp": 1761310656601
}
```

**Key fields to extract**:
- `result`: Job final status (SUCCESS, FAILURE, UNSTABLE, ABORTED)
- `building`: Whether job is still running
- `duration`: Job execution time in milliseconds
- `timestamp`: Job start time
- `parameters`: All build parameters (PAYLOAD_URL, SHIPMENT_MR_ID, VERSION, etc.)

**Parse parameters using jq** (if available):
```bash
# Get PAYLOAD_URL
curl -s "{api_url}" | jq -r '.actions[] | select(._class=="hudson.model.ParametersAction") | .parameters[] | select(.name=="PAYLOAD_URL") | .value'

# Get SHIPMENT_MR_ID
curl -s "{api_url}" | jq -r '.actions[] | select(._class=="hudson.model.ParametersAction") | .parameters[] | select(.name=="SHIPMENT_MR_ID") | .value'

# Get job result
curl -s "{api_url}" | jq -r '.result'
```

**Alternative: Parse using grep/sed** (if jq not available):
```bash
# Get all parameters
curl -s "{api_url}" | grep -o '"name":"[^"]*","value":"[^"]*"'
```

### 3. Fetch Console Log

Jenkins console logs are publicly accessible via `/consoleText` endpoint (no authentication required).

**Construct the console text URL**:

For simple job names:
```
{base_url}/job/{job_name}/{build_number}/consoleText
```

For folder-based job names (e.g., `zstreams/Stage-Pipeline`):
```
{base_url}/job/zstreams/job/Stage-Pipeline/{build_number}/consoleText
```

**Fetch the log**:
```bash
curl -s "{console_text_url}"
```

**Token Management**:
- Console logs can be 5K-20K+ lines
- Focus on last 1000-2000 lines for most relevant information:
  ```bash
  curl -s "{console_text_url}" | tail -n 2000
  ```
- For errors/failures specifically:
  ```bash
  curl -s "{console_text_url}" | grep -i "error\|fail\|exception" | tail -n 500
  ```

### 4. Job-Specific Analysis

#### A. image-consistency-check Job

This job verifies images from release payload against shipment data:
- Iterates all images from release payload (PAYLOAD_URL parameter)
- Compares with shipment data (YAML files in GitLab MR specified by SHIPMENT_MR_ID)
- Multi-arch images are compared using default arch `linux/amd64`
- Reports mismatches if images cannot be found in shipment data

**Key console log sections**:

```
#Mismatch between payload and Advisory
```
**CRITICAL** - Lists images not found in shipment data or registries.

Example format:
```
#Mismatch between payload and Advisory
--------------------------------------
Image   status   Justification

quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:07f75fe... FAIL Couldn't find this image...
pull_spec: quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:07f75fe... != None
digest: sha256:07f75fe65ee24835d18df82cb11c2bd28424837e0bea3f9534a4ebd40706c409
src_commit ID: 1db726a940d5ec150fd185a215f1368990653082
tag: v4.20.0-202510211040.p0.g1db726a.assembly.stream.el9
```

**How the script works** (important context):
- Uses `oc image info --filter-by-os linux/amd64` to compare images
- Comparison based on digest, listdigest, or vcs-ref
- First checks if image exists in `registry.redhat.io` (already shipped)
- Then queries `pyxis.engineering.redhat.com` API to check if image is signed/shipped
- Only reports FAIL if image NOT found in: shipment MR AND registry.redhat.io AND pyxis

**MANDATORY: Validate each reported image failure**

For each image in the "#Mismatch between payload and Advisory" section, you MUST:

1. **Search console log for the image SHA** (first 8-12 chars of digest):
   ```bash
   # The script logs: #checking quay.io/.../sha256:07f75fe...
   # Search for this pattern to see if image was processed
   ```

2. **Check the image processing result**:
   - Look for lines AFTER "#checking {image_sha}"
   - Check for:
     - `[INFO]` log level = successful processing
     - `[ERROR]` or `[WARNING]` = issues during processing
     - Errors like: `manifest unknown`, `unauthorized`, `connection refused`

3. **CRITICAL: Check for multi-arch manifest parsing errors**:

   Multi-arch images can fail manifest parsing with transient errors. This is the MOST COMMON false positive.

   **Detection pattern**:
   - Search console for `[WARNING] root: OpenshiftImage: oc image info` with ANY error (Return code: 1)
   - Common error patterns include (but not limited to):
     - `error: unable to read image ... unable to retrieve source image ... manifest #N from manifest list`
     - `error unmarshalling content: invalid character 'H' looking for beginning of value`
     - `error: unauthorized: authentication required`
     - `error: manifest unknown`
     - Any other `oc image info` failure on multi-arch images

   **Verification workflow** (MANDATORY):

   For each WARNING message with `oc image info` error found:

   a. **Extract the multi-arch image SHA** from the warning:
      ```bash
      # Example: [WARNING] root: OpenshiftImage: oc image info quay.io/.../sha256:4b7314bc...
      # Extract: sha256:4b7314bc...
      ```

   b. **Check if this multi-arch image has arch-specific variants**:
      ```bash
      # Run locally to get manifest list
      oc image info quay.io/redhat-user-workloads/ocp-art-tenant/art-images@sha256:4b7314bc... --filter-by-os linux/amd64
      ```

   c. **Extract the linux/amd64 image digest** from the manifest:
      ```bash
      # Output will show:
      # Name: quay.io/.../sha256:4b7314bc...
      # Digest: sha256:07f75fe6...  ← This is the arch-specific image
      ```

   d. **Compare with mismatched image SHA**:
      - If the arch-specific digest (e.g., `sha256:07f75fe6...`) matches the image in mismatch list
      - Then this confirms the mismatch is caused by the multi-arch manifest parsing error
      - **Categorization**: Transient infrastructure issue → RETRY

   **How this manifests**:
   - Script tries: `oc image info quay.io/.../sha256:4b7314bc...` (multi-arch image from shipment MR)
   - Gets error: `error unmarshalling content: invalid character 'H'`
   - Script fallback: `oc image info --filter-by-os linux/amd64 quay.io/.../sha256:4b7314bc...`
   - Extracts arch-specific digest: `sha256:07f75fe6...`
   - This arch-specific image appears in mismatch list because parent check failed

   **Example from real failure**:
   ```
   [WARNING] root: OpenshiftImage: oc image info quay.io/redhat-user-workloads/ocp-art-tenant/art-images@sha256:4b7314bc... Return code: 1
   error: unable to read image sha256:4b7314bc...: unable to retrieve source image sha256:4b7314bc...:
   error unmarshalling content: invalid character 'H' looking for beginning of value

   # Verify by checking the arch-specific variant:
   $ oc image info quay.io/redhat-user-workloads/ocp-art-tenant/art-images@sha256:4b7314bc... --filter-by-os linux/amd64
   Name: quay.io/redhat-user-workloads/ocp-art-tenant/art-images@sha256:4b7314bc...
   Digest: sha256:07f75fe65ee24835d18df82cb11c2bd28424837e0bea3f9534a4ebd40706c409

   # Then in mismatch list:
   quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:07f75fe... FAIL Couldn't find this image...
   # ✅ MATCH CONFIRMED: sha256:07f75fe... is the linux/amd64 variant of sha256:4b7314bc...
   ```

   **Categorization** (only if SHA match confirmed):
   - This is a **transient infrastructure issue**, NOT a payload failure
   - Recommendation: **RETRY JOB** (not escalate to ART)
   - The image exists in shipment MR but manifest retrieval failed temporarily

   **Important**: If the arch-specific SHA does NOT match the mismatch image, this is NOT a multi-arch manifest parsing issue. Continue investigating other root causes.

4. **Understand other FALSE POSITIVE scenarios**:
   - **Already shipped**: Image found in `registry.redhat.io` but not in MR
     - Script should say: "This image isn't attached to advisories, but can be found in registry.redhat.io"
     - This is NOT a failure - image was shipped in previous release
   - **Successful check**: Found `#checking ...sha256:07f75fe [INFO]` with no errors
     - Image was processed successfully
     - Mismatch report is script error

5. **Identify GENUINE FAILURES**:
   - **Missing from shipment MR**: Image not in YAML files AND not in registry.redhat.io
     - Justification: "Couldn't find this image on either advisory or registry.redhat.io"
     - Pull errors or oc command failures for this specific SHA
     - **AND no multi-arch manifest parsing warnings for this image**
   - **Network/pull errors**: Errors pulling/checking the image
     - Can be transient (retry) or genuine missing image
     - Check if error is multi-arch manifest parsing (retry) vs genuine pull failure (investigate)

6. **Root cause categories**:
   - **Shipment data issue**: ART forgot to include image in MR → ESCALATE TO ART
   - **Already shipped**: Image in previous release, not needed in MR → SAFE TO IGNORE
   - **Network/transient**: Temporary infrastructure issue → RETRY JOB
   - **Script error**: False positive from checker → FILE BUG FOR SCRIPT

**Analysis Output Template**:

```markdown
## Jenkins Job Analysis: image-consistency-check

**Job Information**:
- URL: {jenkins_url}
- Console Log: {console_text_url}
- Build: #{build_number}
- Status: {SUCCESS|FAILURE|UNSTABLE} {emoji}
- Payload: {payload_url}
- Advisories/MR: {errata_numbers or shipment_mr_id}
- Version: {version}

**Analysis Results**:

### 1. Image Consistency Check
{Parse #Image Check Result section}
- Status: {✅ PASS | ❌ FAIL}
- Details: {list inconsistencies if any, otherwise "No image inconsistencies found"}

**Overall Assessment**:

**Critical Issues** ({count}):
{List blockers that MUST be resolved}

**Warnings** ({count}):
{List non-blocking issues for awareness}

**Recommendation**: {✅ PASS | ❌ FAIL | 🔄 RETRY | ⚠️ NEEDS REVIEW}

**Rationale**: {Explain why job should pass/fail/retry}
- {Reason 1}
- {Reason 2}

**Special cases**:
- If multi-arch manifest parsing errors detected → 🔄 RETRY (not escalate to ART)
- If images already shipped in registry.redhat.io → ✅ PASS (safe to ignore)
- If genuine missing images (not in MR AND not in registry.redhat.io AND no manifest errors) → ❌ FAIL (escalate to ART)

**Next Actions**:
1. {Action if needed}
2. {Action if needed}
```

#### B. stage-testing (Stage-Pipeline) Job

This job orchestrates E2E testing for optional operators shipped with OpenShift:

**Pipeline Flow**:
1. **Verify Metadata** - Validates metadata advisory (may be skipped for Konflux flow)
2. **Install Cluster** - Triggers `Flexy-install` child job to provision OCP cluster
3. **Create Test Run** - Prepares test execution environment
4. **Non-admin and non-destructive tests** - Runs 3 parallel `Runner` child jobs
5. **Normal ginkgo tests** - Triggers `ginkgo-test` child job
6. **Admin tests** - Runs 3 parallel `Runner` child jobs
7. **Destructive tests** - Runs 1 `Runner` child job
8. **Disruptive ginkgo tests** - Triggers `ginkgo-test` child job
9. **Check Results** - Validates test results and sends failure notifications
10. **Cleanup** - Triggers `Flexy-destroy` child job to tear down cluster

**Key console log patterns**:

**Pipeline stages** (look for):
```
[Pipeline] stage
[Pipeline] { (Stage Name)
```
Each stage shows:
- START marker: `[Pipeline] stage`
- Stage name: `[Pipeline] { (Install Cluster)`
- End marker: `[Pipeline] // stage`
- May be skipped: `Stage "Verify Metadata" skipped due to when conditional`

**Child jobs** (critical for analysis):
```
Scheduling project: ocp-common » Flexy-install
Starting building: ocp-common » Flexy-install #360950
Build ocp-common » Flexy-install ocpqe-jenkins-bot-360950 completed: SUCCESS
```

Format:
- **Scheduling**: When job is queued
- **Starting building**: When job execution begins (includes build number)
- **Build completed**: Final status (SUCCESS/FAILURE/UNSTABLE)

**Child Job Types**:
- `Flexy-install` - OCP cluster installation (1 job)
- `Runner` - **Cucumber test runner** (7 parallel jobs total)
  - **IMPORTANT**: Runner jobs use Cucumber tests from **verification-tests** or **cucushift** repositories
  - **NOT** from openshift-tests-private (which is for Ginkgo tests only)
- `ginkgo-test` - **Ginkgo test runner** (2 jobs)
  - **IMPORTANT**: ginkgo-test jobs use Ginkgo tests from **openshift-tests-private** repository
  - **NOT** from verification-tests/cucushift (which are for Cucumber tests)
- `Flexy-destroy` - Cluster cleanup (1 job)

**Job Parameters** (search in first 300 lines):
```
PULL_SPEC=quay.io/openshift-release-dev/ocp-release:4.15.59-x86_64
```
- Indicates which OpenShift release payload is being tested

**How to Analyze Failures**:

When stage-pipeline fails, follow these steps:

1. **Check Bundle Image Availability** (ALWAYS RUN THIS FIRST):

   Stage testing failures may be caused by missing operator bundle images in registry.stage.redhat.io.

   **Extract OCP version from job parameters**:
   ```bash
   # Get PULL_SPEC or PAYLOAD_URL parameter (e.g., "quay.io/openshift-release-dev/ocp-release:4.20.1-x86_64")
   # Extract major.minor version (e.g., "4.20")
   VERSION=$(curl -s "{api_url}" | jq -r '.actions[] | select(._class=="hudson.model.ParametersAction") | .parameters[] | select(.name=="PULL_SPEC" or .name=="PAYLOAD_URL") | .value' | grep -oE '[0-9]+\.[0-9]+' | head -1)
   ```

   **Run bundle availability check**:
   ```bash
   # From release-tests repository root
   ./tools/check_stage_bundle_images.sh ${VERSION}
   ```

   **Include in analysis output**:

   If bundles are missing (exit code 1):
   ```markdown
   ## Bundle Image Availability Check

   **Version**: {version}
   **Status**: ❌ Missing bundles detected

   **Missing Operator Bundles** ({count}):
   - {operator-name-1}
   - {operator-name-2}
   - {operator-name-3}
   ...

   **Report**: {/tmp/stage-bundle-check-YYYYMMDD-HHMMSS/MISSING_REPORT.txt}

   **Impact**: These operator bundle images are missing from registry.stage.redhat.io.
   This may cause operator installation failures if tests require these operators.

   **Action Required**:
   - Share MISSING_REPORT.txt with ART team
   - File ticket to mirror missing bundles to stage registry
   ```

   If all bundles available (exit code 0):
   ```markdown
   ## Bundle Image Availability Check

   **Version**: {version}
   **Status**: ✅ All latest bundles available

   All {count} operator bundle images are properly mirrored to stage registry.
   ```

   **IMPORTANT**:
   - Do NOT attempt automatic correlation between missing bundles and test failures
   - Report missing bundles as a separate finding
   - Continue with normal test failure analysis below
   - Let user determine if missing bundles are related to specific test failures

2. **Identify Failed Child Job**:
   - Search for `completed: FAILURE` or `completed: UNSTABLE`
   - Example: `Build ocp-common » Runner #1116884 completed: FAILURE`
   - Note the child job name and build number

2. **Determine Stage Where Failure Occurred**:
   - Find the stage containing the failed child job
   - Stages: "Install Cluster", "non-admin and non-destructive tests", "normal ginkgo tests", "admin tests", "destructive tests", "disruptive ginkgo tests"

3. **Check Child Job Logs** (CRITICAL for root cause):
   - Child job URLs follow pattern: `https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/ocp-common/job/{job_type}/{build_number}/consoleText`
   - For `Flexy-install`/`Flexy-destroy`: Infrastructure/cluster provisioning issues
   - For `Runner`: Cucumber test failures - **MUST check child job console for failed scenario**
   - For `ginkgo-test`: Ginkgo E2E test failures - **MUST check child job console for failed test**

4. **Analyze Cucumber Test Failures (Runner jobs)**:

   **Child Job Console Analysis**:
   - Fetch child job console: `curl -s "https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/ocp-common/job/Runner/{build_number}/consoleText"`
   - Search for failure markers:
     ```
     Scenario: <scenario_name>   # Cucumber scenario that failed
     expected: <expected_value>
     got: <actual_value>
     Failing Scenarios:
     cucumber features/<feature_file>.feature:<line_number> # <scenario_name>
     ```

   **Identify Failed Test File**:
   - Failed scenario format: `cucumber features/logging/elasticsearch.feature:45`
   - Extract feature file path and scenario name

   **Locate Test Source Code**:
   - Cucumber tests come from TWO repositories:
     - **https://github.com/openshift/verification-tests/** (public test repo)
     - **https://github.com/openshift/cucushift** (internal QE repo - may need auth)
   - Feature file path from error corresponds to: `features/<path>` in repo
   - Example: `features/logging/elasticsearch.feature` → clone repo and find this file

   **Analyze Test Code**:
   - Use Read tool to examine the feature file at the failed line number
   - Look for the scenario definition (starts with `Scenario:`)
   - Examine step definitions to understand what the test is validating
   - Common patterns:
     - Resource creation/deletion failures
     - Assertion failures (expected vs actual values)
     - Timeout waiting for resource state
     - API call failures

   **Assessment**:
   - If test code has issues (race condition, flaky selector, hardcoded wait): **Test Automation Issue**
   - If error indicates product functionality broken: **Product Bug**
   - If timeout or resource not ready: **Infrastructure or Timing Issue**

5. **Analyze Ginkgo Test Failures (ginkgo-test jobs)**:

   **Child Job Console Analysis**:
   - Fetch child job console: `curl -s "https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/ocp-common/job/ginkgo-test/{build_number}/consoleText"`
   - Search for failure markers (similar to Prow Ginkgo failures):
     ```
     • Failure [<duration>]
     [FAILED] <test_name>
     Expected <condition>
     error: <error_message>
     ```

   **Identify Failed Test**:
   - Extract test name and error message
   - Look for case ID pattern in test name: `-{digits}-` (e.g., `OCP-12345` or test with `-64296-`)

   **Locate Test Source Code**:
   - **Repository**: https://github.com/openshift/openshift-tests-private/
   - **CRITICAL**: Checkout correct release branch for z-stream version
     - For 4.19.z releases: `git checkout release-4.19`
     - For 4.20.z releases: `git checkout release-4.20`
     - Pattern: `release-{major.minor}` (use z-stream version's major.minor)
   - **Setup**:
     ```bash
     # Check if repo exists
     if [ -d "../openshift-tests-private" ]; then
       cd ../openshift-tests-private && git fetch origin
     else
       cd .. && git clone git@github.com:openshift/openshift-tests-private.git
     fi

     # Checkout correct branch (extract version from PULL_SPEC)
     # e.g., PULL_SPEC=quay.io/.../4.15.59-x86_64 → release-4.15
     git checkout release-{X.Y} && git pull
     ```

   **Search for Test Code**:
   - If case ID found (e.g., `64296`): Search for `-{case_id}-` pattern
     ```bash
     grep -r "\-64296\-" test/extended/
     ```
   - If no case ID: Search by test description keywords
   - Test files are in `test/extended/` directory

   **Analyze Test Code**:
   - Use Read tool to examine the test file
   - Understand test logic: what is being validated?
   - Check for common issues:
     - Hardcoded timeouts that are too short
     - Missing retries for eventually-consistent operations
     - Improper error handling
     - Race conditions in resource creation/validation

   **Assessment**:
   - If test code has clear issues: **Test Automation Issue** → File OCPQE bug
   - If test correctly validates product behavior: **Product Bug** → File OCPBUGS issue
   - If uncertain: **Needs Review** → Analyze both test and product behavior

6. **Common Failure Patterns**:
   - **Flexy-install fails**: Cluster installation timeout, quota exceeded, infrastructure issues
   - **Runner (Cucumber) fails**: Operator functionality tests - check feature file for scenario details
   - **ginkgo-test fails**: E2E test failure - check test code for validation logic
   - **Flexy-destroy fails**: Cleanup timeout - **NOT A BLOCKER** (cluster cleanup issues don't affect release approval)

7. **Categorize Failure Type**:
   - **Infrastructure**: Cluster installation, network, quota issues → RETRY
   - **Product Bug**: Operator/feature functionality broken → FAIL (file OCPBUGS)
   - **Test Automation Issue**: Flaky test, improper assertions, race conditions → File OCPQE bug
   - **Test Flake**: Intermittent failure with no clear root cause → NEEDS REVIEW (check history)
   - **Known Issue**: Already tracked bug → Check if waivable
   - **Cleanup Failure**: Flexy-destroy job failed → **SAFE TO IGNORE** (not a release blocker)

8. **Live Cluster Access for Deep Troubleshooting** (OPTIONAL but highly valuable):

   **Check if Cluster is Still Running**:
   - Stage-pipeline may keep cluster alive after test failures for debugging
   - Cluster is only destroyed at the end by `Flexy-destroy` job
   - If `Flexy-destroy` hasn't run or failed, cluster may still be accessible

   **Obtain Kubeconfig**:
   - Kubeconfig is stored as Jenkins artifact in `Flexy-install` job
   - URL pattern: `https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/ocp-common/job/Flexy-install/{build_number}/artifact/workdir/install-dir/auth/kubeconfig`
   - Extract `Flexy-install` build number from stage-pipeline console (e.g., `#360923`)
   - Download kubeconfig:
     ```bash
     # Extract Flexy-install build number from stage-pipeline log
     # Look for: "Build ocp-common » Flexy-install #360923 completed: SUCCESS"

     BUILD_NUM=360923  # Replace with actual build number
     curl -s "https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/ocp-common/job/Flexy-install/${BUILD_NUM}/artifact/workdir/install-dir/auth/kubeconfig" -o /tmp/kubeconfig-${BUILD_NUM}
     ```

   **Verify Cluster Accessibility**:
   ```bash
   export KUBECONFIG=/tmp/kubeconfig-${BUILD_NUM}

   # Test cluster connectivity
   oc cluster-info
   oc get nodes
   oc get clusterversion
   ```

   **If Cluster is Active - Deep Troubleshooting**:

   When cluster is accessible, you can perform deep analysis:

   **For Cucumber Test Failures** (Runner jobs):

   **CRITICAL: Check CatalogSource Health First**:

   Stage-testing failures often occur because CatalogSource is not READY or operators are not in the index image. **ALWAYS check this first**:

   ```bash
   # 1. Check CatalogSource connection state (MUST be READY)
   oc get catalogsource -n openshift-marketplace -o yaml

   # Or use yq to extract connection state directly:
   oc get catalogsource redhat-operators -n openshift-marketplace -o yaml | yq -y '.status.connectionState.lastObservedState'
   # Expected output: READY

   # Check all catalogsources:
   for catsrc in $(oc get catalogsource -n openshift-marketplace -o name); do
     echo "Checking $catsrc"
     oc get $catsrc -n openshift-marketplace -o jsonpath='{.metadata.name}: {.status.connectionState.lastObservedState}{"\n"}'
   done

   # Expected output for all catalogsources: READY
   # If NOT READY, check the full status:
   oc get catalogsource <catalogsource-name> -n openshift-marketplace -o yaml
   ```

   **Interpret CatalogSource Status**:
   ```yaml
   # Look for these fields in catalogsource YAML:
   status:
     connectionState:
       lastObservedState: READY   # ← MUST be READY
       address: ...               # gRPC connection address

   # Common non-READY states and causes:
   # - CONNECTING → Still initializing, wait a bit
   # - TRANSIENT_FAILURE → Network/registry issues, may recover
   # - "" (empty) → CatalogSource pod not running or failed

   # If state is not READY, check catalogsource pod:
   oc get pods -n openshift-marketplace | grep <catalogsource-name>
   oc logs <catalogsource-pod> -n openshift-marketplace
   ```

   **Check Subscription Status for Operator Availability**:
   ```bash
   # 2. Check subscription status
   oc get subscription <operator-subscription> -n openshift-operators -o yaml

   # Look for these CRITICAL error patterns in subscription status:
   # Under .status.conditions[] array:

   # ❌ "constraints not satisfiable: no operators found"
   #    → Operator is NOT in the index image (catalogsource)
   #    → This is NOT a product bug - operator not included in this release
   #    → Action: Verify operator should be in this release's index image

   # ❌ "install plan not approved"
   #    → Manual approval required (configuration issue)

   # ❌ "no package found"
   #    → Wrong package name or operator doesn't exist in catalog
   ```

   **If "constraints not satisfiable: no operators found"**:
   ```bash
   # 3. Verify what operators are available in the catalogsource
   oc get packagemanifests -n openshift-marketplace | grep <operator-name>

   # Alternative method if oc get packagemanifest doesn't work:
   # Use opm command to list packages from index image directly
   # Tag pattern: ocp-{major.minor} (e.g., ocp-4.15, ocp-4.19)
   # Prerequisite: opm command must be available in PATH
   opm --skip-tls-verify alpha list packages quay.io/openshift-art/stage-fbc-fragments:ocp-4.15

   # Example: Check if specific operator package exists
   opm --skip-tls-verify alpha list packages quay.io/openshift-art/stage-fbc-fragments:ocp-4.19 | grep <operator-package-name>

   # If operator is NOT listed:
   # - Operator is not included in this release's index image
   # - This is EXPECTED for optional operators not shipping in this z-stream
   # - **NOT a test failure** - test should be skipped or marked as expected
   # - Action: Confirm with ART if operator should be in this index

   # 4. Check which catalogsource provides the operator (if packagemanifest works)
   oc get packagemanifest <operator-name> -n openshift-marketplace -o yaml
   # Look at: .status.catalogSource and .status.catalogSourceNamespace
   ```

   **After confirming CatalogSource is READY and operator is available**:

   - Check operator pod status:
     ```bash
     # Find namespace where operator is deployed (e.g., openshift-logging, openshift-storage)
     oc get pods -A | grep -i <operator-name>

     # Check pod status and events
     oc describe pod <pod-name> -n <namespace>
     oc logs <pod-name> -n <namespace>

     # Check operator resource status
     oc get <operator-crd> -n <namespace>
     oc describe <operator-crd> <resource-name> -n <namespace>
     ```

   - Verify operator installation:
     ```bash
     oc get clusterserviceversion -n openshift-operators
     oc get installplan -n openshift-operators
     oc describe subscription <operator-subscription> -n openshift-operators
     ```

   - Check cluster events:
     ```bash
     oc get events -n <namespace> --sort-by='.lastTimestamp'
     ```

   **Root Cause Categories for Operator Failures**:
   - **CatalogSource not READY** → Infrastructure/index image/registry issue → RETRY or escalate
   - **Operator not in index** ("constraints not satisfiable") → NOT A BUG - verify expected for this release
   - **InstallPlan pending** → OLM configuration issue or approval required
   - **Operator pod CrashLoopBackOff** → Product bug → File OCPBUGS
   - **Timeout waiting for operator** → May be resource constraints or slow deployment

   **For Ginkgo Test Failures** (ginkgo-test jobs):
   - Check test namespace (tests often create temporary namespaces):
     ```bash
     # List recent namespaces
     oc get namespaces --sort-by=.metadata.creationTimestamp

     # Check test resources in specific namespace
     oc get all -n <test-namespace>
     oc get events -n <test-namespace>
     ```

   - Examine failed resources mentioned in test error:
     ```bash
     # If test mentions specific resource (pod, deployment, etc.)
     oc get <resource-type> <resource-name> -n <namespace> -o yaml
     oc describe <resource-type> <resource-name> -n <namespace>
     ```

   - Check cluster-wide resources if test involves cluster operators:
     ```bash
     oc get co  # Cluster operators
     oc get nodes
     oc describe co <operator-name>
     ```

   **Common Debugging Patterns**:
   - **Pod CrashLoopBackOff**: Check pod logs for stack traces
     ```bash
     oc logs <pod-name> -n <namespace> --previous
     ```
   - **ImagePullBackOff**: Verify image pullspec and registry access
     ```bash
     oc describe pod <pod-name> -n <namespace> | grep -A 5 "Events:"
     ```
   - **Resource Not Ready**: Check conditions and events
     ```bash
     oc get <resource> -n <namespace> -o jsonpath='{.status.conditions}'
     ```

   **When to Use Live Cluster Access**:
   - ✅ Test failed with unclear error message → Check actual resource state
   - ✅ Timeout waiting for resource → Verify resource exists and check conditions
   - ✅ Operator behavior issue → Check operator pods and logs
   - ✅ Need to verify if issue is environmental vs product bug
   - ❌ Clear test automation issue → No need to check cluster
   - ❌ Infrastructure failure during cluster install → Cluster not accessible

   **Important Notes**:
   - Cluster may be torn down shortly after job completion
   - Kubeconfig access requires no authentication (public Jenkins artifacts)
   - Always clean up local kubeconfig files after analysis: `rm /tmp/kubeconfig-*`
   - Include cluster findings in analysis report if accessed

9. **Extract Error Context and Provide Actionable Analysis**:
   - **ALWAYS fetch and analyze child job console logs** for Runner and ginkgo-test failures
   - Include failed test file path and scenario/test name in analysis
   - If child job console not accessible, note the job URL and recommend manual check

   **For Cucumber (Runner job failures)**:
   - Provide feature file path and failed scenario
   - **Repository**: verification-tests or cucushift
   - **DO NOT** search in openshift-tests-private (that's for Ginkgo tests only)

   **For Ginkgo (ginkgo-test job failures)**:
   - Provide test file path, case ID, and error message
   - **Repository**: openshift-tests-private
   - **DO NOT** search in verification-tests/cucushift (those are for Cucumber tests only)

   - Include assessment of whether this is test automation issue vs product bug
   - **If applicable**: Provide instructions for accessing live cluster for deep troubleshooting

**Analysis Output Template**:

```markdown
## Jenkins Job Analysis: stage-testing

**Job Information**:
- URL: {jenkins_url}
- Console Log: {console_text_url}
- Build: #{build_number}
- Status: {SUCCESS|FAILURE|UNSTABLE} {emoji}
- Payload: {pull_spec}
- Version: {version}
- Metadata Advisory: {metadata_ad or "N/A (Konflux flow)"}

**Pipeline Analysis**:

### Stage Execution Summary
{Parse console log for all stages}

| Stage Name | Status | Notes |
|------------|--------|-------|
| {stage1} | {✅|❌|⏭️} | {brief note} |
| {stage2} | {✅|❌|⏭️} | {brief note} |
...

### Failed Stages Detail

{For each failed stage:}

#### Stage: {name}
**Status**: ❌ FAILED

**Error Messages**:
```
{Extract relevant error lines from console log}
```

**Analysis**:
{Interpret what went wrong in this stage}

**Child Jobs** (if any):
- {child_job_url}: {status}

### Child Job Results

{If child jobs detected:}
- Job 1: {url} - {✅ SUCCESS | ❌ FAILURE}
- Job 2: {url} - {✅ SUCCESS | ❌ FAILURE}
...

**Overall Assessment**:

**Root Cause**: {Identify primary reason for failure}

**Failure Category**: {Infrastructure | Product Bug | Test Automation | Configuration}

**Recommendation**: {✅ PASS | ❌ FAIL | 🔄 RETRY}

**Rationale**: {Why you're making this recommendation}

**Next Actions**:
1. {Recommended action}
2. {Recommended action}
```

### 5. Error Pattern Detection

Scan console log for common error patterns:

**Infrastructure Issues**:
- Network timeouts
- Connection refused
- DNS resolution failures
- Quota/resource exhaustion
- Platform API errors

**Product Bugs**:
- Component crashes
- Assertion failures
- Unexpected behavior
- Regression indicators

**Configuration Issues**:
- Missing environment variables
- Invalid parameters
- Permission denied
- Missing credentials

**Test Automation Issues**:
- Test framework errors
- Flaky test indicators
- Race conditions

Group similar errors and identify the most frequent patterns.

### 6. Generate Comprehensive Summary

Present findings in a clear, actionable format:

```markdown
# Jenkins Job Failure Analysis Summary

## Job Details
- **Type**: {image-consistency-check | stage-testing}
- **Build**: #{build_number}
- **Status**: {status}
- **URL**: {jenkins_url}
- **Console Log**: {console_text_url}

## Quick Assessment

{One-paragraph executive summary}

## Detailed Findings

{Include job-specific analysis from step 4}

## Error Patterns

{If errors found, group and present:}

### Pattern 1: {Error type}
- **Occurrences**: {count}
- **Example**:
  ```
  {error message excerpt}
  ```
- **Impact**: {High | Medium | Low}
- **Likely Cause**: {hypothesis}

### Pattern 2: {Error type}
...

## Decision Matrix

| Criterion | Status | Details |
|-----------|--------|---------|
| Critical failures | {✅|❌} | {summary} |
| Known issues | {✅|⚠️|❌} | {summary} |
| Infrastructure | {✅|⚠️|❌} | {summary} |
| Blocking bugs | {✅|❌} | {summary} |

## Final Recommendation

{Large, clear emoji: ✅ PASS | ❌ FAIL | ⚠️ NEEDS REVIEW | 🔄 RETRY}

**Rationale**:
{Clear explanation of recommendation}

**Confidence Level**: {High | Medium | Low}

## Required Actions

{If FAIL or NEEDS REVIEW:}
1. **Immediate**: {action}
2. **Before retry**: {action}
3. **Long-term**: {action}

{If PASS:}
No critical actions required. Monitor for:
- {Thing to watch}

## Related Resources
- Console log: {console_text_url}
- Job page: {jenkins_url}
{If bugs mentioned:}
- Related bugs: {bugzilla/jira links}
```

## Important Notes

**Console Log Access**:
- Publicly accessible, no authentication needed
- Use `/consoleText` for plain text (easier to parse)
- Can be very large - be selective in what you analyze

**Token Management Strategy**:
- Don't load entire 20K line logs
- Use `tail -n 2000` for recent output
- Use `grep` to filter for ERROR/FAIL/Exception
- Focus on relevant sections based on job type

**Job-Specific Behavior**:
- Each job has unique output format - don't expect standardization
- Parse console text directly - no JUnit XML available
- Look for job-type-specific markers and sections

**Context**:
- These jobs are part of OAR z-stream release workflow
- Triggered by commands like:
  - `oar -r 4.19.1 image-consistency-check`
  - `oar -r 4.19.1 stage-testing`
- Failures may block release approval

**Decision Guidelines**:
- **PASS**: No critical issues, or only known/waivable issues
- **FAIL**: Critical blockers (image inconsistency, unverified CVE bugs, genuine product bugs)
- **NEEDS REVIEW**: Unclear root cause, needs human judgment
- **RETRY**: Infrastructure/transient failures

## Example Usage

```bash
/ci:analyze-jenkins-failures https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/image-consistency-check/3436/
```

The command will:
1. Fetch console log from public endpoint
2. Detect it's an image-consistency-check job
3. Parse the structured output sections
4. Provide analysis and recommendation