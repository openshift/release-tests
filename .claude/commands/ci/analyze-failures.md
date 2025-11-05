---
description: Analyze OpenShift CI job failures (dispatcher for Prow and Jenkins jobs)
---

You are helping the user analyze failures from an OpenShift CI job run.

The user has provided a job URL: {{args}}

## Your Task

Detect whether this is a Prow job or Jenkins job based on URL patterns, then invoke the appropriate specialized analysis command.

## Detection Rules

### Prow Job Indicators:
- URL contains `/view/gs/` AND `/logs/`
- OR domain contains `deck-ci` or `prow.ci.openshift.org`

**Example Prow URLs**:
```
https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.20-automated-release-aws-ipi-f999/1979765746749673472
https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/periodic-ci-openshift-release-master-ci-4.17-e2e-gcp/1234567890
```

### Jenkins Job Indicators:
- URL contains `/job/`
- AND domain contains `jenkins`
- AND path ends with a numeric build number

**Example Jenkins URLs**:
```
https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/image-consistency-check/3436/
https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/zstreams/job/Stage-Pipeline/1413/
```

## Action to Take

**Step 1**: Analyze the provided URL against the detection rules above.

**Step 2**: Based on detection result:

**If Prow job detected**:
- Immediately invoke the SlashCommand tool with command: `/ci:analyze-prow-failures {{args}}`
- Do NOT provide any other response - just invoke the command

**If Jenkins job detected**:
- Immediately invoke the SlashCommand tool with command: `/ci:analyze-jenkins-failures {{args}}`
- Do NOT provide any other response - just invoke the command

**If URL type cannot be determined**:
- Respond to the user:
  ```
  I couldn't automatically detect the job type from the URL: `{{args}}`

  Please specify which type of CI job this is:
  1. **Prow job** - OpenShift CI Prow jobs (from qe-private-deck or prow.ci.openshift.org)
  2. **Jenkins job** - Jenkins jobs (image-consistency-check, stage-testing, etc.)

  Or provide a more complete URL if the one given was truncated.
  ```

## Important Notes

- Do NOT analyze the job yourself - always dispatch to the specialized command
- The specialized commands (`/ci:analyze-prow-failures` and `/ci:analyze-jenkins-failures`) contain the actual analysis logic
- Your only job is to detect the job type and route to the correct command