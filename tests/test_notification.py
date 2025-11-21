import logging
import unittest
import unittest.mock

import oar.core.util as util
from oar.core.configstore import ConfigStore
from oar.core.notification import NotificationManager, NotificationException
from oar.core.worksheet import WorksheetManager

logging.basicConfig(
    level=logging.DEBUG,  # Set the minimum log level to DEBUG
    format="%(asctime)s - %(levelname)s - %(message)s",  # Format for log messages
)

class TestNotificationManager(unittest.TestCase):
    def setUp(self):
        self.cs = ConfigStore("4.19.14")
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

    def test_shipment_mrs_message_format(self):
        """Test formatting of shipment MR notification message"""
        test_mrs = ["https://git.example.com/mr/1", "https://git.example.com/mr/2"]
        test_owner = "test@example.com"
        
        # Mock group ID lookup
        self.nm.mh.sc.get_group_id_by_name = unittest.mock.Mock(
            return_value="<!subteam^TEST>"
        )
        
        message = self.nm.mh.get_slack_message_for_shipment_mr(test_mrs, test_owner)
        logging.debug("Generated Slack message: %s", message)
        
        # Verify message components
        self.assertIn(test_owner, message)
        for mr in test_mrs:
            self.assertIn(mr, message)
        self.assertIn("QE release lead has been transferred", message)
        self.assertIn("Shipment merge requests", message)

    def test_share_shipment_mrs_success(self):
        """Test successful shipment MR notification posting"""
        test_mrs = ["https://git.example.com/mr/1"]
        test_owner = "test@example.com"
        
        # Mock dependencies
        self.cs.get_shipment_mr_urls = unittest.mock.Mock(return_value=test_mrs)
        self.nm.sc.post_message = unittest.mock.Mock()
        
        self.nm.share_shipment_mr(test_mrs, test_owner)
        
        # Verify Slack client called with formatted message
        self.nm.sc.post_message.assert_called_once_with(
            self.cs.get_slack_channel_from_contact("qe-release"),
            unittest.mock.ANY  # We already validated message format separately
        )
            
    def test_share_shipment_mrs_error(self):
        """Test notification when Slack API fails"""
        test_mrs = ["https://git.example.com/mr/1"]
        test_owner = "test@example.com"
        
        # Mock SlackClient to raise error
        self.nm.sc.post_message = unittest.mock.Mock(
            side_effect=Exception("Slack API error")
        )
        
        with self.assertRaises(Exception):
            self.nm.share_shipment_mr(test_mrs, test_owner)

    def test_get_slack_message_for_unverified_cve_issues_to_managers(self):
        empty_unverified_cve_msg = (
            self.nm.mh.get_slack_message_for_unverified_cve_issues_to_managers([])
        )
        self.assertEqual("", empty_unverified_cve_msg)

        unverified_cve_msg = (
            self.nm.mh.get_slack_message_for_unverified_cve_issues_to_managers(
                [self.nm.mh.jm.get_issue("OCPBUGS-57123")]
            )
        )

        self.assertIn(
            "[4.13.6] The following issues must be verified in this release.",
            unverified_cve_msg,
        )
        self.assertIn(
            "As the managers of the assigned QA contacts who have not yet verified these Jiras,",
            unverified_cve_msg,
        )
        self.assertIn(
            "could you please prioritize their verification or reassign them to other available QA contacts?",
            unverified_cve_msg,
        )
        self.assertIn(
            "<https://issues.redhat.com/browse/OCPBUGS-57123|OCPBUGS-57123> <@",
            unverified_cve_msg,
        )

    def test_share_unverified_cve_issues_to_managers_error(self):
        self.nm.sc.post_message = unittest.mock.Mock(
            side_effect=Exception("Test error exception")
        )

        test_issue = self.nm.mh.jm.get_issue("OCPBUGS-57123")

        with self.assertRaises(NotificationException):
            self.nm.share_unverified_cve_issues_to_managers([test_issue])

        self.nm.sc.post_message.assert_called_once()

    def test_share_drop_bugs_mr_for_approval_success(self):
        """Ensure MR approval request is posted to forum channel with URL"""
        mr_url = "https://gitlab.example.com/mygroup/ocp-shipment-data/-/merge_requests/136"
        # Mock channel mapping and Slack posting
        self.nm.cs.get_slack_channel_from_contact = unittest.mock.Mock(return_value="#forum-ocp-release")
        self.nm.sc.post_message = unittest.mock.Mock()

        self.nm.share_drop_bugs_mr_for_approval(mr_url)

        # Validate channel and message contents
        self.nm.sc.post_message.assert_called_once()
        args, kwargs = self.nm.sc.post_message.call_args
        self.assertEqual(args[0], "#forum-ocp-release")
        self.assertIn(mr_url, args[1])

    def test_share_drop_bugs_mr_for_approval_error(self):
        """Ensure NotificationException is raised when Slack post fails"""
        mr_url = "https://gitlab.example.com/mygroup/ocp-shipment-data/-/merge_requests/999"
        self.nm.cs.get_slack_channel_from_contact = unittest.mock.Mock(return_value="#forum-ocp-release")
        self.nm.sc.post_message = unittest.mock.Mock(side_effect=Exception("Slack failure"))

        with self.assertRaises(NotificationException):
            self.nm.share_drop_bugs_mr_for_approval(mr_url)
