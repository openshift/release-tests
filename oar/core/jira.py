import logging
import os
import time
from collections import defaultdict

from jira import Issue
from jira import JIRA
from jira.exceptions import JIRAError

from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import JiraException
from oar.core.exceptions import JiraUnauthorizedException
from oar.core.util import get_advisory_link

logger = logging.getLogger(__name__)


class JiraManager:
    """
    Jira Manager is used to communicate with jira system to get/update/create jira issues
    """

    def __init__(self, cs: ConfigStore):
        self._cs = cs
        token = self._cs.get_jira_token()
        if not token:
            raise JiraException(
                "cannot find auth token from env var JIRA_TOKEN")

        self._svc = JIRA(server=self._cs.get_jira_server(), token_auth=token)
        try:
            self._svc.issue(self._cs.get_jira_ticket())
        except JIRAError as je:
            if je.status_code == 401 or je.status_code == 403:
                raise JiraException("invalid token") from je
            else:
                raise JiraException("cannot talk to jira server") from je

        self._req_count = 0
        self._req_limit = 2

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
            self._req_count += 1
            if self._req_count == self._req_limit:
                time.sleep(1.75)
                self._req_count = 0
        except JIRAError as je:
            if je.status_code == 403:
                logging.exception(
                    f"Cannot get jira issue {key} due to permission issue")
                raise JiraUnauthorizedException from je
            else:
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
        logger.info("Creating jira issue...")
        try:
            issue = self._svc.create_issue(fields=issue_dict)
        except JIRAError as je:
            raise JiraException("create jira issue failed") from je

        logger.info(f"Created jira issue {issue.key}")
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
            raise JiraException(
                f"assign issue {key} to {contact} failed") from je

        logger.info(f"jira issue {key} assignee is updated to {contact}")

    def get_sub_tasks(self, parent_key):
        """
        Get jira subtasks by parent key

        Args:
            parent_key (str): parent issue key

        Returns:
            list[JiraIssue]: jira subtask list
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
            updated_tasks(list): jira keys of updated subtasks
        """
        updated_tasks = []
        subtasks = self.get_sub_tasks(self._cs.get_jira_ticket())
        if len(subtasks):
            for st in subtasks:
                if st.get_summary() in JIRA_QE_TASK_SUMMARIES:
                    self.assign_issue(
                        st.get_key(), self._cs.get_owner().split('@')[0])
                    updated_tasks.append(st.get_key())
                    if st.get_summary().startswith(
                        "[Wed-Fri]"
                    ) or st.get_summary().startswith("[Mon-Wed]"):
                        self.transition_issue(
                            st.get_key(), JIRA_STATUS_IN_PROGRESS)

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
            key (str): jira issue key
            comment (str): description
        """
        if key and comment:
            try:
                self._svc.add_comment(key, comment)
            except JIRAError as je:
                raise JiraException(
                    f"add comment for jira issue {key} failed") from je
        else:
            raise JiraException(
                "invalid input argument key or comment is empty")

    def get_high_severity_and_can_drop_issues(self, jira_issue_keys):
        """
        Get list of critical, blocker, customer or CVE issues and list of issues that can be dropped without confirming

        Args:
            jira_issue_keys (list[str]): jira issues keys to be processed

        Returns:
            tuple[list[str], list[str]]: list of high severity jira keys that are still to be verified, list of jira keys that can be dropped
        """
        high_severity_issues = []
        can_drop_issues = []
        if jira_issue_keys:
            for key in jira_issue_keys:
                issue = self.get_issue(key)
                if issue.is_verified() or issue.is_closed():
                    continue
                else:
                    if issue.is_high_severity_issue():
                        high_severity_issues.append(key)
                    else:
                        can_drop_issues.append(key)

        return high_severity_issues, can_drop_issues
    
    def get_unverified_cve_issues(self, jira_issue_keys: list[str]):
        """
        Get list of unverified CVE issues

        Args:
            jira_issue_keys (list[str]): List of all jira issues keys

        Returns:
            list[JiraIssue]: List of all unverified CVE issues
        """
        unverified_cve_issues = list()
        for key in jira_issue_keys:
            try:
                issue = self.get_issue(key)
            except JiraUnauthorizedException as e:
                logger.error(f"Jira token does not have permission to access security bug {key}, ignore and continue: {e}")
                continue
            if issue.is_on_qa() and issue.is_cve_tracker():
                unverified_cve_issues.append(issue)
        return unverified_cve_issues

    def get_unverified_issues_excluding_cve(self, jira_issue_keys: list[str]):
        """
        Get list of unverified issues (status not in verified, closed), excluding CVE tracker bugs

        Args:
            jira_issue_keys (list[str]): List of jira issue keys to filter

        Returns:
            list[str]: List of issue keys that are unverified and not CVE trackers
        """
        unverified_issues = list()
        for key in jira_issue_keys:
            try:
                issue = self.get_issue(key)
            except JiraUnauthorizedException as e:
                logger.error(f"Jira token does not have permission to access issue {key}, ignore and continue: {e}")
                continue
            if not issue.is_finished() and not issue.is_cve_tracker():
                unverified_issues.append(issue.get_key())
        return unverified_issues

    def create_cvp_issue(self, abnormal_tests):
        """
        Create CVP issue with abnormal test details

        Args:
            abnormal_tests: details to be included in issue description

        Returns:
             JiraIssue: created issue
        """
        jira_issue = self.create_issue(
            project = "CVP",
            summary = self.prepare_cvp_issue_summary(),
            description = self._prepare_greenwave_cvp_jira_description(abnormal_tests),
            issuetype = {"name": "Bug"},
            priority = {"name": "Blocker"}
        )

        return jira_issue

    def is_cvp_issue_reported(self):
        """
        Check if CVP issue with specific cvp summary is reported

        Returns:
             bool: True if CVP issue is reported
        """
        summary = self.prepare_cvp_issue_summary()
        summary_jql = summary.replace('[', '').replace(']', '')
        issues = self.search_issues_by_summary("CVP", summary_jql)

        return True if issues else False

    def search_issues_by_summary(self, project, summary):
        """
        Search issues by summary in given Jira project

        Args:
            project(str): project to look for the issue in
            summary(str): issue summary to look for, expected format: JQL

        Returns:
            ResultList[Issue]: found issues
        """
        logger.debug(f'Looking for issue with summary "{summary}"')
        try:
            issues = self._svc.search_issues(f'project = "{project}" AND summary ~ "{summary}"')
        except JIRAError as je:
            raise JiraException(f'Looking for issue with summary "{summary}" failed') from je

        return issues

    def prepare_cvp_issue_summary(self):
        """
        Prepare Greenwave CVP issue summary

        Returns:
             str: issue summary
        """
        return f"[{self._cs.release}] Greenwave CVP test failures in advisories"

    def _prepare_greenwave_cvp_jira_description(self, abnormal_tests: list[dict]):
        """
        Prepare Greenwave CVP jira description

        Args:
            abnormal_tests(list[dict]): abnormal tests to be included in the description

        Returns:
            str: Greenwave CVP jira description
        """
        grouped_nvrs = defaultdict(list)
        for test in abnormal_tests:
            errata_id = test["relationships"]["errata"]["id"]
            test_id = test["id"]
            nvr = test["relationships"]["brew_build"]["nvr"]
            grouped_nvrs[errata_id].append({"test_id": test_id, "nvr": nvr})

        cvp_details = []
        for errata_id, test_details in grouped_nvrs.items():
            cvp_details.append(f"Failed Nvrs in advisory [{errata_id}|{get_advisory_link(errata_id)}]:")
            for entry in test_details:
                test_id = entry['test_id']
                nvr = entry['nvr']
                cvp_details.append(f"* {nvr} ([test_run/{test_id}|{get_advisory_link(errata_id)}/test_run/{test_id}])")
            cvp_details.append("")

        jira_description = f"[{(self._cs.release)}] Greenwave CVP test failed in the advisories listed below.{os.linesep}{os.linesep}"
        jira_description += os.linesep.join(cvp_details)

        return jira_description

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
        if field:
            if not field.active:
                logger.warning(
                    f"jira issue {self.get_key()} has assigned QA contact which is not active, please contact responsible team to assign a replacement"
                )
            return field.emailAddress
        else:
            logger.warning(
                f"jira issue {self.get_key()} does not have assigned QA contact, please contact responsible team to find it"
            )
            return "Unknown"

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

    def get_need_info_from(self):
        """
        Get issue field `Need Info From`
        """
        return self._issue.fields.customfield_12311840

    def set_need_info_from(self, users: list[dict]):
        """
        Set issue field `Need Info From`
        """
        self._issue.update({"customfield_12311840": users})

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

        return float(sfdc_case_counter) > 0 or bool(sfdc_case_links)

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
    
    def is_finished(self):
        """
        Bug status is `Verified`, `Closed` or `Release Pending`

        Returns:
            bool: is verified, closed or release pending
        """
        return self.is_verified() or self.is_closed() or self.is_release_pending()
    
    def is_release_pending(self):
        """
        Bug status is `Release Pending`

        Returns:
            bool: is release pending or not
        """
        return self.get_status() == JIRA_STATUS_RELEASE_PENDING
    
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
        Check whether the issue is QE subtask.
        """
        return self.get_summary() in JIRA_QE_TASK_SUMMARIES

    def is_high_severity_issue(self):
        """
        Check if the issue is critical, blocker, customer case, or CVE

        Returns:
            bool: True if the issue has high severity
        """
        if self.is_cve_tracker():
            logger.warning(
                f"jira issue {self.get_key()} is cve tracker: {self.is_cve_tracker()}, it must be verified"
            )
            return True
        if self.is_critical_issue() or self.is_customer_case():
            logger.warning(
                f"jira issue {self.get_key()} is critical: {self.is_critical_issue()} or customer case: {self.is_customer_case()}, it should be verified"
            )
            return True
        return False
