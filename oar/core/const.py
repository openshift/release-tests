CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

# cell labels
LABEL_ADVISORY = "B2"
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
LABEL_TASK_PUSH_TO_CDN = "B15"
LABEL_TASK_STAGE_TEST = "B16"
LABEL_TASK_PAYLOAD_IMAGE_VERIFY = "B17"
LABEL_TASK_DROP_BUGS = "B18"
LABEL_TASK_CHANGE_AD_STATUS = "B19"
LABEL_BUG_FIRST_CELL = "C8"

# overall status
OVERALL_STATUS_GREEN = "Green"
OVERALL_STATUS_RED = "Red"

# task status
TASK_STATUS_INPROGRESS = "In Progress"
TASK_STATUS_PASS = "Pass"
TASK_STATUS_FAIL = "Fail"
TASK_STATUS_NOT_STARTED = "Not Started"

# env variables
ENV_VAR_JIRA_TOKEN = "JIRA_TOKEN"
ENV_VAR_SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"
ENV_VAR_SLACK_APP_TOKEN = "SLACK_APP_TOKEN"
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
AD_STATUS_QE = "QE"
AD_STATUS_REL_PREP = "REL_PREP"
AD_STATUS_NEW_FILES = "NEW_FILES"

#release url
ENV_RELEASE_URL="RELEASE_URL"
ENV_SIGNATURE_URL="SIGNATURE_URL"
