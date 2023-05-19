import gspread
import gspread_formatting
import os
import logging
from oar.core.exceptions import WorksheetException
from oar.core.config_store import ConfigStore
from oar.core.const import *
from oar.core.advisory_mgr import AdvisoryManager, Advisory
from oar.core.jira_mgr import JiraManager
from google.oauth2.service_account import Credentials
from gspread.exceptions import *
from gspread import Worksheet

logger = logging.getLogger(__name__)


class WorksheetManager:
    """
    WorksheetManager will be used to update test report with info provided by ConfigStore
    """

    def __init__(self, cs: ConfigStore):
        if cs:
            self._cs = cs
        else:
            raise WorksheetException("argument config store is required")

        # init gspread instance with scopes an sa file
        sa_file_path = self._cs.get_google_sa_file()
        if os.path.isfile(sa_file_path):
            try:
                cred = Credentials.from_service_account_file(
                    sa_file_path,
                    scopes=[
                        "https://spreadsheets.google.com/feeds",
                        "https://www.googleapis.com/auth/drive",
                    ],
                )
            except Exception as ce:
                raise WorksheetException("init cred with SA file failed") from ce
        else:
            raise WorksheetException(f"SA file path is invalid: {sa_file_path}")

        try:
            self._gs = gspread.authorize(cred)
        except Exception as ge:
            raise WorksheetException("gspread auth failed") from ge

        # check template worksheet exists or not
        try:
            self._doc = self._gs.open_by_key(self._cs.get_report_template())
            template = self._doc.worksheet("template")
        except Exception as we:
            raise WorksheetException("cannot find template worksheet") from we

    def create_test_report(self):
        """
        Create new report sheet from template
        Update test report with info in ConfigStore
        """
        try:
            # check report worksheet exists or not, if yes, skip duplicating
            try:
                existing_sheet = self._doc.worksheet(self._cs.release)
                self._report = TestReport(existing_sheet, self._cs)
            except WorksheetNotFound:
                new_sheet = self._doc.duplicate_sheet(template.id)
                new_sheet.update_title(self._cs.release)
                self._report = TestReport(new_sheet, self._cs)

            # get required info from config store and populate cell data
            # update build info
            build_cell_value = ""
            for k, v in self._cs.get_candidate_builds().items():
                build_cell_value += f"{k}: {v}\n"
            self._report.update_build_info(build_cell_value[:-1])
            logger.info("build info is updated")
            logger.debug(f"build info:\n{build_cell_value}")

            # update advisory info
            ad_cell_value = ""
            for k, v in self._cs.get_advisories().items():
                ad_cell_value += f"{k}: {v}\n"
            self._report.update_advisory_info(ad_cell_value[:-1])
            logger.info("advisory info is updated")
            logger.debug(f"advisory info:\n{ad_cell_value}")

            # update jira info
            self._report.update_jira_info(self._cs.get_jira_ticket())
            logger.info("jira info is updated")
            logger.debug(f"jira info:\n{self._cs.get_jira_ticket()}")

            # update on_qa bugs list
            am = AdvisoryManager(self._cs)
            self._report.generate_bug_list(am.get_jira_issues())

        except Exception as ge:  # catch all the exceptions here
            raise WorksheetException("create test report failed") from ge

        return self._report

    def get_test_report(self):
        """
        Get test report impl with release version in config store
        """
        try:
            ws = self._doc.worksheet(self._cs.release)
        except Exception as e:
            raise WorksheetException(
                f"cannot find worksheet {self._cs.release} in report doc"
            ) from e

        return TestReport(ws, self._cs)

    def delete_test_report(self):
        """
        Delete test report
        """
        try:
            self._doc.del_worksheet(self._report._ws)
        except Exception as e:
            raise WorksheetException(
                f"delete worksheet {self._report._ws.title} failed"
            ) from e


class TestReport:
    """
    Wrapper of worksheet to update test report easily
    """

    def __init__(self, ws: Worksheet, cs: ConfigStore):
        self._ws = ws
        self._cs = cs

    def get_url(self):
        """
        Get worksheet url of the report
        """
        return self._ws.url

    def update_advisory_info(self, ad):
        """
        Update advisory info in test report

        Args:
            ad (str): advisories of current release
        """
        self._ws.update_acell(LABEL_ADVISORY, ad)

    def get_advisory_info(self):
        """
        Get advisory info from test report
        """
        return self._ws.acell(LABEL_ADVISORY).value

    def update_build_info(self, build):
        """
        Update candidate nightly build info in test report

        Args:
            build (str): nightly build info
        """
        self._ws.update_acell(LABEL_BUILD, build)

    def get_build_info(self):
        """
        Get candidate nightly build info from test report
        """
        return self._ws.acell(LABEL_BUILD).value

    def update_jira_info(self, jira):
        """
        Update jira ticket created by ART team

        Args:
            jira (str): jira ticket key
        """
        self._ws.update_acell(
            LABEL_JIRA,
            self._to_hyperlink(self._to_jira_link(jira), jira),
        )

    def get_jira_info(self):
        """
        Get jira ticket created by ART team
        """
        return self._ws.acell(LABEL_JIRA).value

    def update_overall_status_to_red(self):
        """
        Update overall status to Red
        """
        self._ws.update_acell(LABEL_OVERALL_STATUS, OVERALL_STATUS_RED)
        logger.info("Overall status is updated to Red")

    def update_overall_status_to_green(self):
        """
        Update overall status to Green
        """
        self._ws.update_acell(LABEL_OVERALL_STATUS, OVERALL_STATUS_GREEN)
        logger.info("Overall status is updated to Green")

    def get_overall_status(self):
        """
        Get overall status value
        """
        return self._ws.acell(LABEL_OVERALL_STATUS).value

    def update_task_status(self, label, status):
        """
        Update task status in check list
        e.g. Pass/Fail/In Progress

        Args:
            label (str): cell label, A1/B2
            status (str): Pass/Fail/In Progress
        """
        self._ws.update_acell(label, status)
        task_name = self._ws.acell("A" + label[1:]).value
        logger.info(f"task [{task_name}] status is changed to [{status}]")
        # if any task is failed, update overall status to Red
        if self.is_task_fail(label):
            self.update_overall_status_to_red()

    def get_task_status(self, label):
        """
        Get task status

        Args:
            label (str): cell label of different tasks
        """
        return self._ws.acell(label).value

    def is_task_in_progress(self, label):
        """
        Util func to check whether task is working in progress

        Args:
            label (str): cell label of different tasks
        """
        return TASK_STATUS_INPROGRESS == self.get_task_status(label)

    def is_task_pass(self, label):
        """
        Util func to check whether task is pass

        Args:
            label (str): cell label of different tasks
        """
        return TASK_STATUS_PASS == self.get_task_status(label)

    def is_task_fail(self, label):
        """
        Util func to check whether task is fail

        Args:
            label (str): cell label of different tasks
        """
        return TASK_STATUS_FAIL == self.get_task_status(label)

    def is_task_not_started(self, label):
        """
        Util func to check whether task is not started

        Args:
            label (str): cell label of different tasks
        """
        return TASK_STATUS_NOT_STARTED == self.get_task_status(label)

    def generate_bug_list(self, jira_issues: []):
        """
        Generate bug list of on_qa bugs

        Args:
            jira_issues (str[]): jira issue keys from advisories
        """
        jm = JiraManager(self._cs)
        row_idx = 8
        batch_vals = []
        for key in jira_issues:
            issue = jm.get_issue(key)
            logger.debug(f"updating jira issue {key} ...")
            if issue.is_on_qa():
                logger.debug(f"jira issue {key} is ON_QA, updating")
                row_vals = []
                row_vals.append(self._to_hyperlink(self._to_jira_link(key), key))
                row_vals.append(issue.get_qa_contact())
                row_vals.append(issue.get_status())
                batch_vals.append(row_vals)
                row_idx += 1
            else:
                logger.debug(
                    f"jira issue {key} status is {issue.get_status()}, skipping"
                )
        self._ws.batch_update(
            [
                {
                    "range": LABEL_BUG_FIRST_CELL + ":E" + str(row_idx),
                    "values": batch_vals,
                }
            ],
            value_input_option=gspread.utils.ValueInputOption.user_entered,
        )
        # TODO: highlight the cell if the issue is critical

        logger.info("bugs to be verified are updated")

    def update_bug_list(self, jira_issues: []):
        """
        Plackholder for the func for bug status update

        Args:
            jira_issues ([]): updated jira issues
        """
        pass

    def _to_hyperlink(self, link, label):
        return f'=HYPERLINK("{link}","{label}")'

    def _to_jira_link(self, key):
        return "%s/browse/%s" % (self._cs.get_jira_server(), key)
