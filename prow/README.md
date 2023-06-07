## Installation

- install this `job` command
```yaml
$ cd prow/

$ pip3 install -e .

$ pip3 list|grep job
job                      1.0.8     /Users/jianzhang/goproject/src/github.com/openshift/release-tests/prow
```
- check if it's ready
```yaml
$ job
Usage: job [OPTIONS] COMMAND [ARGS]...

  "This job tool based on Prow REST API(https://github.com/kubernetes/test-
  infra/issues/27824), used to handle those remote_api jobs.

Options:
  --version             Show the version and exit.
  --debug / --no-debug
  --help                Show this message and exit.

Commands:
  get_payloads  Check the latest payload of each version.
  get_results   Return the Prow job executed info.
  list          List the jobs which support the API call.
  run           Run a job and save results to prow-jobs.csv
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
