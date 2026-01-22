# Image Consistency Check

## Overview

The Image Consistency Check is a validation tool that verifies all container images in an OpenShift release payload are consistent with the images declared in the shipment data (GitLab Merge Request). This ensures the integrity of container images before they are shipped to customers.

## Process flow

The Image Consistency Check compares images between the release payload and shipment MR, and for each payload image:

1. Extracts image metadata (digest, list digest, VCS reference) from the payload.

2. Extracts image metadata from all components in the shipment MR.

3. Checks if the payload image exists in the shipment by comparing identifiers.

    - If the image digest, list digest, or VCS reference matches any shipment component, the image passes.

4. If not found in shipment, checks the Red Hat Container Catalog.

    - If the image digest is found in the catalog, the image passes (it was released in a previous shipment).

5. If the image is not found in either location, the check fails.

    - The tool searches for images with the same name to help identify version mismatches.

6. Reports the overall result: all payload images must pass for the check to succeed.

### Fetching payload data

The payload data is fetched using the `oc adm release info` command:

```bash
oc adm release info --pullspecs <payload-url> -o json
```
- Example payload URL format: `quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64`
- Extracted from payload:
   - `metadata.version` - The release version (e.g., `4.16.55`)
   - `references.spec.tags[]` - List of all images in the payload, each containing:
      - `name` - Image name (e.g., `cluster-version-operator`, ...)
      - `from.name` - Image pullspec (e.g., `quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:...`, ...)

### Fetching shipment data

The shipment data is fetched from a GitLab Merge Request using the GitLab API from GitLab project URL: `https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data`. The process is:

1. Fetches the MR by ID from the shipment data project.

2. Extracts the version from the MR title (pattern: `Shipment for X.Y.Z`).

3. Iterates through all changed YAML files in the MR.

4. For each YAML file, reads the content from the MR source branch.

5. Parses the YAML and extracts each component from `shipment.snapshot.spec.components[]`.
   - `name` - Component name (e.g., `ose-4-17-openshift-enterprise-cli`, ...)
   - `containerImage` - Image pullspec (e.g., `quay.io/redhat-user-workloads/ocp-art-tenant/art-images@sha256:...`, ...)

### Fetching image metadata

For each image pullspec (from all payload images and shipment components), detailed metadata is fetched using:

```bash
oc image info --filter-by-os linux/amd64 -o json --insecure=true <pullspec>
```

- Extracted from image metadata:
   - `digest` - SHA256 digest of the image (e.g., `sha256:abc123...`)
   - `listDigest` - Multi-architecture manifest list digest
   - `config.config.Labels` - Container labels containing:
      - `io.openshift.build.commit.id` - OpenShift build commit ID
      - `vcs-ref` - VCS (git) reference/commit hash
      - `name` - Image name from labels
      - `version` - Version string
      - `release` - Release string

### Skipped images

The following OS-level images are automatically excluded from consistency checking:

- `machine-os-content`
- `rhel-coreos` (including versioned variants like `rhel-coreos-8`, `rhel-coreos-9`, ...)
- `rhel-coreos-extensions` (including versioned variants like `rhel-coreos-8-extensions`, `rhel-coreos-9-extensions`, ...)

## Image matching criteria

Images are considered matching if any of these conditions are true:

- **List Digest Match** - Both images have the same multi-architecture manifest list digest
- **Digest Match** - Both images have the same SHA256 digest
- **VCS Reference Match** - Both images were built from the same git commit

## CLI Usage

### Running Image consistency check locally:

```bash
oarctl image-consistency-check --payload-url PAYLOAD_URL --mr-id MERGE_REQUEST_ID
```
#### Options
- `-p`, `--payload-url TEXT`
   - Payload URL (e.g., `quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64`)
- `-m`, `--mr-id INTEGER`
   - Shipment merge request ID from the `ocp-shipment-data` GitLab project (e.g., `292`)
- `--help`
   - Shows the help message and exits.

### Running Image consistency check Prow job:

```bash
job run_image_consistency_check --payload-url PAYLOAD_URL --mr-id MERGE_REQUEST_ID
```
#### Options
- `-p`, `--payload-url TEXT`
   - Payload URL (e.g., `quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64`)
- `-m`, `--mr-id INTEGER`
   - Shipment merge request ID from the `ocp-shipment-data` GitLab project (e.g., `292`)
- `--help`
   - Shows the help message and exits.

## Links
- Implementation links
  - [Image Consistency Check source code](https://github.com/openshift/release-tests/tree/master/oar/image_consistency_check)
  - [Image Consistency Check command source code](https://github.com/openshift/release-tests/blob/master/oar/cli/cmd_controller_group.py)
  - [Image Consistency Check job run command source code](https://github.com/openshift/release-tests/blob/master/prow/job/job.py)
  - [Image Consistency Check Step registry](https://github.com/openshift/release/tree/master/ci-operator/step-registry/release-qe-tests/image-consistency-check)
  - [Image Consistency Check job configuration](https://github.com/openshift/release/blob/master/ci-operator/jobs/openshift/release-tests/openshift-release-tests-master-periodics.yaml)
- Job Links
  - [Image Consistency Check Prow job](https://prow.ci.openshift.org/?job=periodic-ci-openshift-release-tests-master-image-consistency-check)
  - [(Deprecated) Image Consistency Check Jenkins job](https://jenkins-csb-openshift-qe-mastern.dno.corp.redhat.com/job/image-consistency-check/)

## Implementation Notes

Environment variables passed to the Prow job must have the `MULTISTAGE_PARAM_OVERRIDE_` prefix to be available in the [step registry script](https://github.com/openshift/release/blob/master/ci-operator/step-registry/release-qe-tests/image-consistency-check/release-qe-tests-image-consistency-check-commands.sh):
- `MULTISTAGE_PARAM_OVERRIDE_PAYLOAD_URL` - The payload URL
- `MULTISTAGE_PARAM_OVERRIDE_MERGE_REQUEST_ID` - The shipment merge request ID
