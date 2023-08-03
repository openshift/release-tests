import logging
from oar.core.config_store import ConfigStore
from oar.core.exceptions import JiraException
from oar.core.const import *
from jira import JIRA
from jira import Issue
from jira.exceptions import JIRAError

logger = logging.getLogger(__name__)


class JiraManager:
    """
    Jira Manager is used to communicate with jira system to get/update/create jira issues
    """

    def __init__(self, cs: ConfigStore):
        self._cs = cs
        token = self._cs.get_jira_token()
        if not token:
            raise JiraException("cannot find auth token from env var JIRA_TOKEN")

        self._svc = JIRA(server=self._cs.get_jira_server(), token_auth=token)
        try:
            self._svc.issue(self._cs.get_jira_ticket())
        except JIRAError as je:
            if je.status_code == 401 or je.status_code == 403:
                raise JiraException("invalid token") from je
            else:
                raise JiraException("cannot talk to jira server") from je

    def get_issue(self, key):
        """
        Query server get jira issue object

        Args:
            key (str): JIRA issue key

        Returns:
            JiraIssue: object of JiraIssue
        """
        try:
            issue = self._svc.issue(key)
        except JIRAError as je:
            raise JiraException("get jira issue failed") from je

        return JiraIssue(issue)

    def create_issue(self, **issue_dict):
        """
        Create jira issue

        create_issue(
            project="MyProject",
            summary="dummy summary from jira manager",
            description="dummy description from jira manager",
            issuetype={"name": "Bug"},
        )

        Raises:
            JiraException: error when communicate with jira server

        Returns:
            JiraIssue: JiraIssue
        """

        try:
            issue = self._svc.create_issue(fields=issue_dict)
        except JIRAError as je:
            raise JiraException("create jira issue failed") from je

        return JiraIssue(issue)

    def transition_issue(self, key, status):
        """
        Change issues status

        Args:
            key (str): issue key
            status (str): status e.g. Closed

        Raises:
            JiraException: error when communicate with jira server
        """
        logger.info(f"updating jira issue {key} status ...")

        try:
            self._svc.transition_issue(key, transition=status)
        except JIRAError as je:
            raise JiraException("transition issue failed") from je

        logger.info(f"jira issue {key} is updated to {status}")

    def assign_issue(self, key, contact):
        """
        Assign issue to contact

        Args:
            key (str): issue key
            contact (str): email address

        Raises:
            JiraException: error when communicate with jira server
        """
        logger.info(f"updating jira issue {key} assignee")

        try:
            self._svc.assign_issue(key, contact)
        except JIRAError as je:
            raise JiraException(f"assign issue {key} to {contact} failed") from je

        logger.info(f"jira issue {key} assignee is updated to {contact}")

    def get_sub_tasks(self, parent_key):
        """
        Get jira subtasks by parent key

        Args:
            partent_key (str): parent issue key

        Returns:
            []JiraIssue: jira subtask list
        """
        subtasks = []
        if not parent_key:
            return subtasks

        try:
            parent = self._svc.issue(parent_key)
            tasks = parent.fields.subtasks
            if tasks and len(tasks) > 0:
                for t in tasks:
                    issue = JiraIssue(self._svc.issue(t.key))
                    subtasks.append(issue)
                    logger.info(
                        f"found subtask {issue.get_key()} - {issue.get_summary()}"
                    )
        except JIRAError as je:
            raise JiraException(f"get subtasks of {parent_key} failed") from je

        return subtasks

    def change_assignee_of_qe_subtasks(self):
        """
        Change assignee of all QE subtasks from ART ticket

        Returns:
            updated_tasks([]): jira keys of updated subtasks
        """
        updated_tasks = []
        subtasks = self.get_sub_tasks(self._cs.get_jira_ticket())
        if len(subtasks):
            for st in subtasks:
                if st.get_summary() in JIRA_QE_TASK_SUMMARIES:
                    self.assign_issue(st.get_key(), self._cs.get_owner())
                    updated_tasks.append(st.get_key())
                    if st.get_summary().startswith(
                        "[Wed-Fri]"
                    ) or st.get_summary().startswith("[Mon-Wed]"):
                        self.transition_issue(st.get_key(), JIRA_STATUS_IN_PROGRESS)

        return updated_tasks

    def close_qe_subtasks(self):
        """
        Close all QE subtasks under ART story
        """
        subtasks = self.get_sub_tasks(self._cs.get_jira_ticket())
        if len(subtasks):
            for st in subtasks:
                if st.get_summary() in JIRA_QE_TASK_SUMMARIES:
                    self.transition_issue(st.get_key(), JIRA_STATUS_CLOSED)

    def add_comment(self, key, comment):
        """
        Add comment for jira issue

        Args:
            comment (str): description
        """
        try:
            self._svc.add_comment(key, comment)
        except JIRAError as je:
            raise JiraException(f"add comment for jira issue {key} failed") from je


class JiraIssue:
    """
    Wrapper class to hold jira.issue
    """

    def __init__(self, issue: Issue):
        self._issue = issue

    def get_key(self):
        """
        Get issue key
        """
        return self._issue.key

    def get_qa_contact(self):
        """
        Get issue field `QA Contact`
        """
        field = self._issue.fields.customfield_12315948
        return field.emailAddress if field else "Unknown"

    def get_status(self):
        """
        Get issue field `Status`
        """
        return self._issue.fields.status.name

    def get_assignee(self):
        """
        Get issue field `Assignee`, email address
        """
        return self._issue.fields.assignee.emailAddress

    def get_labels(self):
        """
        Get issue labels
        """
        return self._issue.fields.labels

    def get_priority(self):
        """
        Get issue field `Priority`, e.g. Critical, Blocker
        """
        return self._issue.fields.priority.name

    def get_release_blocker(self):
        """
        Get issue field `Release Blocker`, e.g. None, Rejected, Approved, Proposed
        """
        release_blocker = "None"
        if self._issue.fields.customfield_12319743:
            release_blocker = self._issue.fields.customfield_12319743.value
        return release_blocker

    def get_summary(self):
        """
        Get issue summary
        """
        return self._issue.fields.summary

    def get_sfdc_case_counter(self):
        """
        Get issue field `SFDC Cases Counter`
        """
        return self._issue.fields.customfield_12313440

    def get_sfdc_case_links(self):
        """
        Get issue field `SFDC Cases Links`
        """
        return self._issue.fields.customfield_12313441

    def is_critical_issue(self):
        """
        Check whether the issue is critical

        - Check issue field [Priority] is Critical or Blocker
        - Check issue has label [TestBlocker]
        - Check issue field [Release Blocker] is Approved or Proposed
        """
        priority = self.get_priority()
        labels = self.get_labels()
        release_blocker = self.get_release_blocker()

        priority_check = priority in ["Critical", "Blocker"]
        label_check = "TestBlocker" in labels
        release_blocker_check = release_blocker in ["Approved", "Proposed"]

        return priority_check or label_check or release_blocker_check

    def is_customer_case(self):
        """
        Check whether the issue is customer case

        - Check issue field [SFDC Cases Counter] > 0
        - Check issue field [SFDC Cases Links] is not empty
        """
        sfdc_case_counter = self.get_sfdc_case_counter()
        sfdc_case_links = self.get_sfdc_case_links()

        return float(sfdc_case_counter) > 0 or sfdc_case_links

    def is_cve_tracker(self):
        """
        Check whether the issue is CVE tracker bug

        - Check issue labels, label starts with CVE
        - Check issue summary, starts with CVE
        """
        summary = self.get_summary()
        labels = self.get_labels()

        label_check = False
        for label in labels:
            if label.startswith("CVE"):
                label_check = True
                break

        return summary.startswith("CVE") or label_check

    def is_verified(self):
        """
        Bug status is `Verified`

        Returns:
            bool: is verified or not
        """
        return self.get_status() == JIRA_STATUS_VERIFIED

    def is_closed(self):
        """
        Bug status is `Closed`

        Returns:
            bool: is closed or not
        """
        return self.get_status() == JIRA_STATUS_CLOSED

    def is_on_qa(self):
        """
        Bug status is `ON_QA`

        Returns:
            bool: is onqa or not
        """
        return self.get_status() == JIRA_STATUS_ON_QA

    def is_qe_subtask(self):
        """
        check whether the issue is QE subtask.
        """
        return self.get_summary() in JIRA_QE_TASK_SUMMARIES
