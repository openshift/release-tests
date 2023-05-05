import unittest
from oar.core.exceptions import WorksheetException
from oar.core.worksheet_mgr import WorksheetManager
from oar.core.worksheet_mgr import TestReport
from oar.core.config_store import ConfigStore
from oar.core.const import *


class TestWorksheetManager(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.wm = WorksheetManager(ConfigStore("4.12.11"))

    def test_init(self):
        self.assertRaises(WorksheetException, WorksheetManager, None)
        self.assertRaises(WorksheetException, WorksheetManager, "")

    def step_0_create_report(self):
        self.report = self.wm.create_test_report()
        self.assertRegex(self.report.get_advisory_info(), "112393")
        self.assertRegex(
            self.report.get_build_info(), "4.12.0-0.nightly-2023-04-04-050651"
        )
        self.assertRegex(self.report.get_jira_info(), "ART-6489")

    def step_1_update_overall_status(self):
        self.report.update_overall_status_to_red()
        self.assertEqual(self.report.get_overall_status(), OVERALL_STATUS_RED)
        self.report.update_overall_status_to_green()
        self.assertEqual(self.report.get_overall_status(), OVERALL_STATUS_GREEN)

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

    def step_n_delete_report(self):
        self.wm.delete_test_report()

    def test_report(self):
        self.step_0_create_report()
        self.step_1_update_overall_status()
        self.step_2_update_tasks()
        # self.step_n_delete_report()
