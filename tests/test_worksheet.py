from unittest import TestCase
from unittest.mock import patch

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

    def test_create_test_results_links(self):
        tr = self.wm.get_test_report()
        tr.create_test_results_links()

        self.assertEqual("Blocking jobs", tr._ws.acell(LABEL_BLOCKING_TESTS).value)

        self.assertEqual("ocp-test-result-4.15.4", tr._ws.acell(LABEL_BLOCKING_TESTS_RELEASE).value)
        self.assertIn(
            "https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-4.15.4-amd64.json",
            tr._ws.get(LABEL_BLOCKING_TESTS_RELEASE, value_render_option="FORMULA")[0][0],
        )

        self.assertEqual("ocp-test-result-4.15.0-0.nightly-2024-03-20-032212", tr._ws.acell(LABEL_BLOCKING_TESTS_CANDIDATE).value)
        self.assertIn(
            "https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-4.15.0-0.nightly-2024-03-20-032212-amd64.json",
            tr._ws.get(LABEL_BLOCKING_TESTS_CANDIDATE, value_render_option="FORMULA")[0][0],
        )

        self.assertEqual("Sippy", tr._ws.acell(LABEL_SIPPY).value)

        self.assertEqual("4.15-qe-main", tr._ws.acell(LABEL_SIPPY_MAIN).value)
        self.assertIn(
            "https://qe-component-readiness.dptools.openshift.org/sippy-ng/component_readiness/main?view=4.15-qe-main",
            tr._ws.get(LABEL_SIPPY_MAIN, value_render_option="FORMULA")[0][0],
        )

        self.assertEqual("4.15-qe-auto-release", tr._ws.acell(LABEL_SIPPY_AUTO_RELEASE).value)
        self.assertIn(
            "https://qe-component-readiness.dptools.openshift.org/sippy-ng/component_readiness/main?view=4.15-qe-auto-release",
            tr._ws.get(LABEL_SIPPY_AUTO_RELEASE, value_render_option="FORMULA")[0][0],
        )

class TestTestReport(TestCase):
    # testing_test_report spreadsheet ID
    SPREADSHEET_ID = "1DeGMra2o4dA56R_vGtYMcAVRrhXeHLJ9oGOQQTp4nS0"

    @classmethod
    def setUpClass(self):
        cs = ConfigStore("4.15.4")
        with patch.object(cs, "get_report_template", return_value=self.SPREADSHEET_ID):
            self.wm = WorksheetManager(cs)

        self.wm._create_release_sheet_from_template()

    @classmethod
    def tearDownClass(self):
        self.wm.delete_test_report()

    def test_update_advisory_info(self):
        self.wm._report.update_advisory_info()

        advisory_info_from_test_report = self.wm._report.get_advisory_info()
        expected_advisories = [
            "extras: https://errata.devel.redhat.com/advisory/129356",
            "image: https://errata.devel.redhat.com/advisory/129357",
            "metadata: https://errata.devel.redhat.com/advisory/129358",
            "microshift: https://errata.devel.redhat.com/advisory/129359",
            "rpm: https://errata.devel.redhat.com/advisory/129360"
        ]

        for advisory in expected_advisories:
            self.assertIn(advisory, advisory_info_from_test_report)

    def test_blocking_sec_alerts(self):
        """Test blocking sec-alerts functionality in Others column"""
        # Test the essential worksheet methods used by CLI command
        tr = self.wm.get_test_report()

        # Test adding single hyperlinked advisory to Others section
        test_blocking_advisories = [{"errata_id": 12345, "type": "RHSA", "impetus": "image"}]
        result = tr.add_security_alert_status_to_others_section(True, test_blocking_advisories)
        self.assertTrue(result)

        # Test adding multiple hyperlinked advisories to Others section
        test_multiple_advisories = [
            {"errata_id": 12345, "type": "RHSA", "impetus": "image"},
            {"errata_id": 12346, "type": "RHSA", "impetus": "rpm"}
        ]
        result = tr.add_security_alert_status_to_others_section(True, test_multiple_advisories)
        self.assertTrue(result)

        # Test adding "all clear" status when no blocking alerts
        result = tr.add_security_alert_status_to_others_section(False, [])
        self.assertTrue(result)
