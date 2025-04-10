from unittest import TestCase
from unittest.mock import Mock, patch

from gspread import Spreadsheet
from jira import Issue

from oar.core.jira import JiraManager, JiraIssue

from oar.core.exceptions import WorksheetException
from oar.core.worksheet import WorksheetManager
from oar.core.advisory import AdvisoryManager
from oar.core.worksheet import Worksheet
from oar.core.configstore import ConfigStore
from oar.core.const import *


class TestWorksheetManager(TestCase):
    @classmethod
    def setUpClass(self):
        cs = ConfigStore("4.15.4")
        self.wm = WorksheetManager(cs)
        self.am = AdvisoryManager(cs)

    def test_init(self):
        self.assertRaises(WorksheetException, WorksheetManager, None)
        self.assertRaises(WorksheetException, WorksheetManager, "")

    def step_0_create_report(self):
        self.report = self.wm.create_test_report()
        self.assertRegex(self.report.get_advisory_info(), "129357")
        self.assertRegex(
            self.report.get_build_info(), "4.15.0-0.nightly-2024-03-20-032212"
        )
        self.assertRegex(self.report.get_jira_info(), "ART-9191")

    def step_1_update_overall_status(self):
        self.report.update_overall_status_to_red()
        self.assertEqual(self.report.get_overall_status(), OVERALL_STATUS_RED)
        self.report.update_overall_status_to_green()
        self.assertEqual(self.report.get_overall_status(),
                         OVERALL_STATUS_GREEN)

    def step_2_update_tasks(self):
        task_list = [
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

        for label in task_list:
            self.report.update_task_status(label, TASK_STATUS_INPROGRESS)
            self.assertTrue(self.report.is_task_in_progress(label))

            self.report.update_task_status(label, TASK_STATUS_PASS)
            self.assertTrue(self.report.is_task_pass(label))

            self.report.update_task_status(label, TASK_STATUS_FAIL)
            self.assertTrue(self.report.is_task_fail(label))

            self.report.update_task_status(label, TASK_STATUS_NOT_STARTED)
            self.assertTrue(self.report.is_task_not_started(label))

    def step_3_update_bug_list(self):
        self.wm.get_test_report().update_bug_list(self.am.get_jira_issues())

    def step_4_update_cve_bug_list(self):
        self.wm.get_test_report().append_missed_cve_tracker_bugs(
            ["OCPQE-123", "OCPQE-456"]
        )

    def step_n_delete_report(self):
        self.wm.delete_test_report()

    def test_report(self):
        self.step_0_create_report()
        self.step_1_update_overall_status()
        self.step_2_update_tasks()
        self.step_3_update_bug_list()
        self.step_4_update_cve_bug_list()
        self.step_n_delete_report()

    def test_create_report_for_candidate_release(self):
        wm = WorksheetManager(ConfigStore("4.18.0-rc.8"))
        wm.create_test_report()


class TestTestReport(TestCase):
    @classmethod
    def setUpClass(self):
        self.cs = ConfigStore("4.17.18")
        self.wm = WorksheetManager(self.cs)

    def test_is_cvp_issue_reported(self):
        # Issues containing CVP
        assert self._run_is_cvp_issue_reported([['CVP-x4431'], ['CVP-x4433'], [''], ['OCPBUGS-x1234']])
        # Issues without CVP
        assert not self._run_is_cvp_issue_reported([['OCPBUGS-x1234']])
        # No issues
        assert not self._run_is_cvp_issue_reported([])

    @patch.object(JiraManager, 'get_issue')
    def _run_is_cvp_issue_reported(self, issues_data, mock_get_issue):
        # Prepare spreadsheet mocks
        mock_worksheet = Mock(spec=Worksheet)
        mock_worksheet.get_values.return_value = issues_data
        spreadsheet_mock = Mock(spec=Spreadsheet)
        spreadsheet_mock.worksheet.return_value = mock_worksheet
        self.wm._doc = spreadsheet_mock

        # Prepare jira mocks
        mock_issues = {
            'CVP-x4431': self._mock_issue('CVP-x4431', JiraManager(self.cs).prepare_cvp_issue_summary()),
            'CVP-x4433': self._mock_issue('CVP-x4433', "Another CVP issue"),
            'OCPBUGS-x1234': self._mock_issue('OCPBUGS-x1234', "Some OCP bug")
        }
        mock_get_issue.side_effect = lambda key: JiraIssue(mock_issues.get(key, None))

        self.test_report = self.wm.get_test_report()

        # Execute tested method
        return self.test_report.is_cvp_issue_reported()

    def _mock_issue(self, key, summary):
        mock_issue = Mock(spec=Issue)
        mock_issue.key = key
        mock_field = Mock()
        mock_field.summary = summary
        mock_issue.fields = mock_field

        return mock_issue