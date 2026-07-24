import unittest
from unittest.mock import Mock, patch, call

from click.testing import CliRunner

from oar.core.advisory import Advisory
from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.const import (
    AD_STATUS_DROPPED_NO_SHIP,
    TASK_CHECK_BLOCKING_SEC_ALERTS,
    TASK_STATUS_FAIL,
    TASK_STATUS_PASS,
)
from oar.core.exceptions import StateBoxException
from oar.cli.cmd_check_blocking_sec_alerts import check_blocking_sec_alerts


class TestAdvisoryManager(unittest.TestCase):
    def setUp(self):
        self.am = AdvisoryManager(ConfigStore("4.19.10"))

    def test_init(self):
        pass

    def test_get_jira_issues(self):
        jira_issues = self.am.get_jira_issues()
        self.assertIn("OCPBUGS-10973", jira_issues)
        self.assertIn("OCPBUGS-10225", jira_issues)

    @unittest.skip("disable this case, will not update released advisory")
    def test_change_qe_owner(self):
        self.am.change_ad_owners()
        for ad in self.am.get_advisories():
            self.assertEqual(ad.get_qe_email(), "xx@redhat.com")

    def test_check_greenwave_cvp_test(self):
        abnormal_tests = self.am.check_greenwave_cvp_tests()
        self.assertTrue(len(abnormal_tests) == 0)

    def test_push_to_cdn(self):
        self.am.push_to_cdn_staging()

    @unittest.skip("disable this case by default")
    def test_change_ad_status(self):
        self.am.change_advisory_status("REL_PREP")

    @unittest.skip("disable this case by default")
    def test_drop_bugs(self):
        self.am.drop_bugs()

    def test_check_cve_tracker_bug(self):
        tracker_bugs = self.am.check_cve_tracker_bug()
        self.assertFalse(tracker_bugs)

    @unittest.skip("disable this case by default")
    def test_get_doc_security_approved_ads(self):
        doc_appr, prodsec_appr = self.am.get_doc_security_approved_ads()
        self.assertTrue(len(doc_appr) == 2)
        self.assertTrue(len(prodsec_appr) == 0)

    def test_get_dependent_advisories(self):
        ad_id = 121862
        dependent_ad_id = 121861
        ad = Advisory(errata_id=ad_id)
        self.assertTrue(ad.has_dependency())
        self.assertEqual(ad.get_dependent_advisories()[
                         0].errata_id, dependent_ad_id)

    def test_check_ad_state(self):
        self.me = AdvisoryManager(ConfigStore("4.13.15"))
        ads = self.me.get_advisories()
        for ad in ads:
            self.assertNotEqual(ad.errata_state, AD_STATUS_DROPPED_NO_SHIP,
                                "AD with DROPPED NO SHIP hasn't been filtered out")

    def test_get_security_alerts(self):
        self.me = AdvisoryManager(ConfigStore("4.12.61"))
        ads = self.me.get_advisories()
        for ad in ads:
            self.assertFalse(ad.has_blocking_security_alert(), f"advisory {ad.errata_id} has blocking security alerts")

    def test_kernel_tag(self):
        self.assertTrue(Advisory(errata_id=144853, impetus='image').check_kernel_tag())
        self.assertFalse(Advisory(errata_id=144854, impetus='metadata').check_kernel_tag())
        self.assertFalse(Advisory(errata_id=146595, impetus='image').check_kernel_tag())
        self.assertFalse(Advisory(errata_id=153980, impetus='rhcos').check_kernel_tag())
    
    def test_finished_jiras(self):
        self.assertTrue(self.am.has_finished_all_advisories_jiras())


class TestCheckBlockingSecAlerts(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.mock_cs = Mock(spec=ConfigStore)

    def _make_advisory(self, errata_id, errata_type, has_blocking=False, raises=None):
        ad = Mock()
        ad.errata_id = errata_id
        ad.errata_type = errata_type
        if raises:
            ad.has_blocking_security_alert.side_effect = raises
        else:
            ad.has_blocking_security_alert.return_value = has_blocking
        return ad

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_no_blocking_alerts(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(11111, "RHSA", has_blocking=False),
        ]
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)
        mock_sb_cls.return_value.add_issue.assert_not_called()

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_blocking_alert_found(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_util.get_advisory_link.return_value = "https://errata.devel.redhat.com/advisory/11111"
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(11111, "RHSA", has_blocking=True),
        ]
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        mock_sb_cls.return_value.add_issue.assert_called_once()
        call_kwargs = mock_sb_cls.return_value.add_issue.call_args
        self.assertTrue(call_kwargs[1]["blocker"])
        self.assertIn(TASK_CHECK_BLOCKING_SEC_ALERTS, call_kwargs[1]["related_tasks"])

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_no_rhsa_advisories(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(22222, "RHBA"),
        ]
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)
        mock_sb_cls.return_value.add_issue.assert_not_called()

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_all_checks_fail_with_exception(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(33333, "RHSA", raises=ConnectionError("Errata API unreachable")),
        ]
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        mock_sb_cls.return_value.add_issue.assert_not_called()

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_mixed_success_and_error_fails(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(11111, "RHSA", has_blocking=False),
            self._make_advisory(22222, "RHSA", raises=ConnectionError("Errata API unreachable")),
        ]
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)

    @patch('oar.cli.cmd_check_blocking_sec_alerts.util')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.StateBox')
    @patch('oar.cli.cmd_check_blocking_sec_alerts.AdvisoryManager')
    def test_statebox_add_issue_raises(self, mock_am_cls, mock_sb_cls, mock_util):
        mock_util.get_advisory_link.return_value = "https://errata.devel.redhat.com/advisory/44444"
        mock_am_cls.return_value.get_advisories.return_value = [
            self._make_advisory(44444, "RHSA", has_blocking=True),
        ]
        mock_sb_cls.return_value.add_issue.side_effect = StateBoxException("duplicate blocker")
        result = self.runner.invoke(check_blocking_sec_alerts, obj={"cs": self.mock_cs}, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        mock_util.log_task_status.assert_any_call(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)

