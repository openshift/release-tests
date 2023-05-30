import unittest
import sys
from oar.core.notification_mgr import NotificationManager
from oar.core.config_store import ConfigStore
from oar.core.worksheet_mgr import WorksheetManager

class TestNotificationManager(unittest.TestCase):
    def setUp(self):
        self.nm = NotificationManager(ConfigStore("4.12.11"))
        self.cs = ConfigStore("4.12.11")
    def tearDown(self) -> None:
        return super().tearDown()
    
    def test_send_gmail(self):
        self.nm.mc.send_email("wewang@redhat.com", self.cs.get_google_app_passwd())
