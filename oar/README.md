# OAR (Openshift Automatic Release)
## OAR Commandline Tool (CLI)
### Install
```
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
$ oar -r $release-version $sub-cmd -h
```
### Examples
- Common functions
  - release-version: e.g. 4.13.6
  - every command is related to QE task in checklist, every task status will be updated to `In Progress` when execution is started, and the tasks tatus will be updated to `Pass` or `Fail` when execution is completed. If any task is failed, `Overall Status` will be updated to `Green` or `Red`
1. Create test report for z-stream release in spreadsheet, you can get new report url when execution is completed. new report contains advisory, candidate nightly build, ART JIRA ticket, QE checklist, ONQA bugs etc.
```
$ oar -r $release-version create-test-report
```
2. This command will help us to take ownership of advisory and JIRA subtasks created by ART team. just need to provide owner email as command option
```
$ oar -r $release-version take-ownership -e foo@bar.com
```
3. This command needs to be ran multiple times, it can update ONQA bugs with latest status in test report, e.g. Verified/Closed, and append newly attached bugs to the report as well, slack notification will be sent out to QA Contacts finally
```
$ oar -r $release-version update-bug-list
```
4. This command will trigger image-consistency-check jenkins job to verify images in release payload, build number will be returned with first run, the build number can be used as option for subsequent run to check jenkins job status
```
$ oar -r $release-version image-consistency-check
$ oar -r $release-version image-consistency-check -n 123
```
5. This command will check all the Greenwave CVP tests of all advisories, expected result is all the tests are `PASSED/WAVIED`, if any of the tests is failed, you can get test id and corresponding advisory number from the output, you can trigger `Refetch` for it, if the test is still failed after refetch, contact CVP team via Google Spaces [CVP]
```
$ oar -r $release-version check-greenwave-cvp-tests
```
6. This command will call `rh-elliott` to check if any CVE tracker bug is missed for current release. it will send out slack notification to ART team if any bug found
```
$ oar -r $release-version check-cve-tracker-bug
```
7. If all the Greenwave CVP tests are `PASSED/WAIVED`, this command can trigger push job for default target `stage`, it will not interrupt existing running jobs
```
$ oar -r $release-version push-to-cdn-staging
```
8. This command will trigger stage pipeline to do stage testing, build number will be returned with first run, the build number can be used as option for subsequent run to check jenkins job status
```
$ oar -r $release-version stage-testing
$ oar -r $release-version stage-testing -n 123
```
9. This command will verify whether payload is well-signed. it can get digest of stable build automatically and check out whether it can be found on mirror site
```
$ oar -r $release-version image-signed-check
```
10. This command will check all the not verified bugs from advisories, if any bug is `Critical` or `Blocker` or `Customer Case` it is must-verify bug, need to confirm with bug owner, slack notification will be sent out. the rest of the bugs will be dropped automatically
```
$ oar -r $release-version drop-bugs
```
11. This command will change advisory status e.g. REL_PREP, and close QE related JIRA subtasks
```
$ oar -r $release-version change-advisory-status
```