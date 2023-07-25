# OAR (Openshift Automatic Release)
## OAR Commandline Tool (CLI)
- Install
```
git clone git@github.com:openshift/release-tests.git
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
- Sub command help
```
oar -r $release-version $sub-cmd -h

- For example
$oar -r 4.13.6 create-test-report -h
Usage: cli create-test-report [OPTIONS]
  Create test report for z-stream release
Options:
  -h, --help  Show this message and exit.
note: the command will create a 4.13.6 sheet from template sheet.

$oar -r 4.13.6 take-ownership -h
Usage: cli take-ownership [OPTIONS]
  Take ownership for advisory and jira subtasks
Options:
  -e, --email TEXT  email address of the owner, if option is not set, will use
                    default owner setting instead
  -h, --help        Show this message and exit.

$ oar -r 4.13.6 update-bug-list -h
Usage: cli update-bug-list [OPTIONS]
Update bug status listed in report, update existing bug status and append new ON_QA bug
Options:
  -h, --help  Show this message and exit.
note: the command will update bug latest status in related sheet.

$ oar -r 4.13.6 image-consistency-check -h
Usage: cli image-consistency-check [OPTIONS]
  Check if images in advisories and payload are consistent
Options:
  -n, --build_number INTEGER  provide build number to get job status
  -h, --help                  Show this message and exit.
note: if add -n option, will check Stage-Pipeline job result.

$oar -r 4.13.6 check-greenwave-cvp-tests -h
Usage: cli check-greenwave-cvp-tests [OPTIONS]
  Check Greenwave CVP test results for all advisories
Options:
  -h, --help  Show this message and exit.

$oar -r 4.13.6 check-cve-tracker-bug -h
Usage: cli check-cve-tracker-bug [OPTIONS]
  Check if there is any missed CVE tracker bug
Options:
  -h, --help  Show this message and exit.
note: the command will list cve bugs missed attached in advisories.

$oar -r 4.13.6 push-to-cdn-staging -h
Usage: cli push-to-cdn-staging [OPTIONS]
  Trigger push job for cdn stage targets
Options:
  -h, --help  Show this message and exit.

$oar -r 4.13.6 stage-testing -h
Usage: cli stage-testing [OPTIONS]
  Trigger stage pipeline test
Options:
  -n, --build_number INTEGER  provide build number to get job status
  -h, --help                  Show this message and exit.
notes: if add -n options, will return Stage-Pipeline job result.

$oar -r 4.13.6 image-signed-check -h
Usage: cli image-signed-check [OPTIONS]
  Check payload image is well signed
Options:
  -h, --help  Show this message and exit.

$oar -r 4.13.6 drop-bugs -h
Usage: cli drop-bugs [OPTIONS]
  Drop bugs from advisories
Options:
  -h, --help  Show this message and exit.

$oar -r 4.13.6 change-advisory-status -h
Usage: cli change-advisory-status [OPTIONS]
  Change advisory status e.g. QE, REL_PREP
Options:
  -s, --status TEXT  Valid advisory status, default is REL_PREP
  -h, --help         Show this message and exit.
