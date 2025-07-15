import os
import unittest

from unittest.mock import Mock

from tools.jira_notificator import *

class TestJiraNotificator(unittest.TestCase):

    def setUp(self):
        jira_token = os.environ.get("JIRA_TOKEN")
        self.jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)
    
    def test_notification_type(self):
        self.assertEqual(get_notification_type("QA Contact Action Request"), NotificationType.QA_CONTACT)
        self.assertEqual(get_notification_type("Team Lead Action Request"), NotificationType.TEAM_LEAD)
        self.assertEqual(get_notification_type("Manager Action Request"), NotificationType.MANAGER)
        self.assertEqual(get_notification_type("Please verify the issues as soon as possible."), None)
        self.assertEqual(get_notification_type(""), None)

    def test_get_qa_contact(self):
        issue = self.jira.issue("OCPBUGS-59288", expand="changelog")
        qa_contact = get_qa_contact(issue)
        self.assertEqual(qa_contact.displayName, "Tomas David")
        self.assertEqual(qa_contact.name, "tdavid@redhat.com")

        issues_without_qa = self.jira.issue("OCPBUGS-8760", expand="changelog")
        self.assertEqual(get_qa_contact(issues_without_qa), None)

    def test_get_manager(self):
        qa_contact = Mock()
        qa_contact.emailAddress = "tdavid@redhat.com"
        manager = get_manager(self.jira, qa_contact)
        self.assertEqual(manager.displayName, "Gui Jospin")
        self.assertEqual(manager.name, "rhn-support-gjospin")

        invalid_user = Mock()
        invalid_user.emailAddress = "dtomas@redhat.com"
        self.assertEqual(get_manager(self.jira, invalid_user), None)

    def test_find_user_by_email(self):
        self.assertEqual(find_user_by_email(self.jira, "tdavid@redhat.com").displayName, "Tomas David")
        self.assertEqual(find_user_by_email(self.jira, "dtomas@redhat.com"), None)
    

    def test_create_notification_prefix(self):
        self.assertEqual(
            create_notification_prefix(NotificationType.QA_CONTACT),
            "Errata Reliability Team Notification - QA Contact Action Request: This issue has been in the ON_QA state for over 24 hours."
        )
        self.assertEqual(
            create_notification_prefix(NotificationType.TEAM_LEAD),
            "Errata Reliability Team Notification - Team Lead Action Request: This issue has been in the ON_QA state for over 48 hours."
        )
        self.assertEqual(
            create_notification_prefix(NotificationType.MANAGER),
            "Errata Reliability Team Notification - Manager Action Request: This issue has been in the ON_QA state for over 72 hours."
        )

    def test_create_qa_notification_text(self):
        self.assertEqual(
            create_qa_notification_text(self.jira.issue("OCPBUGS-59288", expand="changelog")),
            (
                "Errata Reliability Team Notification - QA Contact Action Request: This issue has been in the ON_QA state for over 24 hours. "
                "[~tdavid@redhat.com] Please verify the Jira as soon as possible."
            )
        )
        self.assertEqual(
            create_qa_notification_text(self.jira.issue("OCPBUGS-8760", expand="changelog")),
            (
                "Errata Reliability Team Notification - QA Contact Action Request: This issue has been in the ON_QA state for over 24 hours. "
                "Please verify the Jira as soon as possible."
            )
        )
    
    def test_create_team_lead_notification_text(self):
        self.assertEqual(
            create_team_lead_notification_text(self.jira.issue("OCPBUGS-59288", expand="changelog")),
            (
                "Errata Reliability Team Notification - Team Lead Action Request: This issue has been in the ON_QA state for over 48 hours. "
                "[~tdavid@redhat.com] Please verify the Jira as soon as possible or arrange a reassignment with your team lead."
            )
        )
        self.assertEqual(
            create_team_lead_notification_text(self.jira.issue("OCPBUGS-8760", expand="changelog")),
            (
                "Errata Reliability Team Notification - Team Lead Action Request: This issue has been in the ON_QA state for over 48 hours. "
                "Please verify the Jira as soon as possible or arrange a reassignment with your team lead."
            )
        )
    
    def test_create_manager_notification_text(self):
        self.assertEqual(
            create_manager_notification_text(self.jira, self.jira.issue("OCPBUGS-59288", expand="changelog")),
            (
                "Errata Reliability Team Notification - Manager Action Request: This issue has been in the ON_QA state for over 72 hours. "
                "[~rhn-support-gjospin] Please prioritize the verification or consider reassigning it to another available QA Contact."
            )
        )
        self.assertEqual(
            create_manager_notification_text(self.jira, self.jira.issue("OCPBUGS-8760", expand="changelog")),
            (
                "Errata Reliability Team Notification - Manager Action Request: This issue has been in the ON_QA state for over 72 hours. "
                "Please prioritize the verification or consider reassigning it to another available QA Contact."
            )
        )

    def test_get_on_qa_issues(self):
        issues = get_on_qa_issues(self.jira)
        self.assertNotEqual(len(issues), 0)
        for i in issues:
            self.assertTrue(i.key.startswith("OCPBUGS-"))
