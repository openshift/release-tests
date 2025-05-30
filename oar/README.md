# OAR (Openshift Automatic Release)
## OAR Commandline Tool (CLI)
### Install
```
python3 -m pip install --upgrade pip
git clone git@github.com:openshift/release-tests.git
cd release-tests
pip3 install -e .
```
### Configuration
  - We need to export some system environment variables, you can find shared variables from https://vault.bitwarden.com/, search *openshift-qe-trt-env-vars* <br>
  Below variables can be customized by user
  - JIRA token, used to communicate with jira system. [How to create personal access token](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html#UsingPersonalAccessTokens)
    ```
    export JIRA_TOKEN=xxx
    ```
  - Jenkins user and token, used to trigger and get jenkins job status, [How to create jenkins api token](https://www.jenkins.io/blog/2018/07/02/new-api-token-system/#about-api-tokens)
    ```
    export JENKINS_USER=<$your-mail-id>
    export JENKINS_TOKEN=xxx
    ```
  - Kerberos ticket is required to access Errata Tool
```
kinit $kid@$domain
```
- Bugzilla login api-key, the credentials are cached to ~/.config/python-bugzilla/bugzillarc
```
echo 'xxx' | bugzilla login --api-key
```
   - According to security policy, sensitive data in config file should NOT be plain text, we use JWE to encrypt `config_store.json`, encryption key should be exported by var `OAR_JWK`, value can be found in above bitwarden item
### Command help
```
$ oar -h
Usage: oar [OPTIONS] COMMAND [ARGS]...

Options:
  -V, --version
  -r, --release TEXT  z-stream releaes version  [required]
  -v, --debug         enable debug logging
  -h, --help          Show this message and exit.

Commands:
  create-test-report         Create test report for z-stream release
  take-ownership             Take ownership for advisory and jira subtasks
  update-bug-list            Update bug status listed in report, update...
  image-consistency-check    Check if images in advisories and payload...
  check-greenwave-cvp-tests  Check Greenwave CVP test results for all...
  check-cve-tracker-bug      Check if there is any missed CVE tracker bug
  push-to-cdn-staging        Trigger push job for cdn stage targets
  stage-testing              Trigger stage pipeline test
  image-signed-check         Check payload image is well signed
  drop-bugs                  Drop bugs from advisories
  change-advisory-status     Change advisory status e.g.
```
### Sub command help
```
$ oar $sub-cmd -h
```
### Examples
- Common functions
  - release-version: e.g. 4.13.6
  - every command is related to QE task in checklist, every task status is updated to `In Progress` when execution is started, and the task status is updated to `Pass` or `Fail` when execution is completed. If any task fails, `Overall Status` is updated to `Red`
1. Create test report for z-stream release in spreadsheet, you can get new report url when execution is completed. New report contains advisory, candidate nightly build, ART JIRA ticket, QE checklist, ONQA bugs, etc.
```
$ oar -r $release-version create-test-report
```
2. This command helps us to take ownership of an advisory and JIRA subtasks created by ART team. Just need to provide owner email as command option
```
$ oar -r $release-version take-ownership -e foo@bar.com
```
3. This command needs to be run multiple times, it updates ONQA bugs with the latest status in test report, e.g. Verified/Closed, and appends newly attached bugs to the report as well. Slack notification is sent out to QA Contacts
```
$ oar -r $release-version update-bug-list
```
4. This command triggers image-consistency-check jenkins job to verify images in release payload. The build number is returned with the first run. The build number can be used as an option for subsequent run to check jenkins job status
```
$ oar -r $release-version image-consistency-check
$ oar -r $release-version image-consistency-check -n 123
```
5. This command checks all Greenwave CVP tests of all advisories. Expected result is that all tests finish with status `PASSED/WAIVED`. If any of the tests failed, you can trigger `Refetch` with the test id and corresponding advisory number. You can get those parameters from this command output. If the test is still failing after refetch, contact CVP team via Google Spaces [CVP]
```
$ oar -r $release-version check-greenwave-cvp-tests
```
6. This command calls `rh-elliott` to check if any CVE tracker bug is missed for current release. It sends out a Slack notification to ART team if any bug found
```
$ oar -r $release-version check-cve-tracker-bug
```
7. If all Greenwave CVP tests are `PASSED/WAIVED`, this command triggers push job for default target `stage`. It does not interrupt existing running jobs
```
$ oar -r $release-version push-to-cdn-staging
```
8. This command triggers stage pipeline to do stage testing. Build number is returned with the first run. The build number can be used as option for subsequent run to check jenkins job status
```
$ oar -r $release-version stage-testing
$ oar -r $release-version stage-testing -n 123
```
9. This command verifies whether payload is well-signed. It gets digest of stable build automatically and checks out whether it can be found on mirror site
```
$ oar -r $release-version image-signed-check
```
10. This command checks all not verified bugs from advisories. If any bug is `Critical`, `CVE Tracker` or `Customer Case`, it is a "high severity" bug. These bugs need to be confirmed with a bug owner, a Slack notification is sent out. The rest of the bugs are dropped automatically
```
$ oar -r $release-version drop-bugs
```
11. This command changes advisory status to, e.g. REL_PREP, and close QE related JIRA subtasks. It also checks blocking secalerts for RHSA advisory. In case of failure, it throws appropriate error message
```
$ oar -r $release-version change-advisory-status
```
