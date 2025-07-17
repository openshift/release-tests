import logging
import os
import re
import time
from itertools import chain

import gspread
from google.oauth2.service_account import Credentials
from gspread import Worksheet
from gspread.exceptions import *

import oar.core.util as util
from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import WorksheetException, WorksheetExistsException, JiraUnauthorizedException
from oar.core.jira import JiraManager

logger = logging.getLogger(__name__)

class WorksheetManager:
    """
    WorksheetManager is used to update test report with info provided by ConfigStore
    """

    def __init__(self, cs: ConfigStore):
        if cs:
            self._cs = cs
        else:
            raise WorksheetException("argument config store is required")

        # init gspread instance with scopes an sa file
        sa_file_path = self._cs.get_google_sa_file()
        if sa_file_path and os.path.isfile(sa_file_path):
            try:
                cred = Credentials.from_service_account_file(
                    sa_file_path,
                    scopes=[
                        "https://spreadsheets.google.com/feeds",
                        "https://www.googleapis.com/auth/drive",
                    ],
                )
            except Exception as ce:
                raise WorksheetException(
                    "init cred with SA file failed") from ce
        else:
            raise WorksheetException(
                f"SA file path is invalid: {sa_file_path}")

        try:
            self._gs = gspread.authorize(
                cred, client_factory=gspread.client.BackoffClient)
        except Exception as ge:
            raise WorksheetException("gspread auth failed") from ge

        # check template worksheet exists or not
        try:
            self._doc = self._gs.open_by_key(self._cs.get_report_template())
            self._template = self._doc.worksheet("template")
        except Exception as we:
            raise WorksheetException("cannot find template worksheet") from we

    def create_test_report(self):
        """
        Create new report sheet from template
        Update test report with info in ConfigStore
        """
        try:
            self._create_release_sheet_from_template()

            # get required info from config store and populate cell data
            # update build info
            build_cell_value = ""
            candidate_builds = self._cs.get_candidate_builds()
            if candidate_builds:
                for k, v in candidate_builds.items():
                    build_cell_value += f"{k}: {v}\n"
            # if attr reference_releases! does not have anything, update the cell with empty
            self._report.update_build_info(build_cell_value.strip())
            logger.info("build info is updated")
            logger.debug(f"build info:\n{build_cell_value}")

            # update advisory info
            self._report.update_advisory_info()

            # update jira info
            self._report.update_jira_info(self._cs.get_jira_ticket())
            logger.info("jira info is updated")
            logger.debug(f"jira info:\n{self._cs.get_jira_ticket()}")

            # update on_qa bugs list
            am = AdvisoryManager(self._cs)
            self._report.generate_bug_list(am.get_jira_issues())

            # add test results links
            self._report.create_test_results_links()

            # setup blocking sec-alerts section
            self._report.setup_blocking_sec_alerts()

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

    def _create_release_sheet_from_template(self):
        """
        Create release worksheet from template

        If the release worksheet already exists, creation is skipped.

        Raises:
            WorksheetExistsException: If the worksheet already exists
        """
        try:
            existing_sheet = self._doc.worksheet(self._cs.release)
            if existing_sheet:
                logger.info(
                    f"test report of {self._cs.release} already exists, url: {existing_sheet.url}")
                raise WorksheetExistsException()
        except WorksheetNotFound:
            new_sheet = self._doc.duplicate_sheet(self._template.id)
            new_sheet.update_title(self._cs.release)
            self._report = TestReport(new_sheet, self._cs)

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

    def update_advisory_info(self):
        """
        Update advisory info in test report
        """
        ad_info = []
        # Arrange AD names and urls as per needs of spreadsheet.batch_update API
        for k, v in self._cs.get_advisories().items():
            ad_info.append({"name": k, "url": util.get_advisory_link(v)})

        text, text_format_runs = TestReport._prepare_hyperlink_text_format_runs(ad_info, True)
        requests = [
            {
                "updateCells": {
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {"stringValue": text},
                                    "textFormatRuns": text_format_runs
                                }
                            ]
                        }
                    ],
                    "range": {"sheetId": self._ws.id, "startRowIndex": LABEL_ADVISORY_START_ROW_INDEX,
                              "endRowIndex": LABEL_ADVISORY_END_ROW_INDEX,
                              "startColumnIndex": LABEL_ADVISORY_START_COL_INDEX,
                              "endColumnIndex": LABEL_ADVISORY_END_COL_INDEX},
                    "fields": "userEnteredValue,textFormatRuns"
                }
            }
        ]
        self._ws.spreadsheet.batch_update({"requests": requests})
        logger.info("advisory info is updated")
        logger.debug(f"advisory info:\n{ad_info}")

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
            self._to_hyperlink(util.get_jira_link(jira), jira),
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
        else:
            # if no failed cases, update overall status to Green
            if status != TASK_STATUS_INPROGRESS:
                no_failed_task = True
                for label in ALL_TASKS:
                    if self.is_task_fail(label):
                        no_failed_task = False
                        break
                if no_failed_task and self.is_overall_status_red():
                    logger.debug(
                        "there is no failed task and overall status is Red, will update overall status to Green"
                    )
                    self.update_overall_status_to_green()

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
        Util func to check whether task status is 'Pass'

        Args:
            label (str): cell label of different tasks
        """
        return TASK_STATUS_PASS == self.get_task_status(label)

    def is_task_fail(self, label):
        """
        Util func to check whether task status is 'Fail'

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

    def is_overall_status_green(self):
        """
        Check whether overall status is Green

        Returns:
            bool: boolean value of the result
        """
        return OVERALL_STATUS_GREEN == self.get_overall_status()

    def is_overall_status_red(self):
        """
        Check whether overall status is Red

        Returns:
            bool: boolean value of the result
        """
        return OVERALL_STATUS_RED == self.get_overall_status()

    def generate_bug_list(self, jira_issues: list[str]):
        """
        Generate bug list of on_qa bugs

        Args:
            jira_issues (list[str]): jira issue keys from advisories
        """
        logger.info("waiting for the bugs to be verified to update in sheet")
        jm = JiraManager(self._cs)
        row_idx = 8
        batch_vals = []
        for key in jira_issues:
            try:
                issue = jm.get_issue(key)
            except JiraUnauthorizedException:  # jira token does not have permission to access security bugs, ignore it
                continue
            logger.debug(f"updating jira issue {key} ...")
            if issue.is_on_qa():
                logger.debug(f"jira issue {key} is ON_QA, updating")
                row_vals = []
                row_vals.append(self._to_hyperlink(
                    util.get_jira_link(key), key))
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

    def update_bug_list(self, jira_issues: list):
        """
        Update existing bug status in report
        Append new ON_QA bugs

        Args:
            jira_issues (list): updated jira issues
        """
        jm = JiraManager(self._cs)
        # iterate cell value from C8 in colum C, update existing bug status
        existing_bugs = []
        row_idx = 8
        while True:
            bug_key = self._ws.acell("C" + str(row_idx)).value
            bug_qa_contact = self._ws.acell("D" + str(row_idx)).value
            bug_status = self._ws.acell("E" + str(row_idx)).value
            # if bug_key is empty exit the loop. i.e. at the end of bug list
            if not bug_key:
                break
            logger.info(f"found existing bug {bug_key} in report, checking...")
            try:
                issue = jm.get_issue(bug_key)
                # check QA contact of bug and update if needed
                if bug_qa_contact != issue.get_qa_contact():
                    self._ws.update_acell(
                        "D" + str(row_idx), issue.get_qa_contact())
                    logger.info(
                        f"QA contact of bug {issue.get_key()} is updated to {issue.get_qa_contact()}"
                    )
                # check bug status is updated or not. if yes, update it accordingly
                if bug_status != issue.get_status():
                    self._ws.update_acell(
                        "E" + str(row_idx), issue.get_status())
                    logger.info(
                        f"status of bug {issue.get_key()} is updated to {issue.get_status()}"
                    )
                elif bug_key not in jira_issues:
                    self._ws.update_acell(
                        "E" + str(row_idx), JIRA_STATUS_DROPPED)
                    logger.info(f"bug {bug_key} is dropped")
                else:
                    logger.info(f"bug status of {bug_key} is not changed")
                if issue.is_cve_tracker():
                    logger.warning(
                        f"jira issue {issue.get_key()} is cve tracker: {issue.is_cve_tracker()}, it must be verified"
                    )
            except JiraUnauthorizedException:
                pass
            except Exception as e:
                raise WorksheetException(
                    f"update bug {bug_key} status failed") from e

            existing_bugs.append(bug_key)
            row_idx += 1

        try:
            start_idx = row_idx
            batch_vals = []
            for key in jira_issues:
                if key not in existing_bugs:
                    try:
                        issue = jm.get_issue(key)
                    except JiraUnauthorizedException:  # ignore the bug that cannot be accessed due to permission issue
                        continue
                    if issue.is_on_qa():
                        logger.info(f"found new ON_QA bug {key}")
                        row_vals = []
                        row_vals.append(
                            self._to_hyperlink(util.get_jira_link(key), key)
                        )
                        row_vals.append(issue.get_qa_contact())
                        row_vals.append(issue.get_status())
                        batch_vals.append(row_vals)
                        row_idx += 1

            if len(batch_vals) > 0:
                self._ws.batch_update(
                    [
                        {
                            "range": "C{}:E{}".format(str(start_idx), str(row_idx)),
                            "values": batch_vals,
                        }
                    ],
                    value_input_option=gspread.utils.ValueInputOption.user_entered,
                )
                logger.info("all new ON_QA bugs are appended to the report")
        except Exception as e:
            raise WorksheetException("update new ON_QA bugs failed") from e

    def are_all_bugs_verified(self):
        """
        Check all bugs are verified
        """
        logger.info("checking all bugs are verified")
        row_idx = 8
        verified = True
        try:
            while True:
                status = self._ws.acell("E" + str(row_idx)).value
                if not status:
                    break
                if status not in [
                    JIRA_STATUS_VERIFIED,
                    JIRA_STATUS_CLOSED,
                    JIRA_STATUS_DROPPED,
                ]:
                    verified = False
                    bug_key = self._ws.acell("C" + str(row_idx)).value
                    logger.debug(f"found not verified bug {bug_key}:{status}")
                    break
                row_idx += 1
        except Exception as e:
            raise WorksheetException("iterate bug status failed") from e

        logger.info("result is: {}".format("yes" if verified else "no"))

        return verified

    def append_missed_cve_tracker_bugs(self, cve_tracker_bugs):
        """
        Append missed CVE tracker bugs
        """
        if len(cve_tracker_bugs) == 0:
            logger.warning("no cve bugs found, won't update report")
            return

        row_idx = 8
        while True:
            cell_value = self._ws.acell("F" + str(row_idx)).value
            if not cell_value:
                break
            else:
                # check whether track bug is already there, remove it from the list
                match = re.search(r'OCPBUGS-\d+', cell_value)
                if match:
                    bug = match.group(0)
                    logger.info(
                        f"found existing CVE tracker bug {bug} in report")
                    cve_tracker_bugs.remove(bug)
            row_idx += 1

        for bug in cve_tracker_bugs:
            self._ws.update_acell(
                "F" + str(row_idx), self._to_hyperlink(util.get_jira_link(bug), bug)
            )
            row_idx += 1
            logger.info(f"append missed CVE tracker bug {bug} to test report")

        # if cve_tracker_bugs list is not empty, it means a new tracker bug is found
        # we need to send out notification
        return len(cve_tracker_bugs) > 0

    def add_jira_to_others_section(self, jira_key, max_retries = 3, delay = 2):
        """
        Add jira to "others" section

        Find the first available cell in section, and add jira to it.

        Args:
             jira_key(str): jira key to be added
             max_retries: optional maximum number of attempts, default value is 3
             delay: optional delay between worksheet calls, default value is 2
        """
        issue_keys = self._get_issues_from_others_section()

        row_idx = LABEL_ISSUES_OTHERS_ROW
        # Find first empty cell
        if "" in issue_keys:
            row_idx += issue_keys.index("")
        else:
            row_idx += len(issue_keys)

        jira_hyperlink = self._to_hyperlink(
            util.get_jira_link(jira_key), jira_key)

        for attempt in range(1, max_retries + 1):
            try:
                self._ws.update_acell(f"{LABEL_ISSUES_OTHERS_COLUMN}{row_idx}", jira_hyperlink)
                logger.info(f"Jira {jira_key} was added to test report")
                break
            except Exception as e:
                logger.warning(f"Adding jira {jira_key} to test report failed on attempt: {attempt}")
                if attempt < max_retries:
                    time.sleep(delay)
                else:
                    logger.error(f"Adding jira {jira_key} to test report failed after all retries: {e}")

    def create_test_results_links(self):
        self._ws.update_acell(LABEL_BLOCKING_TESTS, "Blocking jobs")
        self._ws.update_acell(
            LABEL_BLOCKING_TESTS_RELEASE,
            self._to_hyperlink(
                util.get_ocp_test_result_url(self._cs.release),
                f"ocp-test-result-{self._cs.release}"
            )
        )

        candidate_build_cell_value = "no-candidate-build-no-test-results"
        candidate_builds = self._cs.get_candidate_builds()
        if candidate_builds and "x86_64" in candidate_builds:
            cb = candidate_builds["x86_64"]
            candidate_build_cell_value = self._to_hyperlink(
                util.get_ocp_test_result_url(cb),
                f"ocp-test-result-{cb}"
            )
        self._ws.update_acell(
            LABEL_BLOCKING_TESTS_CANDIDATE,
            candidate_build_cell_value
        )

        self._ws.update_acell(LABEL_SIPPY, "Sippy")
        self._ws.update_acell(
            LABEL_SIPPY_MAIN,
            self._to_hyperlink(
                util.get_qe_sippy_main_view_url(self._cs.release),
                f"{util.get_y_release(self._cs.release)}-qe-main"
            )
        )
        self._ws.update_acell(
            LABEL_SIPPY_AUTO_RELEASE,
            self._to_hyperlink(
                util.get_qe_sippy_auto_release_view_url(self._cs.release),
                f"{util.get_y_release(self._cs.release)}-qe-auto-release"
            )
        )

    # ========================================================================
    # BLOCKING SECURITY ALERTS FUNCTIONALITY
    # ========================================================================

    # Color constants for security alerts dropdown
    _BLOCKING_ALERT_COLORS = {
        "YES_BACKGROUND": {"red": 1.0, "green": 0.8, "blue": 0.8},  # Light red
        "NO_BACKGROUND": {"red": 0.8, "green": 1.0, "blue": 0.8},   # Light green
    }

    # Security alert check result template
    _SECURITY_ALERT_RESULT_TEMPLATE = {
        "has_blocking": False,
        "checked_advisories": [],
        "blocking_advisories": [],
        "errors": []
    }

    def setup_blocking_sec_alerts(self):
        """
        Set up the complete blocking security alerts section

        This method:
        1. Creates the text label in A29
        2. Creates a color-coded dropdown in B29
        3. Automatically checks all advisories and sets the appropriate value
        4. Logs the setup completion
        """
        try:
            logger.info("Setting up blocking security alerts section...")

            # Set up the UI components
            self._create_security_alerts_ui()

            # Perform initial check and set status
            self.refresh_blocking_sec_alerts_status()

            logger.info("✅ Blocking sec-alerts section setup complete with automated checking")

        except Exception as e:
            logger.error(f"Failed to setup blocking security alerts section: {e}")
            # Fallback setup - at least create the UI components
            try:
                self._create_security_alerts_ui()
                self._ws.update_acell(LABEL_BLOCKING_SEC_ALERTS_DROPDOWN, "No")
                logger.warning("⚠️ Setup completed with fallback to 'No' due to checking error")
            except Exception as fallback_error:
                logger.error(f"Even fallback setup failed: {fallback_error}")
                raise WorksheetException("Failed to setup blocking security alerts section") from e

    def _create_security_alerts_ui(self):
        """Create the UI components for blocking security alerts"""
        # Set the text label in A29
        self._ws.update_acell(LABEL_BLOCKING_SEC_ALERTS, "Blocking sec-alerts")

        # Create dropdown in B29 with Yes/No options and color coding
        self._create_security_alerts_dropdown()

    def _create_security_alerts_dropdown(self):
        """Create the security alerts dropdown with proper color coding"""
        options = ["Yes", "No"]
        cell_label = LABEL_BLOCKING_SEC_ALERTS_DROPDOWN

        # Get cell coordinates
        row_index, col_index = self._parse_cell_coordinates(cell_label)

        # Create the dropdown with validation and color formatting
        requests = self._build_dropdown_requests(row_index, col_index, options)
        requests.extend(self._build_color_formatting_requests(row_index, col_index))

        # Execute the batch update
        self._ws.spreadsheet.batch_update({"requests": requests})
        logger.debug(f"Security alerts dropdown created in {cell_label}")

    def check_for_blocking_sec_alerts(self):
        """
        Check all advisories for blocking security alerts

        Returns:
            tuple: (has_blocking_alerts: bool, details: dict)
                - has_blocking_alerts: True if any RHSA advisory has blocking alerts
                - details: Dictionary with comprehensive check results
        """
        try:
            logger.info("Checking for blocking security alerts across all advisories...")

            # Initialize result structure
            result = self._SECURITY_ALERT_RESULT_TEMPLATE.copy()
            result["checked_advisories"] = []
            result["blocking_advisories"] = []
            result["errors"] = []

            # Get all advisories
            advisories = self._get_advisories_for_security_check()

            # Check each advisory
            for advisory in advisories:
                advisory_result = self._check_single_advisory(advisory)
                result["checked_advisories"].append(advisory_result)

                # Track blocking advisories
                if advisory_result.get("has_blocking", False):
                    result["has_blocking"] = True
                    result["blocking_advisories"].append(advisory_result)

                # Track errors
                if advisory_result.get("error"):
                    result["errors"].append(advisory_result)

            # Log summary
            self._log_security_check_summary(result)

            return result["has_blocking"], result

        except Exception as e:
            error_msg = f"Failed to check for blocking security alerts: {e}"
            logger.error(error_msg)
            return False, {"error": str(e), "checked_advisories": [], "blocking_advisories": [], "errors": []}

    def _get_advisories_for_security_check(self):
        """Get advisories for security alert checking"""
        from oar.core.advisory import AdvisoryManager
        am = AdvisoryManager(self._cs)
        return am.get_advisories()

    def _check_single_advisory(self, advisory):
        """
        Check a single advisory for blocking security alerts

        Args:
            advisory: Advisory object to check

        Returns:
            dict: Advisory check result with status and metadata
        """
        advisory_info = {
            "errata_id": advisory.errata_id,
            "type": advisory.errata_type,
            "impetus": getattr(advisory, 'impetus', 'unknown'),
            "has_blocking": False,
            "checked": False
        }

        try:
            # Only check RHSA advisories (RHBA don't have security alerts)
            if advisory.errata_type == "RHSA":
                advisory_info["checked"] = True
                has_blocking = advisory.has_blocking_secruity_alert()
                advisory_info["has_blocking"] = has_blocking

                if has_blocking:
                    logger.warning(f"🔴 Advisory {advisory.errata_id} has blocking security alerts!")
                else:
                    logger.debug(f"✅ Advisory {advisory.errata_id} has no blocking security alerts")
            else:
                advisory_info["reason"] = "RHBA advisories don't have security alerts"
                logger.debug(f"⏭️ Skipping {advisory.errata_type} advisory {advisory.errata_id} (no security alerts)")

        except Exception as e:
            advisory_info["error"] = str(e)
            logger.error(f"❌ Error checking advisory {advisory.errata_id}: {e}")

        return advisory_info

    def _log_security_check_summary(self, result):
        """Log a summary of the security alert check results"""
        total_advisories = len(result["checked_advisories"])
        rhsa_checked = len([a for a in result["checked_advisories"] if a.get("checked", False)])
        blocking_count = len(result["blocking_advisories"])
        error_count = len(result["errors"])

        logger.info(f"🔍 Security alert check complete: {total_advisories} total, {rhsa_checked} RHSA checked, {blocking_count} blocking, {error_count} errors")

        if blocking_count > 0:
            blocking_ids = [str(a["errata_id"]) for a in result["blocking_advisories"]]
            logger.warning(f"⚠️ Blocking alerts found in advisories: {', '.join(blocking_ids)}")

    def refresh_blocking_sec_alerts_status(self):
        """
        Check for blocking security alerts and update the dropdown value automatically

        This is the main method that coordinates checking and updating.

        Returns:
            tuple: (has_blocking_alerts: bool, details: dict)
        """
        try:
            # Perform the security alert check
            has_blocking, details = self.check_for_blocking_sec_alerts()

            # Update the dropdown based on results
            new_status = "Yes" if has_blocking else "No"
            self.update_blocking_sec_alerts_status(new_status)

            # Log the result
            if has_blocking:
                logger.info("🔴 Automated check: Found blocking security alerts - set to 'Yes'")
            else:
                logger.info("🟢 Automated check: No blocking security alerts - set to 'No'")

            return has_blocking, details

        except Exception as e:
            logger.error(f"Failed to refresh blocking sec-alerts status: {e}")
            # Fallback to "No" if check fails
            self._fallback_to_safe_status()
            return False, {"error": str(e)}

    def _fallback_to_safe_status(self):
        """Set a safe fallback status when automated checking fails"""
        try:
            self.update_blocking_sec_alerts_status("No")
            logger.warning("⚠️ Automated check failed - defaulting to 'No' for safety")
        except Exception as fallback_error:
            logger.error(f"Even fallback status update failed: {fallback_error}")

    def update_blocking_sec_alerts_status(self, status):
        """
        Update the blocking sec-alerts dropdown status

        Args:
            status (str): Either "Yes" or "No"

        Raises:
            WorksheetException: If status is not "Yes" or "No"
        """
        if status not in ["Yes", "No"]:
            raise WorksheetException("Status must be either 'Yes' or 'No'")

        self._ws.update_acell(LABEL_BLOCKING_SEC_ALERTS_DROPDOWN, status)
        logger.debug(f"Blocking sec-alerts status updated to: {status}")

    def get_blocking_sec_alerts_status(self):
        """
        Get the current blocking sec-alerts status

        Returns:
            str: The current status ("Yes", "No", or None if not set)
        """
        try:
            return self._ws.acell(LABEL_BLOCKING_SEC_ALERTS_DROPDOWN).value
        except Exception as e:
            logger.warning(f"Failed to get blocking sec-alerts status: {e}")
            return None

    # ========================================================================
    # DROPDOWN CREATION UTILITIES
    # ========================================================================

    def _create_dropdown(self, cell_label, options):
        """
        Create a dropdown with specified options in the given cell

        This is a generic dropdown creator. For security alerts, use
        _create_security_alerts_dropdown() which includes color coding.

        Args:
            cell_label (str): Cell address in A1 notation (e.g., 'B29')
            options (list): List of dropdown options
        """
        # Get cell coordinates
        row_index, col_index = self._parse_cell_coordinates(cell_label)

        # Build and execute dropdown requests
        requests = self._build_dropdown_requests(row_index, col_index, options)

        # Add color formatting for Yes/No dropdowns
        if set(options) == {"Yes", "No"}:
            requests.extend(self._build_color_formatting_requests(row_index, col_index))

        self._ws.spreadsheet.batch_update({"requests": requests})
        logger.debug(f"Dropdown created in {cell_label} with options: {options}")

    def _parse_cell_coordinates(self, cell_label):
        """
        Parse cell label to get row and column indices

        Args:
            cell_label (str): Cell address in A1 notation

        Returns:
            tuple: (row_index, col_index) as 0-based integers
        """
        import re
        match = re.match(r'([A-Z]+)(\d+)', cell_label)
        if not match:
            raise WorksheetException(f"Invalid cell label: {cell_label}")

        col_str, row_str = match.groups()
        row_index = int(row_str) - 1  # Convert to 0-based

        # Convert column letters to 0-based index
        col_index = 0
        for char in col_str:
            col_index = col_index * 26 + (ord(char) - ord('A') + 1)
        col_index -= 1  # Convert to 0-based

        return row_index, col_index

    def _build_dropdown_requests(self, row_index, col_index, options):
        """Build the data validation requests for dropdown creation"""
        return [
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": self._ws.id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": option} for option in options]
                        },
                        "showCustomUi": True,
                        "strict": True
                    }
                }
            }
        ]

    def _build_color_formatting_requests(self, row_index, col_index):
        """Build conditional formatting requests for Yes/No color coding"""
        requests = []

        # Red background for "Yes" (indicating blocking)
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": self._ws.id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Yes"}]
                        },
                        "format": {
                            "backgroundColor": self._BLOCKING_ALERT_COLORS["YES_BACKGROUND"]
                        }
                    }
                },
                "index": 0
            }
        })

        # Green background for "No" (indicating not blocking)
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": self._ws.id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "No"}]
                        },
                        "format": {
                            "backgroundColor": self._BLOCKING_ALERT_COLORS["NO_BACKGROUND"]
                        }
                    }
                },
                "index": 1
            }
        })

        return requests

    # ========================================================================
    # END BLOCKING SECURITY ALERTS FUNCTIONALITY
    # ========================================================================

    def _get_issues_from_others_section(self):
        """
        Get issue keys from "others" section in work sheet

        Returns:
            list[str]: list of issue keys
        """
        range_values = self._ws.get_values(f"{LABEL_ISSUES_OTHERS_COLUMN}{LABEL_ISSUES_OTHERS_ROW}:{LABEL_ISSUES_OTHERS_COLUMN}")
        return list(chain.from_iterable(range_values))

    @staticmethod
    def _prepare_hyperlink_text_format_runs(link_entries: list[dict], format_separate_urls: bool = False):
        """
        Prepare text with hyperlink formatting for use in a Google Sheets API update request

        This method constructs the data structure needed to apply hyperlink formatting to specific parts
        of a text within a spreadsheet cell. The resulting output includes `textFormatRuns`,
        which can be used with the Google Sheets API to update cell content with embedded clickable links.

        By default, the returned text contains only the names as clickable hyperlinks.
        When the `format_separate_urls` parameter is set to `True`, the returned text contains entries formatted as "name: url".

        Args:
            link_entries (list[dict]):
                List of dictionaries with 'name' and 'url' keys.
                Expected format: [{"name": "value", "url": "value"}, ...]
            format_separate_urls (bool):
                If False (default), returns only the names as clickable hyperlinks.
                If True, returns text containing entries formatted as "name: url".

        Returns:
            tuple[str, list[dict]]:
                A tuple containing the text and a list of text format runs to apply hyperlink formatting.
        """
        if format_separate_urls:
            text = "\n".join([e["name"] + ": " + e["url"] for e in link_entries])
            url_text = "url"
        else:
            text = "\n".join([e["name"] for e in link_entries])
            url_text = "name"

        # Prepare textFormatRuns
        text_format_runs = []
        for entry in link_entries:
            visible_text_for_url = entry[url_text]
            start_index = text.find(visible_text_for_url)
            end_index = start_index + len(visible_text_for_url)
            text_format_runs.append({
                "startIndex": start_index,
                "format": {"link": {"uri": entry["url"]}}
            })
            if end_index < len(text):
                text_format_runs.append({
                    "startIndex": end_index,
                    "format": {}
                })

        return text, text_format_runs

    def _to_hyperlink(self, link, label):
        return f'=HYPERLINK("{link}","{label}")'
