# ERT (Errata Reliability Team)

ERT makes QE tasks of z-stream releases more efficient by improving test coverage and automating processes. This frees up release leaders, managers, and component teams from repetitive z-stream release tasks.

## Features

- Automates interactions with multiple systems (Errata, Jira, Google Docs, Slack, Jenkins)
- Provides Prow job execution capabilities
- Comprehensive testing framework
- CLI interface for common release tasks

## Tools

### OAR (Openshift Automatic Release)

The OAR tool provides CLI commands for:

- Advisory management (create, update, check status)
- Bug tracking and management
- Test report generation
- Image consistency and signing checks
- Notification handling
- Integration with Jenkins for CI/CD

### Prow Jobs

The QE job controller system handles:

- Running and monitoring Prow jobs via Gangway
- Artifact collection and analysis
- Test result processing
- Job selection and filtering

## Installation

1. Clone this repository:

```bash
git clone https://github.com/openshift/release-tests.git
cd release-tests
```

2. Install dependencies:

```bash
pip3 install -e .
```

## Command Samples

Here are some common OAR command examples:

```bash
# Create test report
oar -r [release] create-test-report

# Change advisory status
oar -r [release] change-advisory-status

# Update bug list and notify the QA Contact
oar -r [release] update-bug-list

# Update bug list without sending notifications
oar -r [release] update-bug-list --no-notify

# Enable debug logging (global option -v comes before -r)
oar -v -r [release] update-bug-list
...
```
More details can be found in [oar/README.md](./oar/README.md)

Prow job command examples:

```bash
# Run specific Prow job
job run [job_name] --payload $image_pullspec

# Check job results
job get_results [job_id]

# Start job controller
jobctl start-controller -r [release] --nightly --arch [amd64|arm64|multi|ppc64le|s390x]

# Start test results aggregator
jobctl start-aggregator --arch [amd64|arm64|multi|ppc64le|s390x]
```

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.
