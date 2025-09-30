from datetime import datetime, timedelta, timezone
import os
import unittest

from unittest.mock import Mock

from jira import JIRA

from oar.notificator.jira_notificator import Contact, Notification, NotificationService, NotificationType

class TestJiraNotificator(unittest.TestCase):

    def setUp(self):
        jira_token = os.environ.get("JIRA_TOKEN")
        jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)
        self.ns = NotificationService(jira, True)

        self.test_issue = jira.issue("OCPBUGS-59288", expand="changelog")
        self.test_issue_without_qa = jira.issue("OCPBUGS-8760", expand="changelog")
        self.test_issue_without_assignee = jira.issue("OCPBUGS-1542", expand="changelog")
        self.test_issue_on_qa = jira.issue("OCPBUGS-46472", expand="changelog")

        self.test_user = Mock()
        self.test_user.name = "tdavid"
        self.test_user.displayName = "Tomas David"
        self.test_user.emailAddress = "tdavid@redhat.com"

    def test_create_notification_title(self):
        self.assertEqual(
            self.ns.create_notification_title(NotificationType.QA_CONTACT),
            (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
            )
        )
        self.assertEqual(
            self.ns.create_notification_title(NotificationType.TEAM_LEAD),
            (
                "Errata Reliability Team Notification - Team Lead Action Request\n"
                "This issue has been in the ON_QA state for over 48 hours.\n"
            )
        )
        self.assertEqual(
            self.ns.create_notification_title(NotificationType.MANAGER),
            (
                "Errata Reliability Team Notification - Manager Action Request\n"
                "This issue has been in the ON_QA state for over 72 hours.\n"
            )
        )
        self.assertEqual(
            self.ns.create_notification_title(NotificationType.ASSIGNEE),
            (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
            )
        )

    def test_get_notification_type(self):
        self.assertEqual(self.ns.get_notification_type("QA Contact Action Request"), NotificationType.QA_CONTACT)
        self.assertEqual(self.ns.get_notification_type("Team Lead Action Request"), NotificationType.TEAM_LEAD)
        self.assertEqual(self.ns.get_notification_type("Manager Action Request"), NotificationType.MANAGER)
        self.assertEqual(self.ns.get_notification_type("Assignee Action Request"), NotificationType.ASSIGNEE)
        self.assertEqual(self.ns.get_notification_type("Please verify the issues as soon as possible."), None)
        self.assertEqual(self.ns.get_notification_type("QA Contact Manager Team Lead"), None)
        self.assertEqual(self.ns.get_notification_type(""), None)

    def test_create_jira_comment_mentions(self):
        second_user = Mock()
        second_user.name = "gjospin"

        self.assertEqual(self.ns.create_jira_comment_mentions([]), "")
        self.assertEqual(self.ns.create_jira_comment_mentions([self.test_user]), "[~tdavid] ")
        self.assertEqual(self.ns.create_jira_comment_mentions([self.test_user, second_user]), "[~tdavid] [~gjospin] ")
    
    def test_process_notification(self):
        jira_mock = Mock()
        notification = Notification(self.test_issue, NotificationType.QA_CONTACT, "Hello")

        ns_dry = NotificationService(jira_mock, True)
        ns_dry.process_notification(notification)
        jira_mock.add_comment.assert_not_called()

        ns_live = NotificationService(jira_mock, False)
        ns_live.process_notification(notification)
        jira_mock.add_comment.assert_called_once_with(notification.issue, notification.text)

    def test_add_ert_all_notified_onqa_pending_label(self):
        self.ns.add_ert_all_notified_onqa_pending_label(self.test_issue)
        self.assertEqual(self.test_issue.fields.labels, ["ert-all-notified-onqa-pending"])

    def test_remove_ert_all_notified_onqa_pending_label(self):
        self.ns.remove_ert_all_notified_onqa_pending_label(self.test_issue)
        self.assertEqual(self.test_issue.fields.labels, [])

    def test_find_user_by_email(self):
        self.assertEqual(self.ns.find_user_by_email("tdavid@redhat.com").displayName, "Tomas David")
        self.assertEqual(self.ns.find_user_by_email("dtomas@redhat.com"), None)

    def test_get_qa_contact(self):
        qa_contact = self.ns.get_qa_contact(self.test_issue)
        self.assertEqual(qa_contact.displayName, "Tomas David")
        self.assertEqual(qa_contact.name, "tdavid@redhat.com")

        self.assertEqual(self.ns.get_qa_contact(self.test_issue_without_qa), None)
    
    def test_get_manager(self):
        manager = self.ns.get_manager(self.test_user)
        self.assertEqual(manager.displayName, "Gui Jospin")
        self.assertEqual(manager.name, "rhn-support-gjospin")

        nont_existing_user = Mock()
        nont_existing_user.emailAddress = "dtomas@redhat.com"
        self.assertEqual(self.ns.get_manager(nont_existing_user), None)

    def test_get_assignee(self):
        assignee = self.ns.get_assignee(self.test_issue)
        self.assertEqual(assignee.displayName, "Tomas David")
        self.assertEqual(assignee.name, "tdavid@redhat.com")

        empty_assignee = self.ns.get_assignee(self.test_issue_without_assignee)
        self.assertEqual(empty_assignee, None)

    def test_create_assignee_notification_text(self):
        assignee_manager = Mock()
        assignee_manager.name = "gjospin"

        self.assertEqual(
            self.ns.create_assignee_notification_text(Contact.QA_CONTACT, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] The QA contact is missing. Could you please help us identify someone who could verify the issue?"
        )
        self.assertEqual(
            self.ns.create_assignee_notification_text(Contact.TEAM_LEAD, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] There has been no response from the QA contact and the Team Lead is not listed in Jira. "
            "Could you please help us identify someone who could verify the issue?"
        )
        self.assertEqual(
            self.ns.create_assignee_notification_text(Contact.MANAGER, [self.test_user, assignee_manager]),
            "Errata Reliability Team Notification - Assignee Action Request\n"
            "This issue has been in the ON_QA state for over 24 hours.\n"
            "[~tdavid] [~gjospin] There has been no response from the QA contact and the Manager is not listed in Jira. "
            "Could you please help us identify someone who could verify the issue?"
        )

    def test_has_assignee_notification(self):
        self.assertTrue(self.ns.has_assignee_notification(self.test_issue))
        self.assertFalse(self.ns.has_assignee_notification(self.test_issue_without_qa))
   
    def test_notify_assignees(self):
        self.assertEqual(self.ns.notify_assignees(self.test_issue, Contact.QA_CONTACT), None)
        self.assertEqual(self.ns.notify_assignees(self.test_issue, Contact.TEAM_LEAD), None)
        self.assertEqual(self.ns.notify_assignees(self.test_issue, Contact.MANAGER), None)

        q_notification = self.ns.notify_assignees(self.test_issue_without_qa, Contact.QA_CONTACT)
        self.assertEqual(q_notification.issue, self.test_issue_without_qa)
        self.assertEqual(q_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(q_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] The QA contact is missing. "
                "Could you please help us identify someone who could verify the issue?"
            )
        )
        t_notification = self.ns.notify_assignees(self.test_issue_without_qa, Contact.TEAM_LEAD)
        self.assertEqual(t_notification.issue, self.test_issue_without_qa)
        self.assertEqual(t_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(t_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] "
                "There has been no response from the QA contact and the Team Lead is not listed in Jira. "
                "Could you please help us identify someone who could verify the issue?"
            )
        )
        m_notification = self.ns.notify_assignees(self.test_issue_without_qa, Contact.MANAGER)
        self.assertEqual(m_notification.issue, self.test_issue_without_qa)
        self.assertEqual(m_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(m_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] "
                "There has been no response from the QA contact and the Manager is not listed in Jira. Could you please help us identify someone who could verify the issue?"
            )
        )

        with self.assertRaises(Exception) as context:
            self.ns.notify_assignees(self.test_issue_without_assignee, Contact.QA_CONTACT)
        self.assertEqual(str(context.exception), f"No contact is available. Issue {self.test_issue_without_assignee.key} does not have assignee.")

    def test_create_qa_notification_text(self):
        self.assertEqual(
            self.ns.create_qa_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~tdavid] Please verify the Issue as soon as possible."
            )
        )

    def test_notify_qa_contact(self):
        notification = self.ns.notify_qa_contact(self.test_issue)
        self.assertEqual(notification.issue, self.test_issue)
        self.assertEqual(notification.type, NotificationType.QA_CONTACT)
        self.assertEqual(notification.text, (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~tdavid@redhat.com] Please verify the Issue as soon as possible."
            )
        )

        no_qa_notification = self.ns.notify_qa_contact(self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.issue, self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(no_qa_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] The QA contact is missing. "
                "Could you please help us identify someone who could verify the issue?"
            )
        )

    def test_create_team_lead_notification_text(self):
        self.assertEqual(
            self.ns.create_team_lead_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - Team Lead Action Request\n"
                "This issue has been in the ON_QA state for over 48 hours.\n"
                "[~tdavid] Please verify the Issue as soon as possible or arrange a reassignment with your team lead."
            )
        )

    def test_notify_team_lead(self):
        notification = self.ns.notify_team_lead(self.test_issue)
        self.assertEqual(notification.issue, self.test_issue)
        self.assertEqual(notification.type, NotificationType.TEAM_LEAD)
        self.assertEqual(notification.text, (
                "Errata Reliability Team Notification - Team Lead Action Request\n"
                "This issue has been in the ON_QA state for over 48 hours.\n"
                "[~tdavid@redhat.com] Please verify the Issue as soon as possible or arrange a reassignment with your team lead."
            )
        )

        no_qa_notification = self.ns.notify_team_lead(self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.issue, self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(no_qa_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] The QA contact is missing. "
                "Could you please help us identify someone who could verify the issue?"
            )
        )
    
    def test_create_manager_notification_text(self):
        self.assertEqual(
            self.ns.create_manager_notification_text(self.test_user),
            (
                "Errata Reliability Team Notification - Manager Action Request\n"
                "This issue has been in the ON_QA state for over 72 hours.\n"
                "[~tdavid] Please prioritize the Issue verification or consider reassigning it to another available QA Contact."
            )
        )

    def test_notify_manager(self):
        notification = self.ns.notify_manager(self.test_issue)
        self.assertEqual(notification.issue, self.test_issue)
        self.assertEqual(notification.type, NotificationType.MANAGER)
        self.assertEqual(notification.text, (
                "Errata Reliability Team Notification - Manager Action Request\n"
                "This issue has been in the ON_QA state for over 72 hours.\n"
                "[~rhn-support-gjospin] Please prioritize the Issue verification or consider reassigning it to another available QA Contact."
            )
        )

        no_qa_notification = self.ns.notify_manager(self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.issue, self.test_issue_without_qa)
        self.assertEqual(no_qa_notification.type, NotificationType.ASSIGNEE)
        self.assertEqual(no_qa_notification.text, (
                "Errata Reliability Team Notification - Assignee Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-engineering-scollier] [~fsimonce@redhat.com] The QA contact is missing. "
                "Could you please help us identify someone who could verify the issue?"
            )
        )

    def test_get_latest_on_qa_transition_datetime(self):
        self.assertEqual(
            self.ns.get_latest_on_qa_transition_datetime(self.test_issue),
            datetime(2025, 7, 15, 14, 10, 20, 862000, timezone.utc)
        )
        self.assertEqual(self.ns.get_latest_on_qa_transition_datetime(
            self.test_issue_without_qa),
            None
        )

    def test_get_latest_notification_dates_after_on_qa_transition(self):
        all_notifications = self.ns.get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 9, 0, 0, 0, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.QA_CONTACT), datetime(2025, 7, 17, 11, 8, 46, 381000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.TEAM_LEAD), datetime(2025, 7, 17, 11, 10, 25, 168000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.MANAGER), datetime(2025, 7, 17, 11, 11, 54, 48000, timezone.utc))
        self.assertEqual(all_notifications.get(NotificationType.ASSIGNEE), datetime(2025, 7, 17, 9, 53, 50, 10000, timezone.utc))

        partial_notifications = self.ns.get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 11, 9, 0, 0, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.QA_CONTACT), None)
        self.assertEqual(partial_notifications.get(NotificationType.TEAM_LEAD), datetime(2025, 7, 17, 11, 10, 25, 168000, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.MANAGER), datetime(2025, 7, 17, 11, 11, 54, 48000, timezone.utc))
        self.assertEqual(partial_notifications.get(NotificationType.ASSIGNEE), None)

        none_notifications = self.ns.get_latest_notification_dates_after_on_qa_transition(self.test_issue, datetime(2025, 7, 17, 11, 12, 0, 0, timezone.utc))
        self.assertEqual(len(none_notifications), 0)

    def test_is_more_than_24_weekday_hours(self):
        start = datetime(2025, 7, 22, 10, tzinfo=timezone.utc)
        self.assertFalse(self.ns.is_more_than_24_weekday_hours(start, start + timedelta(hours=23)))
        self.assertFalse(self.ns.is_more_than_24_weekday_hours(start,  start + timedelta(hours=24)))
        self.assertTrue(self.ns.is_more_than_24_weekday_hours(start, start + timedelta(hours=24, minutes=1)))
        self.assertTrue(self.ns.is_more_than_24_weekday_hours(start, start + timedelta(hours=25)))

        friday_start = datetime(2025, 7, 18, 10, tzinfo=timezone.utc)
        self.assertFalse(self.ns.is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 9, tzinfo=timezone.utc)))
        self.assertFalse(self.ns.is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 10, tzinfo=timezone.utc)))
        self.assertTrue(self.ns.is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 10, 1, tzinfo=timezone.utc)))
        self.assertTrue(self.ns.is_more_than_24_weekday_hours(friday_start, datetime(2025, 7, 21, 11, tzinfo=timezone.utc)))

        self.assertFalse(self.ns.is_more_than_24_weekday_hours(datetime.now(timezone.utc) - timedelta(hours=23)))
        self.assertTrue(self.ns.is_more_than_24_weekday_hours(datetime.now(timezone.utc) - timedelta(hours=73)))

    def test_get_on_qa_filter(self):
        self.assertEqual(
            self.ns.get_on_qa_filter(None),
            (
                "project = OCPBUGS AND issuetype in (Bug, Vulnerability) "
                "AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"
            )
        )
        self.assertEqual(
            self.ns.get_on_qa_filter(datetime(2025, 7, 17, tzinfo=timezone.utc)),
            (
                "project = OCPBUGS AND issuetype in (Bug, Vulnerability) "
                "AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"
                " AND status changed to ON_QA after 2025-07-17"
            )
        )

    def test_get_on_qa_issues(self):
        issues = self.ns.get_on_qa_issues(100, None)
        self.assertNotEqual(len(issues), 0)
        for i in issues:
            self.assertTrue(i.key.startswith("OCPBUGS-"))

        issues_after_date = self.ns.get_on_qa_issues(100, datetime(2025, 7, 17, tzinfo=timezone.utc))
        self.assertNotEqual(len(issues_after_date), 0)
        self.assertGreater(len(issues), len(issues_after_date))
        for iad in issues_after_date:
            self.assertTrue(iad.key.startswith("OCPBUGS-"))

    def test_check_issue_and_notify_responsible_people(self):
        self.assertEqual(self.ns.check_issue_and_notify_responsible_people(self.test_issue), None)

        notification = self.ns.check_issue_and_notify_responsible_people(self.test_issue_on_qa)
        self.assertEqual(notification.type, NotificationType.QA_CONTACT)
        self.assertEqual(notification.issue, self.test_issue_on_qa)
        self.assertEqual(notification.text,
            (
                "Errata Reliability Team Notification - QA Contact Action Request\n"
                "This issue has been in the ON_QA state for over 24 hours.\n"
                "[~rhn-support-txue] Please verify the Issue as soon as possible."
            )
        )

    def test_process_on_qa_issues(self):
        day_ago = datetime.now() - timedelta(hours=24)
        self.assertEqual(len(self.ns.process_on_qa_issues(100, day_ago)), 0)

        week_ago = datetime.now() - timedelta(weeks=1)
        self.assertLess(
            len(self.ns.process_on_qa_issues(100, week_ago)), 
            len(self.ns.process_on_qa_issues(100, None))
        )
