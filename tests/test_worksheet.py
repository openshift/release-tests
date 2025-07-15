from unittest import TestCase
from gspread_formatting import get_text_format_runs
import time
import json

from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import WorksheetException
from oar.core.worksheet import WorksheetManager
from oar.core.worksheet import TestReport


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
    """Dedicated test class for TestReport functionality"""
    
    @classmethod
    def setUpClass(self):
        """Create test worksheet before all tests"""
        self.cs = ConfigStore("4.19.2")
        self.wm = WorksheetManager(self.cs)
        self.test_sheet_title = "test-hyperlinks-" + str(int(time.time()))
        self.ws = self.wm._doc.add_worksheet(title=self.test_sheet_title, rows=100, cols=20)
        self.tr = TestReport(self.ws, self.cs)

    @classmethod
    def tearDownClass(self):
        """Clean up test worksheet after all tests"""
        self.wm._doc.del_worksheet(self.ws)

    def test_update_cell_with_hyperlinks(self):
        """Test basic hyperlink functionality"""
        # test data
        mr_url = "https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/31"
        rpm_advisory = "149403"
        
        self.tr.update_shipment_info([mr_url], rpm_advisory)
        # verify the cell content
        info = self.tr.get_shipment_info()
        self.assertIn(mr_url, info)
        self.assertIn(f"rpm: {rpm_advisory}", info)

    def test_update_cell_with_multiple_hyperlinks(self):
        """Test multiple hyperlinks in one cell"""
        # Test data with multiple links
        links_data = [
            ("Click here", "https://example.com/1"),
            ("And here", "https://example.com/2"),
            ("Also here", "https://example.com/3")
        ]
        
        self.tr.update_cell_with_hyperlinks("A1", links_data)
        cell_value = self.ws.acell("A1").value
        for text, _ in links_data:
            self.assertIn(text, cell_value)

    def test_partial_text_hyperlinking(self):
        """Test hyperlinking only part of the text"""
        # Link only the word "here" in the text
        links_data = [
            ("Click here for details", "https://example.com", "here")
        ]
        
        self.tr.update_cell_with_hyperlinks("B2", links_data)
        
        # Verify cell text content
        cell_value = self.ws.acell("B2").value
        self.assertEqual("Click here for details", cell_value)

        # Verify format runs
        format_runs = get_text_format_runs(self.ws, "B2")
        found_link = False
        for run in format_runs:
            if run.startIndex == 6:  # Position of "here"
                self.assertTrue(hasattr(run.format, 'link'))
                self.assertEqual(run.format.link.uri, "https://example.com")
                found_link = True
        self.assertTrue(found_link, "No format run found for hyperlinked text")

    def test_format_runs_hyperlinking(self):
        """Test hyperlinking with format runs"""
        # Test data with format runs
        links_data = [
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
        
        self.tr.update_cell_with_hyperlinks("C3", links_data)
        
        # Verify text content
        cell_value = self.ws.acell("C3").value
        self.assertEqual("Important: Click here", cell_value)

        # Verify format runs
        format_runs = get_text_format_runs(self.ws, "C3")
        
        # Verify bold formatting at start
        found_bold = False
        found_link = False
        for run in format_runs:
            if run.startIndex == 0:
                self.assertTrue(hasattr(run.format, 'bold'))
                self.assertTrue(run.format.bold)
                found_bold = True
            elif run.startIndex == 10:  # Position of "here"
                self.assertTrue(hasattr(run.format, 'link'))
                self.assertEqual(run.format.link.uri, "https://example.com")
                found_link = True
                
        self.assertTrue(found_bold, "Bold format not found at start")
        self.assertTrue(found_link, "Hyperlink format not found at position 10")

    def test_invalid_hyperlink_inputs(self):
        """Test error handling for invalid inputs"""
        # Test None input
        with self.assertRaises(WorksheetException):
            self.tr.update_cell_with_hyperlinks("D4", None)

        # Test non-list input
        with self.assertRaises(WorksheetException):
            self.tr.update_cell_with_hyperlinks("D4", "invalid")

        # Test empty list
        with self.assertRaises(WorksheetException):
            self.tr.update_cell_with_hyperlinks("D4", [])

    def test_hyperlink_fallback_solution(self):
        """Test fallback to simple HYPERLINK when advanced formatting fails"""
        # Setup test data
        links_data = [
            ("Test link", "https://example.com"),
            ("Another link", "https://example.org")
        ]
        
        # Mock the advanced formatting to fail by raising an exception
        original_batch_update = self.ws.spreadsheet.batch_update
        def mock_batch_update(*args, **kwargs):
            raise Exception("Simulated advanced formatting failure")
        self.ws.spreadsheet.batch_update = mock_batch_update
        
        # Capture log output
        with self.assertLogs('oar.core.worksheet', level='WARNING') as cm:
            self.tr.update_cell_with_hyperlinks("E5", links_data)
            
            # Verify warning was logged about fallback
            self.assertIn("Advanced hyperlink formatting failed, falling back to simple HYPERLINK", cm.output[0])
        
        # Restore original method
        self.ws.spreadsheet.batch_update = original_batch_update
        
        # Verify fallback worked - cell should contain simple HYPERLINK formulas
        cell_value = self.ws.acell("E5", value_render_option="FORMULA").value
        for text, link in links_data:
            expected_hyperlink = f'=HYPERLINK("{link}","{text}")'
            self.assertIn(expected_hyperlink, cell_value)
