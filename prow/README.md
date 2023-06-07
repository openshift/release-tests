### Installation

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
  run           Run a job and save results to /tmp/prow-jobs.csv
  run_required  Run required jobs from a file
```

### Run job

- Get the Prow token

Login https://console-openshift-console.apps.ci.l2s4.p1.openshiftapps.com/ and then, click **your-personal-account** -> `Copy login command` -> `Display Token`, you will get it like below:
```console
oc login --token=sha256~<your-prow-token> --server=https://api.ci.l2s4.p1.openshiftapps.com:6443
```

- Get the Github token

Click your personal Github account -> `Settings` -> `Developer settings` -> `Personal access tokens (classic)` -> `Create new token`, you will get it like:
```console
ghp_xxx
```

- Set token ENVs
```console
$ export APITOKEN=<your-prow-token>
$ export GITHUB_TOKEN=<your-github-token>
``` 

- An example to run a job on a specific payload for **e2e test**.
```console
$ job run periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 --payload quay.io/openshift-release-dev/ocp-release:4.11.0-assembly.art6883.2
Debug mode is off
Returned job id: 2ff60863-b9f1-40ca-9eb1-caefb6d44dff
2ff60863-b9f1-40ca-9eb1-caefb6d44dff 2023-06-06T07:22:17Z https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14/1665982424904896512 
```

- An example to run a upgrade job on specific payloads for **upgrade test**.
```console
MacBook-Pro:~ jianzhang$ job run --upgrade_to quay.io/openshift-release-dev/ocp-release:4.11.0-assembly.art6883.3 periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 
Debug mode is off
Returned job id: 773f7076-ecc0-433f-aae1-e4dd09bcdf25
periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 None 773f7076-ecc0-433f-aae1-e4dd09bcdf25 2023-06-07T04:09:33Z https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14/1666296310531100672
``` 
or
```console
MacBook-Pro:~ jianzhang$ job run --upgrade_to quay.io/openshift-release-dev/ocp-release:4.11.0-assembly.art6883.3 periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 --upgrade_from registry.ci.openshift.org/ocp/release:4.10.0-0.nightly-2023-06-05-210256
Debug mode is off
Returned job id: 3ebe0a6e-ea5c-4c96-9ca4-295074f9eaa3
periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14 None 3ebe0a6e-ea5c-4c96-9ca4-295074f9eaa3 2023-06-07T06:15:10Z https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-4.11-upgrade-from-stable-4.10-gcp-ipi-disconnected-private-p2-f14/1666327924111839232
```
