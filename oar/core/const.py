CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

# Logging format constants - shared across all handlers for consistency
LOG_FORMAT = "%(asctime)s: %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# cell labels
LABEL_AD_OR_SHIPMENT = "B2"
LABEL_BUILD = "B3"
LABEL_JIRA = "B4"
LABEL_OVERALL_STATUS = "B1"
LABEL_TASK_OWNERSHIP = "B8"
LABEL_TASK_BUGS_TO_VERIFY = "B9"
LABEL_TASK_IMAGE_CONSISTENCY_TEST = "B10"
LABEL_TASK_NIGHTLY_BUILD_TEST = "B11"
LABEL_TASK_SIGNED_BUILD_TEST = "B12"
LABEL_TASK_GREENWAVE_CVP_TEST = "B13"
LABEL_TASK_CHECK_CVE_TRACKERS = "B14"
LABEL_TASK_CHECK_CVE_TRACKERS_KONFLUX = "B13"
LABEL_TASK_PUSH_TO_CDN = "B15"
LABEL_TASK_PUSH_TO_CDN_KONFLUX = "B14"
LABEL_TASK_STAGE_TEST = "B16"
LABEL_TASK_STAGE_TEST_KONFLUX = "B15"
LABEL_TASK_PAYLOAD_IMAGE_VERIFY = "B17"
LABEL_TASK_PAYLOAD_IMAGE_VERIFY_KONFLUX = "B16"
LABEL_TASK_DROP_BUGS = "B18"
LABEL_TASK_DROP_BUGS_KONFLUX = "B17"
LABEL_TASK_CHANGE_AD_STATUS = "B19"
LABEL_TASK_CHANGE_AD_STATUS_KONFLUX = "B18"
LABEL_TASK_ADD_QE_APPROVAL = "B19"
LABEL_BLOCKING_TESTS = "A21"
LABEL_BLOCKING_TESTS_RELEASE = "A22"
LABEL_BLOCKING_TESTS_CANDIDATE = "A23"
LABEL_SIPPY = "A25"
LABEL_SIPPY_MAIN = "A26"
LABEL_SIPPY_AUTO_RELEASE = "A27"
LABEL_BUG_FIRST_CELL = "C8"
LABEL_ISSUES_OTHERS_COLUMN = "H"
LABEL_ISSUES_OTHERS_ROW = 8
ALL_TASKS = [
    LABEL_TASK_OWNERSHIP,
    LABEL_TASK_BUGS_TO_VERIFY,
    LABEL_TASK_IMAGE_CONSISTENCY_TEST,
    LABEL_TASK_NIGHTLY_BUILD_TEST,
    LABEL_TASK_SIGNED_BUILD_TEST,
    LABEL_TASK_GREENWAVE_CVP_TEST,
    LABEL_TASK_CHECK_CVE_TRACKERS,
    LABEL_TASK_PUSH_TO_CDN,
    LABEL_TASK_STAGE_TEST,
    LABEL_TASK_PAYLOAD_IMAGE_VERIFY,
    LABEL_TASK_DROP_BUGS,
    LABEL_TASK_CHANGE_AD_STATUS,
]

# Supported task names for OAR workflow
# Human-readable task names used in StateBox and MCP server
# Aligned with CLI commands and Konflux release flow specification
SUPPORTED_TASK_NAMES = [
    "create-test-report",
    "take-ownership",
    "update-bug-list",
    "image-consistency-check",
    "analyze-candidate-build",
    "analyze-promoted-build",
    "check-greenwave-cvp-tests",
    "check-cve-tracker-bug",
    "push-to-cdn-staging",
    "stage-testing",
    "image-signed-check",
    "drop-bugs",
    "change-advisory-status",
]

# Workflow task names tracked during release lifecycle
# Excludes one-time/optional tasks: create-test-report, update-bug-list, drop-bugs
# Used by MCP server for status tracking and Google Sheets integration
WORKFLOW_TASK_NAMES = [
    "take-ownership",
    "image-consistency-check",
    "analyze-candidate-build",
    "analyze-promoted-build",
    "check-cve-tracker-bug",
    "push-to-cdn-staging",
    "stage-testing",
    "image-signed-check",
    "change-advisory-status",
]

# overall status
OVERALL_STATUS_GREEN = "Green"
OVERALL_STATUS_RED = "Red"

# task status
TASK_STATUS_INPROGRESS = "In Progress"
TASK_STATUS_PASS = "Pass"
TASK_STATUS_FAIL = "Fail"
TASK_STATUS_NOT_STARTED = "Not Started"

# Task constants (CLI command names)
TASK_CREATE_TEST_REPORT = "create-test-report"
TASK_TAKE_OWNERSHIP = "take-ownership"
TASK_UPDATE_BUG_LIST = "update-bug-list"
TASK_IMAGE_CONSISTENCY_CHECK = "image-consistency-check"
TASK_CHECK_GREENWAVE_CVP_TESTS = "check-greenwave-cvp-tests"
TASK_CHECK_CVE_TRACKER_BUG = "check-cve-tracker-bug"
TASK_PUSH_TO_CDN_STAGING = "push-to-cdn-staging"
TASK_STAGE_TESTING = "stage-testing"
TASK_IMAGE_SIGNED_CHECK = "image-signed-check"
TASK_DROP_BUGS = "drop-bugs"
TASK_CHANGE_ADVISORY_STATUS = "change-advisory-status"

# Task to human-readable display name mapping
TASK_DISPLAY_NAMES = {
    TASK_CREATE_TEST_REPORT: "Create Test Report",
    TASK_TAKE_OWNERSHIP: "Take Ownership",
    TASK_UPDATE_BUG_LIST: "Update Bug List",
    TASK_IMAGE_CONSISTENCY_CHECK: "Image Consistency Check",
    TASK_CHECK_GREENWAVE_CVP_TESTS: "Check Greenwave CVP Tests",
    TASK_CHECK_CVE_TRACKER_BUG: "Check CVE Tracker Bug",
    TASK_PUSH_TO_CDN_STAGING: "Push to CDN Staging",
    TASK_STAGE_TESTING: "Stage Testing",
    TASK_IMAGE_SIGNED_CHECK: "Image Signed Check",
    TASK_DROP_BUGS: "Drop Bugs",
    TASK_CHANGE_ADVISORY_STATUS: "Change Advisory Status",
}

# env variables
ENV_VAR_OAR_JWK = "OAR_JWK"
ENV_VAR_JIRA_TOKEN = "JIRA_TOKEN"
ENV_VAR_SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"
ENV_VAR_SLACK_APP_TOKEN = "SLACK_APP_TOKEN"
ENV_VAR_GITLAB_TOKEN = "GITLAB_TOKEN"
ENV_VAR_GCP_SA_FILE = "GCP_SA_FILE"
ENV_APP_PASSWD = "GOOGLE_APP_PASSWD"
ENV_JENKINS_USER = "JENKINS_USER"
ENV_JENKINS_TOKEN = "JENKINS_TOKEN"
# jira status
JIRA_STATUS_CLOSED = "Closed"
JIRA_STATUS_IN_PROGRESS = "In Progress"
JIRA_STATUS_VERIFIED = "Verified"
JIRA_STATUS_ON_QA = "ON_QA"
JIRA_STATUS_DROPPED = "Dropped"
JIRA_STATUS_RELEASE_PENDING = "Release Pending"
JIRA_QE_TASK_SUMMARIES = [
    "[Fri/Mon] QE moves advisories to REL_PREP",
    "[Wed-Fri] QE does release verification",
    "[Mon-Wed] QE notifies ON_QA bugzilla owners and analyze ci failures",
]

# greenwave CVP test status
CVP_TEST_STATUS_PASSED = "PASSED"
CVP_TEST_STATUS_PENDING = "PENDING"
CVP_TEST_STATUS_FAILED = "FAILED"
CVP_TEST_STATUS_WAIVED = "WAIVED"
CVP_TEST_STATUS_INELIGIBLE = "INELIGIBLE"

# push job status
PUSH_JOB_STATUS_COMPLETE = "COMPLETE"
PUSH_JOB_STATUS_FAILED = "FAILED"
PUSH_JOB_STATUS_READY = "READY"
PUSH_JOB_STATUS_RUNNING = "RUNNING"
PUSH_JOB_STATUS_QUEUED = "QUEUED"
PUSH_JOB_STATUS_WAITING_ON_PUB = "WAITING_ON_PUB"

# advisory status
AD_STATUS_NEW_FILES = "NEW_FILES"
AD_STATUS_QE = "QE"
AD_STATUS_REL_PREP = "REL_PREP"
AD_STATUS_PUSH_READY = "PUSH_READY"
AD_STATUS_IN_PUSH = "IN_PUSH"
AD_STATUS_SHIPPED_LIVE = "SHIPPED_LIVE"
AD_STATUS_DROPPED_NO_SHIP = "DROPPED_NO_SHIP"

# advisory impetus
AD_IMPETUS_EXTRAS = "extras"
AD_IMPETUS_IMAGE = "image"
AD_IMPETUS_METADATA = "metadata"
AD_IMPETUS_MICROSHIFT = "microshift"
AD_IMPETUS_RPM = "rpm"
AD_IMPETUS_RHCOS = "rhcos"

# jenkins related properties
JENKINS_JOB_IMAGE_CONSISTENCY_CHECK = "image-consistency-check"
JENKINS_JOB_STAGE_PIPELINE = "zstreams/Stage-Pipeline"
JENKINS_JOB_STATUS_SUCCESS = "SUCCESS"
JENKINS_JOB_STATUS_IN_PROGRESS = "In Progress"
JENKINS_CLASS_PARAMS = "hudson.model.ParametersAction"
JENKINS_CLASS_STRING = "hudson.model.StringParameterValue"
JENKINS_ATTR_CLASS = "_class"
JENKINS_ATTR_PARAMS = "parameters"
JENKINS_ATTR_NAME = "name"
JENKINS_ATTR_VALUE = "value"
JENKINS_ATTR_IS_IN_PROGRESS = "inProgress"
JENKINS_ATTR_RESULT = "result"
JENKINS_QUEUE_ITEM_ATTR_EXECUTABLE = "executable"
JENKINS_QUEUE_ITEM_ATTR_BLOCKED = "blocked"
JENKINS_QUEUE_ITEM_ATTR_URL = "url"
JENKINS_PARAM_PAYLOAD_URL = "PAYLOAD_URL"
JENKINS_PARAM_PULL_SPEC = "PULL_SPEC"
