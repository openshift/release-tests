import os
import unittest

from unittest.mock import Mock

from tools.jira_notificator import *

class TestJiraNotificator(unittest.TestCase):

    def setUp(self):
        jira_token = os.environ.get("JIRA_TOKEN")
        self.jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)
        self.test_issue = self.jira.issue("OCPBUGS-59288", expand="changelog")
        self.test_issues_without_qa = self.jira.issue("OCPBUGS-8760", expand="changelog")

        self.test_user = Mock()
        self.test_user.name = "tdavid"
        self.test_user.displayName = "Tomas David"
        self.test_user.emailAddress = "tdavid@redhat.com"

    def test_create_notification_title(self):
        self.assertEqual(
            create_notification_title(NotificationType.QA_CONTACT),
            (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
            )
        )
        self.assertEqual(
            create_notification_title(NotificationType.TEAM_LEAD),
            (
                "Errata Reliability Team Notification - Team Lead Action Request\n"
                "This issue has been in the ON_QA state for over 48 hours.\n"
            )
        )
        self.assertEqual(
            create_notification_title(NotificationType.MANAGER),
            (
                "Errata Reliability Team Notification - Manager Action Request\n"
                "This issue has been in the ON_QA state for over 72 hours.\n"
            )
        )
        self.assertEqual(
            create_notification_title(NotificationType.ASSIGNEE),
            (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
            )
        )

    def test_get_notification_type(self):
        self.assertEqual(get_notification_type("QA Contact Action Request"), NotificationType.QA_CONTACT)
        self.assertEqual(get_notification_type("Team Lead Action Request"), NotificationType.TEAM_LEAD)
        self.assertEqual(get_notification_type("Manager Action Request"), NotificationType.MANAGER)
        self.assertEqual(get_notification_type("Assignee Action Request"), NotificationType.ASSIGNEE)
        self.assertEqual(get_notification_type("Please verify the issues as soon as possible."), None)
        self.assertEqual(get_notification_type("QA Contact Manager Team Lead"), None)
        self.assertEqual(get_notification_type(""), None)

    def test_create_jira_comment_mentions(self):
        second_user = Mock()
        second_user.name = "gjospin"

        self.assertEqual(create_jira_comment_mentions([]), "")
        self.assertEqual(create_jira_comment_mentions([self.test_user]), "[~tdavid] ")
        self.assertEqual(create_jira_comment_mentions([self.test_user, second_user]), "[~tdavid] [~gjospin] ")

    def test_process_notification(self):
        jira_mock = Mock()
        notification = Notification(self.test_issue, NotificationType.QA_CONTACT, "Hello")

        process_notification(jira_mock, notification, True)
        jira_mock.add_comment.assert_not_called()

        process_notification(jira_mock, notification, False)
        jira_mock.add_comment.assert_called_once_with(notification.issue, notification.text)

    def test_find_user_by_email(self):
        self.assertEqual(find_user_by_email(self.jira, "tdavid@redhat.com").displayName, "Tomas David")
        self.assertEqual(find_user_by_email(self.jira, "dtomas@redhat.com"), None)

    def test_get_qa_contact(self):
        qa_contact = get_qa_contact(self.test_issue)
        self.assertEqual(qa_contact.displayName, "Tomas David")
        self.assertEqual(qa_contact.name, "tdavid@redhat.com")

        self.assertEqual(get_qa_contact(self.test_issues_without_qa), None)
    
    def test_get_manager(self):
        manager = get_manager(self.jira, self.test_user)
        self.assertEqual(manager.displayName, "Gui Jospin")
        self.assertEqual(manager.name, "rhn-support-gjospin")

        nont_existing_user = Mock()
        nont_existing_user.emailAddress = "dtomas@redhat.com"
        self.assertEqual(get_manager(self.jira, nont_existing_user), None)

    def test_get_assignee(self):
        assignee = get_assignee(self.test_issue)
        self.assertEqual(assignee.displayName, "Tomas David")
        self.assertEqual(assignee.name, "tdavid@redhat.com")

        empty_assignee = get_assignee(self.jira.issue("OCPBUGS-1542"))
        self.assertEqual(empty_assignee, None)

    def test_create_assignee_notification_text(self):
        assignee_manager = Mock()
        assignee_manager.name = "gjospin"

        self.assertEqual(
            create_assignee_notification_text(Contact.QA_CONTACT, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] The QA contact is missing. Could you please help us identify someone who could review the issue?"
        )
        self.assertEqual(
            create_assignee_notification_text(Contact.TEAM_LEAD, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] There has been no response from the QA contact and the Team Lead is not listed in Jira. "
            "Could you please help us identify someone who could review the issue?"
        )
        self.assertEqual(
            create_assignee_notification_text(Contact.MANAGER, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] There has been no response from the QA contact and the Manager is not listed in Jira. "
            "Could you please help us identify someone who could review the issue?"
        )

    def test_has_assignee_notification(self):
        self.assertTrue(has_assignee_notification(self.test_issue))
        self.assertFalse(has_assignee_notification(self.test_issues_without_qa))
    
    @unittest.skip("Skipping because this would send notification to jira.")
    def test_notify_assignees(self):
        notify_assignees(self.jira, self.test_issue, Contact.MANAGER, True)

    def test_create_qa_notification_text(self):
        self.assertEqual(
            create_qa_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~tdavid] Please verify the Issue as soon as possible."
            )
        )

    @unittest.skip("Skipping because this would send notification to jira.")
    def test_notify_qa_contact(self):
        notify_qa_contact(self.jira, self.test_issue, True)

    def test_create_team_lead_notification_text(self):
        self.assertEqual(
            create_team_lead_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - Team Lead Action Request\n"
                "This issue has been in the ON_QA state for over 48 hours.\n"
                "[~tdavid] Please verify the Issue as soon as possible or arrange a reassignment with your team lead."
            )
        )
    
    @unittest.skip("Skipping because this would send notification to jira.")
    def test_notify_team_lead(self):
        notify_team_lead(self.jira, self.test_issue, True)
    
    def test_create_manager_notification_text(self):
        self.assertEqual(
            create_manager_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - Manager Action Request\n"
                "This issue has been in the ON_QA state for over 72 hours.\n"
                "[~tdavid] Please prioritize the Issue verification or consider reassigning it to another available QA Contact."
            )
        )

    @unittest.skip("Skipping because this would send notification to jira.")
    def test_notify_manager(self):
        notify_manager(self.jira, self.test_issue, True)

    def test_get_latest_on_qa_transition_datetime(self):
        self.assertEqual(
            get_latest_on_qa_transition_datetime(self.test_issue),
            datetime(2025, 7, 15, 14, 10, 20, 862000, timezone.utc)
        )
        self.assertEqual(get_latest_on_qa_transition_datetime(
            self.test_issues_without_qa),
            None
        )

    def test_get_latest_notification_dates_after_on_qa_transition(self):
        all_notifications = get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 9, 0, 0, 0, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.QA_CONTACT), datetime(2025, 7, 17, 11, 8, 46, 381000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.TEAM_LEAD), datetime(2025, 7, 17, 11, 10, 25, 168000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.MANAGER), datetime(2025, 7, 17, 11, 11, 54, 48000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.ASSIGNEE), datetime(2025, 7, 17, 9, 53, 50, 10000, timezone.utc))

        partial_notifications = get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 11, 9, 0, 0, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.QA_CONTACT), None)
        self.assertEqual(partial_notifications.get(NotificationType.TEAM_LEAD), datetime(2025, 7, 17, 11, 10, 25, 168000, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.MANAGER), datetime(2025, 7, 17, 11, 11, 54, 48000, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.ASSIGNEE), None)

        none_notifications = get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 11, 12, 0, 0, timezone.utc))
        self.assertEqual(len(none_notifications), 0)

    def test_is_more_than_24_weekday_hours(self):
        start = datetime(2025, 7, 22, 10)
        self.assertFalse(is_more_than_24_weekday_hours(start, start + timedelta(hours=23)))
        self.assertFalse(is_more_than_24_weekday_hours(start,  start + timedelta(hours=24)))
        self.assertTrue(is_more_than_24_weekday_hours(start, start + timedelta(hours=24, minutes=1)))
        self.assertTrue(is_more_than_24_weekday_hours(start, start + timedelta(hours=25)))

        friday_start = datetime(2025, 7, 18, 10)
        self.assertFalse(is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 9)))
        self.assertFalse(is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 10)))
        self.assertTrue(is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 10, 1)))
        self.assertTrue(is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 11)))

        self.assertFalse(is_more_than_24_weekday_hours(datetime.now() - timedelta(hours=23)))
        self.assertTrue(is_more_than_24_weekday_hours(datetime.now() - timedelta(hours=73)))

    def test_get_on_qa_filter(self):
        self.assertEqual(
            get_on_qa_filter(None),
            (
                "project = OCPBUGS AND issuetype in (Bug, Vulnerability) "
                "AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"
            )
        )
        self.assertEqual(
            get_on_qa_filter(datetime(2025, 7, 17)),
            (
                "project = OCPBUGS AND issuetype in (Bug, Vulnerability) "
                "AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"
                " AND status changed to ON_QA after 2025-07-17"
            )
        )

    def test_get_on_qa_issues(self):
        issues = get_on_qa_issues(self.jira, 100, None)
        self.assertNotEqual(len(issues), 0)
        for i in issues:
            self.assertTrue(i.key.startswith("OCPBUGS-"))

        issues_after_date = get_on_qa_issues(self.jira, 100, datetime(2025, 7, 17))
        self.assertNotEqual(len(issues_after_date), 0)
        self.assertGreater(len(issues), len(issues_after_date))
        for iad in issues_after_date:
            self.assertTrue(iad.key.startswith("OCPBUGS-"))
