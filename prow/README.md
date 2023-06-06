## Installation

- install this `job` command
```yaml
$ cd prow/
$ pip install -e .
Defaulting to user installation because normal site-packages is not writeable
Obtaining file:///Users/jianzhang/goproject/src/github.com/openshift/release-tests/prow
  Preparing metadata (setup.py) ... done
Requirement already satisfied: semver in /Users/jianzhang/Library/Python/3.10/lib/python/site-packages (from release-tests==1.0.2) (3.0.0)
Requirement already satisfied: requests in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from release-tests==1.0.2) (2.27.1)
Requirement already satisfied: pyyaml in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from release-tests==1.0.2) (6.0)
Requirement already satisfied: click in /Users/jianzhang/Library/Python/3.10/lib/python/site-packages (from release-tests==1.0.2) (8.0.1)
Requirement already satisfied: certifi>=2017.4.17 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.2) (2022.12.7)
Requirement already satisfied: urllib3<1.27,>=1.21.1 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.2) (1.26.9)
Requirement already satisfied: charset-normalizer~=2.0.0 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.2) (2.0.12)
Requirement already satisfied: idna<4,>=2.5 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.2) (3.3)
Installing collected packages: release-tests
  Running setup.py develop for release-tests
Successfully installed release-tests
```
- check if it's ready
```yaml
$ job
Usage: job [OPTIONS] COMMAND [ARGS]...

Options:
  --debug / --no-debug
  --help                Show this message and exit.

Commands:
  get_payloads  Check the latest payload of each version.
  get_results   Return the Prow job executed info.
  run           Run a Prow job via API call.
  run_required  Run required jobs from a file
```
- export the necessary Prow and Github tokens
```console
$ export APITOKEN=`cat token/xxx`
$ export GITHUB_TOKEN=`cat token/xxx`
``` 
- An example to run a periodic job on a specific payload.
Once done, it will return the Job ID, creation time stamp, and the triggered job link.
```console
$ job run periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 --payload quay.io/openshift-release-dev/ocp-release:4.11.0-assembly.art6883.2
Debug mode is off
Returned job id: 2ff60863-b9f1-40ca-9eb1-caefb6d44dff
2ff60863-b9f1-40ca-9eb1-caefb6d44dff 2023-06-06T07:22:17Z https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14/1665982424904896512 
```
