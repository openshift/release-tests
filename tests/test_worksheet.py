from unittest import TestCase

from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import WorksheetException
from oar.core.worksheet import WorksheetManager


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
        self.assertRegex(self.report.get_shipment_info(), "129357")
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
