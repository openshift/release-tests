# OAR (Openshift Automatic Release)
## OAR Commandline Tool (CLI)
- Install
```
clone git@github.com:openshift/release-tests.git
cd release-tests
pip3 install -e .
```
- Configuration
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
  
- Command help
```
oar -h
Usage: oar [OPTIONS] COMMAND [ARGS]...

Options:
  -V, --version
  -r, --release TEXT  z-stream releaes version  [required]
  -v, --debug         enable debug logging
  -h, --help          Show this message and exit.

Commands:
  change-advisory-status     Change advisory status e.g.
  check-cve-tracker-bug      Check if there is any missed CVE tracker bug
  check-greenwave-cvp-tests  Check Greenwave CVP test results for all...
  create-test-report         Create test report for z-stream release
  drop-bugs                  Drop bugs from advisories
  image-consistency-check    Check if images in advisories and payload...
  image-signed-check         Check payload image is well signed
  push-to-cdn-staging        Trigger push job for cdn stage targets
  stage-testing              Trigger stage pipeline test
  take-ownership             Take ownership for advisory and jira subtasks
  update-bug-list            Update bug status listed in report, update...
```
- Sub command help
```
oar -r $release-version $sub-cmd -h

oar -r 4.12.25 image-consistency-check -h
Usage: oar image-consistency-check [OPTIONS]

  Check if images in advisories and payload are consistent

Options:
  -n, --build_number INTEGER  provide build number to get job status
  -h, --help                  Show this message and exit.
```
