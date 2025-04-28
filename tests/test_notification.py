import logging
import unittest

import oar.core.util as util
from oar.core.configstore import ConfigStore
from oar.core.notification import NotificationManager
from oar.core.worksheet import WorksheetManager

logging.basicConfig(
    level=logging.DEBUG,  # Set the minimum log level to DEBUG
    format="%(asctime)s - %(levelname)s - %(message)s",  # Format for log messages
)

class TestNotificationManager(unittest.TestCase):
    def setUp(self):
        self.cs = ConfigStore("4.13.6")
        self.nm = NotificationManager(self.cs)

    @unittest.skip
    def test_send_gmail(self):
        self.nm.mc.send_email(
            self.cs.get_email_contact("trt"), self.cs.get_google_app_passwd()
        )

    def test_get_slack_group_id(self):
        gid = self.nm.sc.get_group_id_by_name("openshift-qe")
        self.assertTrue(gid.startswith("<!subteam"))

    def test_get_slack_group_id_from_cache(self):
        groupidlist = ["openshift-qe","openshift-qe","openshift-qe"]
        for groupid in groupidlist:
            gid = self.nm.sc.get_group_id_by_name(groupid)
            self.assertTrue(gid.startswith("<!subteam"))

    def test_get_slack_user_id(self):
        uid = self.nm.sc.get_user_id_by_email("rioliu@redhat.com")
        self.assertTrue(uid.startswith("<@"))

    def test_get_slack_user_id_from_cache(self):
        emaillist = ["rioliu@redhat.com","jhuttana@redhat.com","rioliu@redhat.com","rioliu@redhat.com"]
        for emailid in emaillist:
            uid = self.nm.sc.get_user_id_by_email(emailid)
            self.assertTrue(uid.startswith("<@"))

    def test_share_dropped_bugs(self):
        dropped_bugs = ["OCPQE-123", "OCPQE-456", "OCPQE-789"]
        high_severity_bugs = ["OCPQE-911"]
        self.nm.share_dropped_and_high_severity_bugs(dropped_bugs, high_severity_bugs)
        high_severity_bugs = []
        self.nm.share_dropped_and_high_severity_bugs(dropped_bugs, high_severity_bugs)
        dropped_bugs = []
        high_severity_bugs = ["OCPQE-911"]
        self.nm.share_dropped_and_high_severity_bugs(dropped_bugs, high_severity_bugs)

    @unittest.skip("disabled by default, avoid message flood")
    def test_share_new_report(self):
        cs = ConfigStore("4.14.9")
        wm = WorksheetManager(cs)
        nm = NotificationManager(cs)
        nm.share_new_report(wm.get_test_report())

    def test_get_qe_release_slack(self):
        gid = self.nm.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )
        self.assertTrue(gid.startswith("<!subteam"))

    def test_get_slack_message_for_bug_verification(self):
        """Test the formatting of Slack messages for bug verification requests."""
        # Test with CVE tracker issues
        test_issues = ["OCPBUGS-53509"]
        msg = self.nm.mh.get_slack_message_for_bug_verification(test_issues)

        # Verify message contains required components
        for issue in test_issues:
            self.assertIn(issue, msg)

        # Verify message format
        self.assertIn("Please pay attention to following ON_QA bugs", msg)
        self.assertIn("let's verify them ASAP", msg)
        self.assertIn("thanks for your cooperation", msg)
        self.assertIn("This is a CVE bug and must be verified", msg)
