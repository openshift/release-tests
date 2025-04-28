import unittest
import logging
import sys
from oar.core.notification import *
from oar.core.configstore import ConfigStore
from oar.core.worksheet import WorksheetManager
from oar.core.worksheet import TestReport
from oar.core.advisory import AdvisoryManager
import oar.core.util as util

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
        cs = ConfigStore("4.17.27")
        am = AdvisoryManager(cs)
        mh = MessageHelper(cs)
        mh.get_slack_message_for_bug_verification(am.get_jira_issues())
