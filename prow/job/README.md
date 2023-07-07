## how to launch multiple Prow CI jobs
To help launch multiple ProwCI runs, we run the command

```
python run_jobs_from_yaml.py 4_11_jobs.yaml
```
This script calls the script `job.py` to launch runs via the Prow REST API
here.  To run the script `job.py`, there are 3 parameters needed to be set.
```
## PROW API tokens
# https://console-openshift-console.apps.ci.l2s4.p1.openshiftapps.com/
export APITOKEN=`cat ~/tokens/pull_secret_token`
export GITHUB_TOKEN=`cat ~/tokens/github_token`
export GANGWAY_API=https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com
```
the `pull_secret_token` is retrived by going to ` https://console-openshift-console.apps.ci.l2s4.p1.openshiftapps.com`