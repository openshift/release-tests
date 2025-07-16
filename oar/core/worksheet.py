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
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import WorksheetException, WorksheetExistsException, JiraUnauthorizedException
from oar.core.jira import JiraManager
from oar.core.shipment import ShipmentData

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
            # check report worksheet exists or not, if yes, skip duplicating
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

            # update shipment MRs and RPM advisory link
            shipment_mrs = self._cs.get_shipment_mrs()
            rpm_advisory = self._cs.get_rpm_advisory()
            self._report.update_shipment_info(shipment_mrs, rpm_advisory)
            logger.info("shipment info is updated")
            logger.debug(f"shipment info:\n MR: {shipment_mrs}\nRPM advisory id: {rpm_advisory}")

            # update jira info
            self._report.update_jira_info(self._cs.get_jira_ticket())
            logger.info("jira info is updated")
            logger.debug(f"jira info:\n{self._cs.get_jira_ticket()}")

            # update on_qa bugs list
            shipment = ShipmentData(self._cs)
            self._report.generate_bug_list(shipment.get_jira_issues())

            # add test results links
            self._report.create_test_results_links()

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

    def update_shipment_info(self, shipment_mrs, rpm_advisory):
        """
        Update shipment info in test report with shipment MRs and RPM advisory link

        Args:
            shipment_mrs (list): List of shipment MR URLs
            rpm_advisory (str): RPM advisory ID (will be converted to full link)
        """
        links_data = []
        if rpm_advisory:
            links_data.append((f"rpm: {rpm_advisory}", util.get_advisory_link(rpm_advisory), rpm_advisory))

        for mr in shipment_mrs:
            links_data.append((mr, mr))
        
        self.update_cell_with_hyperlinks(LABEL_SHIPMENT, links_data)

    def get_shipment_info(self):
        """
        Get shipment info from test report
        """
        return self._ws.acell(LABEL_SHIPMENT).value

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

    def _get_issues_from_others_section(self):
        """
        Get issue keys from "others" section in work sheet

        Returns:
            list[str]: list of issue keys
        """
        range_values = self._ws.get_values(f"{LABEL_ISSUES_OTHERS_COLUMN}{LABEL_ISSUES_OTHERS_ROW}:{LABEL_ISSUES_OTHERS_COLUMN}")
        return list(chain.from_iterable(range_values))

    def _to_hyperlink(self, link, label):
        return f'=HYPERLINK("{link}","{label}")'

    def update_cell_with_hyperlinks(self, cell_label, links_data):
        """
        Update a cell with multiple hyperlinks, each on a new line
        
        Args:
            cell_label (str): The cell label to update (e.g. "A1")
            links_data (list): List of tuples containing:
                              - (display_text, link) OR
                              - (display_text, link, linkable_text) OR 
                              - (display_text, link, linkable_text, text_format_runs)
                              where:
                              - linkable_text: portion of display_text to hyperlink
                              - text_format_runs: optional pre-defined format runs

        Raises:
            WorksheetException: If links_data is invalid (None, not a list, or empty)

        Examples:
            # Simple hyperlink
            [("Click here", "https://example.com")]
            
            # Partial text hyperlink
            [("Click here for details", "https://example.com", "here")]
            
            # Custom format runs
            [
                (
                    "Important: Click here", 
                    "https://example.com",
                    "here",
                    [
                        {
                            "startIndex": 0,
                            "format": {"bold": True}
                        },
                        {
                            "startIndex": 10,  # Start of "here"
                            "format": {"link": {"uri": "https://example.com"}}
                        }
                    ]
                )
            ]
        """
        # Validate input
        if links_data is None:
            raise WorksheetException("links_data cannot be None")
        if not isinstance(links_data, list):
            raise WorksheetException("links_data must be a list")
        if len(links_data) == 0:
            raise WorksheetException("links_data cannot be empty")
        try:
            # Try advanced formatting first
            text = "\n".join([item[0] for item in links_data])  # Extract just the display text
            text_format_runs = []
            for item in links_data:
                display_text = item[0]
                link = item[1]
                
                # If format runs are provided (4th element), use them directly
                if len(item) > 3 and item[3]:
                    text_format_runs.extend(item[3])
                else:
                    # Otherwise use linkable_text logic
                    linkable_text = item[2] if len(item) > 2 else display_text
                    
                    # Validate linkable_text is part of display_text
                    if linkable_text not in display_text:
                        raise WorksheetException(
                            f"linkable_text '{linkable_text}' must be part of display_text '{display_text}'"
                        )
                    
                    # Find positions of each text portion
                    link_start = text.find(display_text)
                    linkable_start = text.find(linkable_text, link_start)
                    linkable_end = linkable_start + len(linkable_text)
                    
                    # Add format run for text before linkable portion (if any)
                    if linkable_start > link_start:
                        text_format_runs.append({
                            "startIndex": link_start,
                            "format": {}
                        })
                    
                    # Add format run for linkable portion
                    text_format_runs.append({
                        "startIndex": linkable_start,
                        "format": {"link": {"uri": link}}
                    })
                    
                    # Add format run for text after linkable portion (if any)
                    remaining_text_start = linkable_end
                    remaining_text_end = link_start + len(display_text)
                    if remaining_text_start < remaining_text_end:
                        text_format_runs.append({
                            "startIndex": remaining_text_start,
                            "format": {}
                        })

            # Convert cell label to row and column indices
            row, col = gspread.utils.a1_to_rowcol(cell_label)
            
            requests = [{
                "updateCells": {
                    "rows": [{
                        "values": [{
                            "userEnteredValue": {"stringValue": text},
                            "textFormatRuns": text_format_runs
                        }]
                    }],
                    "range": {
                        "sheetId": self._ws.id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col - 1,
                        "endColumnIndex": col
                    },
                    "fields": "*"
                }
            }]
            self._ws.spreadsheet.batch_update({"requests": requests})
        except Exception as e:
            logger.warning(f"Advanced hyperlink formatting failed, falling back to plain text with URLs: {e}")
            # Fall back to plain text with URLs
            plain_text = []
            for item in links_data:
                display_text = item[0]
                link = item[1]
                plain_text.append(f"{display_text} ({link})")
            self._ws.update_acell(cell_label, "\n".join(plain_text))
