import unittest
import sys
from oar.core.notification import NotificationManager
from oar.core.configstore import ConfigStore
from oar.core.worksheet import WorksheetManager
from oar.core.worksheet import TestReport


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
        must_verify_bugs = ["OCPQE-911"]
        self.nm.share_dropped_and_must_verify_bugs(dropped_bugs, must_verify_bugs)
        must_verify_bugs = []
        self.nm.share_dropped_and_must_verify_bugs(dropped_bugs, must_verify_bugs)
        dropped_bugs = []
        must_verify_bugs = ["OCPQE-911"]
        self.nm.share_dropped_and_must_verify_bugs(dropped_bugs, must_verify_bugs)

    @unittest.skip("disabled by default, avoid message flood")
    def test_share_new_report(self):
        cs = ConfigStore("4.14.9")
        wm = WorksheetManager(cs)
        nm = NotificationManager(cs)
        nm.share_new_report(wm.get_test_report())
