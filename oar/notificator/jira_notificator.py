import click
import logging
import os

from enum import Enum
from typing import List, Optional, Dict
from jira import JIRA, Issue
from jira.resources import User
from datetime import datetime, timedelta, timezone
from dateutil import parser
from oar.core.jira import JiraIssue
from oar.core.ldap import LdapHelper

logger = logging.getLogger(__name__)

ERT_NOTIFICATION_PREFIX = "Errata Reliability Team Notification"
ERT_ALL_NOTIFIED_ONQA_PENDING_LABEL = "ert:pending-onqa-over-96hrs"

class NotificationType(Enum):
    """
    Enum representing different types of notifications with associated hours and labels.
    """

    QA_CONTACT = (24, "QA Contact Action Request")
    TEAM_LEAD = (48, "Team Lead Action Request")
    MANAGER = (72, "Manager Action Request")
    ASSIGNEE = (24, "Assignee Action Request")

    def __init__(self, hours: int, label: str):
        self.hours = hours
        self.label = label

class Contact(Enum):
    """
    Enum representing different contact roles.
    """

    QA_CONTACT = "QA Contact"
    TEAM_LEAD = "Team Lead"
    MANAGER = "Manager"

class Notification:
    """
    Represents a notification related to a JIRA issue.

    Attributes:
        issue (Issue): The JIRA issue associated with the notification.
        type (NotificationType): The type of notification.
        text (str): The notification message text.
    """

    issue: Issue
    type: NotificationType
    text: str

    def __init__(self, issue, type, text):
        self.issue = issue
        self.type = type
        self.text = text

class NotificationService:
    """
    Represents a service for sending notifications via the Jira API.
    
    Attributes:
        jira (JIRA): JIRA API client instance.
        dry_run (bool): If True, logs the action without sending comments to Jira.
    """
    
    def __init__(self, jira, dry_run=False):
        self.jira = jira
        self.dry_run = dry_run
        self.ldap = LdapHelper()

    def create_notification_title(self, notification_type: NotificationType) -> str:
        """
        Returns a formatted notification title based on the given type.

        Args:
            notification_type (NotificationType): The type of notification.

        Returns:
            str: A string with the notification title and time information.
        """

        return (
            f"{ERT_NOTIFICATION_PREFIX} - {notification_type.label}\n"
            f"This issue has been in the ON_QA state for over {notification_type.hours} hours.\n"
        )

    def get_notification_type(self, notification_message: str) -> Optional[NotificationType]:
        """
        Extracts the notification type from a message string.

        Args:
            notification_message (str): The message to search.

        Returns:
            Optional[NotificationType]: The matching notification type, or None if not found.
        """
        
        for notification_type in NotificationType:
            if notification_type.label in notification_message:
                return notification_type
        return None

    def create_jira_comment_mentions(self, users: List[User]) -> str:
        """
        Creates a Jira-formatted mention string for a list of users.

        Args:
            users (List[User]): List of users to mention.

        Returns:
            str: A string with Jira mentions (e.g., "[~user1] [~user2]").
        """

        jira_comment_mentions = ""
        for u in users:
            jira_comment_mentions += f"[~{u.name}] "
        return jira_comment_mentions

    def process_notification(self, notification: Notification) -> None:
        """
        Sends or logs a notification as a JIRA comment.

        Args:
            notification (Notification): The notification to process.
        """

        log_message = f"- {notification.type.label} - notification to Issue - {notification.issue.key}: {notification.text}"
        if not self.dry_run:
            logger.info(f"Sending {log_message}")
            self.jira.add_comment(notification.issue, notification.text)
        else:
            logger.info(f"Skipping sending {log_message}")
            
    def add_ert_all_notified_onqa_pending_label(self, issue: Issue) -> None:
        """
        Adds the ON_QA pending label to the issue.

        Args:
            issue (Issue): The JIRA issue to add the label to.
        """

        current_labels = issue.fields.labels
        if ERT_ALL_NOTIFIED_ONQA_PENDING_LABEL not in current_labels:
            current_labels.append(ERT_ALL_NOTIFIED_ONQA_PENDING_LABEL)
            issue.update(fields={"labels": current_labels})
            logger.info(f"ON_QA pending label added to the issue {issue.key}.")
        else:
            logger.info(f"ON_QA pending label already exists on the issue {issue.key}.")

    def remove_ert_all_notified_onqa_pending_label(self, issue: Issue) -> None:
        """
        Removes the ON_QA pending label from the issue.

        Args:
            issue (Issue): The JIRA issue to remove the label from.
        """

        current_labels = issue.fields.labels
        if ERT_ALL_NOTIFIED_ONQA_PENDING_LABEL in current_labels:
            current_labels.remove(ERT_ALL_NOTIFIED_ONQA_PENDING_LABEL)
            issue.update(fields={"labels": current_labels})
            logger.info(f"ON_QA pending label removed from the issue {issue.key}.")
        else:
            logger.info(f"ON_QA pending label does not exist on the issue {issue.key}.")
            
    def find_user_by_email(self, email: str) -> Optional[User]:
        """
        Searches for a JIRA user by email address.

        Args:
            email (str): Email address to search for.

        Returns:
            Optional[User]: The matched user if found, otherwise None.
        """

        for user in self.jira.search_users(user=email):
            if user.emailAddress == email:
                return user
        logger.warning(f"User was not found for email {email}.")
        return None

    def get_qa_contact(self, issue: Issue) -> Optional[User]:
        """
        Retrieves the QA contact user from an issue.

        Args:
            issue (Issue): The JIRA issue to inspect.

        Returns:
            Optional[User]: The QA contact user if set, otherwise None.
        """

        qa_contact = issue.fields.customfield_12315948
        if qa_contact:
            return qa_contact
        else:
            logger.warning(f"Issue {issue.key} does not have a QA contact.")
            return None

    def get_manager(self, user: User) -> Optional[User]:
        """
        Retrieves the manager of a given user via LDAP and matches them in JIRA.

        Args:
            user (User): The user whose manager is to be found.

        Returns:
            Optional[User]: The manager user if found, otherwise None.
        """

        manager_email = self.ldap.get_manager_email(user.emailAddress)
        if manager_email:
            manager = self.find_user_by_email(manager_email)
            if manager:
                return manager
            else:
                logger.warning(f"Manager {manager_email} was not found in Jira.")
        else:
            logger.warning(f"Manager of {user.emailAddress} was not found in LDAP.")
        return None

    def get_assignee(self, issue: Issue) -> Optional[User]:
        """
        Retrieves the assignee user from an issue.

        Args:
            issue (Issue): The JIRA issue to inspect.

        Returns:
            Optional[User]: The assignee user if set, otherwise None.
        """

        assignee = issue.fields.assignee
        if assignee:
            return assignee
        else:
            logger.warning(f"Issue {issue.key} does not have an Assignee.")
            return None

    def add_user_to_need_info_from(self, issue: Issue, user: User) -> None:
        """
        Adds a user to the need info from field.

        Args:
            issue (Issue): The JIRA issue to add the user to.
            user (User): The user to add to the need info from field.
        """
        if self.dry_run:
            logger.info(f"Skipping adding {user.emailAddress} to need info from field. Issue {issue.key}.")
        else:
            logger.info(f"Adding {user.emailAddress} to need info from field. Issue {issue.key}.")
            jira_issue = JiraIssue(issue)
            need_info_from = jira_issue.get_need_info_from() or []
            updated_users = [u.raw for u in need_info_from]
            updated_users.append(user.raw)
            jira_issue.set_need_info_from(updated_users)

    def create_assignee_notification_text(self, missing_contact: Contact, notified_assignees: list[User]) -> str:
        """
        Creates a notification text for assignees when a contact is missing.

        Args:
            missing_contact (Contact): The type of missing contact.
            notified_assignees (list[User]): List of users to be notified.

        Returns:
            str: The complete notification message text.
        """

        message = ""
        if missing_contact == Contact.QA_CONTACT:
            message = f"The QA contact is missing."
        elif missing_contact == Contact.TEAM_LEAD or missing_contact == Contact.MANAGER:
            message = f"There has been no response from the QA contact and the {missing_contact.value} is not listed in Jira."
        else:
            raise ValueError(f"Unknown Contact value: {missing_contact}.")
        
        return (
            f"{self.create_notification_title(NotificationType.ASSIGNEE)}"
            f"{self.create_jira_comment_mentions(notified_assignees)}"
            f"{message} Could you please help us identify someone who could verify the issue?"
        )

    def has_assignee_notification(self, issue: Issue) -> bool:
        """
        Checks if the issue already contains an assignee notification comment.

        Args:
            issue (Issue): The JIRA issue to inspect.

        Returns:
            bool: True if an assignee notification comment is found, False otherwise.
        """

        for comment in issue.fields.comment.comments:
            if comment.body.startswith(self.create_notification_title(NotificationType.ASSIGNEE)):
                return True
        return False

    def notify_assignees(self, issue: Issue, missing_contact: Contact) -> Optional[Notification]:
        """
        Notifies assignees about a missing contact on an issue, if not already notified.

        Args:
            issue (Issue): The issue related to the notification.
            missing_contact (Contact): The type of missing contact triggering the notification.

        Returns:
            Optional[Notification]: The created notification if sent, otherwise None.

        Raises:
            Exception: If no assignee is available on the issue.
        """

        if not self.has_assignee_notification(issue):
            assignee = self.get_assignee(issue)
            if assignee:
                notified_assignees = [assignee]
                assignee_manager = self.get_manager(assignee)
                self.add_user_to_need_info_from(issue, assignee)
                if assignee_manager:
                    notified_assignees.append(assignee_manager)
                    self.add_user_to_need_info_from(issue, assignee_manager)
                assignee_notification = Notification(
                    issue, 
                    NotificationType.ASSIGNEE, 
                    self.create_assignee_notification_text(missing_contact, notified_assignees)
                )
                self.process_notification(assignee_notification)
                return assignee_notification
            else:
                raise Exception(f"No contact is available. Issue {issue.key} does not have assignee.")
        else:
            logger.warning(f"Assignees have already been notified about the missing {missing_contact.value} contact.")
        return None

    def create_qa_notification_text(self, qa_contact: User) -> str:
        """
        Creates a notification text for the QA contact to verify the issue.

        Args:
            qa_contact (User): The QA contact user.

        Returns:
            str: The complete notification message text.
        """

        return (
            f"{self.create_notification_title(NotificationType.QA_CONTACT)}"
            f"{self.create_jira_comment_mentions([qa_contact])}Please verify the Issue as soon as possible."
        )

    def notify_qa_contact(self, issue: Issue) -> Optional[Notification]:
        """
        Notifies the QA contact of the issue, or notifies assignees if QA contact is missing.

        Args:
            issue (Issue): The issue to notify about.

        Returns:
            Optional[Notification]: The created notification if sent, otherwise None.
        """

        qa_contact = self.get_qa_contact(issue)
        if qa_contact:
            qa_notification = Notification(
                issue,
                NotificationType.QA_CONTACT,
                self.create_qa_notification_text(qa_contact)
            )
            self.process_notification(qa_notification)
            self.add_user_to_need_info_from(issue, qa_contact)
            return qa_notification
        else:
            logger.warning("QA contact is missing. Assignees will be notified.")
            return self.notify_assignees(issue, Contact.QA_CONTACT)

    # FIXME OCPERT-139 Improve Jira notificator by notifying team leads instead QA contacts
    def create_team_lead_notification_text(self, qa_contact: User) -> Optional[str]:
        """
        Creates a notification text for the QA contact to verify the issue or arrange a reassignment with their team lead.

        Args:
            qa_contact (User): The QA contact user.

        Returns:
            str: The complete notification message text.
        """

        return (
            f"{self.create_notification_title(NotificationType.TEAM_LEAD)}"
            f"{self.create_jira_comment_mentions([qa_contact])}Please verify the Issue as soon as possible or arrange a reassignment with your team lead."
        )

    def notify_team_lead(self, issue: Issue) -> Optional[Notification]:
        """
        Notifies the team lead via the QA contact, or notifies assignees if QA contact is missing.

        Args:
            issue (Issue): The issue to notify about.

        Returns:
            Optional[Notification]: The created notification if sent, otherwise None.
        """

        logger.info("Notification to the team lead is not yet implemented. Notifying the QA contact again.")

        qa_contact = self.get_qa_contact(issue)
        if qa_contact:
            team_lead_notification = Notification(
                issue,
                NotificationType.TEAM_LEAD,
                self.create_team_lead_notification_text(qa_contact)
            )
            self.process_notification(team_lead_notification)
            self.add_user_to_need_info_from(issue, qa_contact)
            return team_lead_notification
        else:
            logger.warning("QA contact is missing. Assignees will be notified.")
            return self.notify_assignees(issue, Contact.QA_CONTACT)

    def create_manager_notification_text(self, manager: User) -> str:
        """
        Creates a notification text for the manager to prioritize or reassign the issue.

        Args:
            manager (User): The manager user to notify.

        Returns:
            str: The complete notification message text.
        """

        return (
            f"{self.create_notification_title(NotificationType.MANAGER)}"
            f"{self.create_jira_comment_mentions([manager])}Please prioritize the Issue verification or consider reassigning it to another available QA Contact."
        )

    def notify_manager(self, issue: Issue) -> Optional[Notification]:
        """
        Notifies the manager, or notifies assignees if needed.

        Args:
            issue (Issue): The issue to notify about.

        Returns:
            Optional[Notification]: The created notification if sent, otherwise None.
        """

        qa_contact = self.get_qa_contact(issue)
        if qa_contact:
            manager = self.get_manager(qa_contact)
            if manager:
                manager_notification = Notification(
                    issue,
                    NotificationType.MANAGER,
                    self.create_manager_notification_text(manager)
                )
                self.process_notification(manager_notification)
                self.add_user_to_need_info_from(issue, manager)
                return manager_notification
            else:
                logger.warning("Manager was not found. Assignees will be notified.")
                return self.notify_assignees(issue, Contact.MANAGER)
        else:
            logger.warning("QA contact is missing. Assignees will be notified.")
            return self.notify_assignees(issue, Contact.QA_CONTACT)

    def get_latest_on_qa_transition_datetime(self, issue: Issue) -> Optional[datetime]:
        """
        Returns the most recent datetime when the issue transitioned to ON_QA status.

        Args:
            issue (Issue): The JIRA issue to inspect.

        Returns:
            Optional[datetime]: The latest ON_QA transition timestamp, or None if not found.
        """

        latest_on_qa: datetime = None

        for history in issue.changelog.histories:
            for item in history.items:
                if item.field == "status" and item.toString == "ON_QA":
                    transition_time = parser.parse(history.created)
                    if not latest_on_qa or transition_time > latest_on_qa:
                        latest_on_qa = transition_time

        return latest_on_qa

    def get_latest_notification_dates_after_on_qa_transition(self, issue: Issue, on_qa_transition: datetime) -> Dict[NotificationType, Optional[datetime]]:
        """
        Returns the latest notification dates for each type after the ON_QA transition.

        Args:
            issue (Issue): The JIRA issue to inspect.
            on_qa_transition (datetime): The datetime when the issue transitioned to ON_QA.

        Returns:
            Dict[NotificationType, Optional[datetime]]: A mapping of notification types to
            their latest comment creation datetimes after the ON_QA transition.
        """

        notification_types_with_latest_date: Dict[NotificationType, Optional[datetime]] = {}

        for comment in issue.fields.comment.comments:
            if not comment.body.startswith(ERT_NOTIFICATION_PREFIX):
                continue

            created_datetime = parser.parse(comment.created)
            if created_datetime < on_qa_transition:
                continue

            notification_type = self.get_notification_type(comment.body)
            notification_datetime = notification_types_with_latest_date.get(notification_type)

            if not notification_datetime or created_datetime > notification_datetime:
                notification_types_with_latest_date[notification_type] = created_datetime

        return notification_types_with_latest_date

    def is_more_than_24_weekday_hours(self, from_date: datetime, now: Optional[datetime] = None) -> bool:
        """
        Checks if more than 24 weekday hours have passed since the given datetime.

        Args:
            from_date (datetime): The starting datetime.
            now (Optional[datetime]): Current datetime used for comparison (for testing; defaults to current UTC time).

        Returns:
            bool: True if more than 24 weekday hours have passed, otherwise False.
        """

        if now is None:
            now = datetime.now(timezone.utc)

        if from_date >= now:
            return False

        total_diff = now - from_date

        if total_diff > timedelta(days=3):
            return True

        current = from_date
        valid_hours = 0
        while current < now:
            if current.weekday() < 5:  # Monday to Friday
                valid_hours += 1
            current += timedelta(hours=1)

        return valid_hours > 24

    def check_issue_and_notify_responsible_people(self, issue: Issue) -> Optional[Notification]:
        """
        Checks the ON_QA transition and sends notifications based on elapsed time and notification history.

        Args:
            issue (Issue): The issue to evaluate and notify about.

        Returns:
            Optional[Notification]: The created notification if sent, otherwise None.
        """

        on_qa_datetime = self.get_latest_on_qa_transition_datetime(issue)
        if not on_qa_datetime:
            logger.error(f"Issue {issue.key} does not have ON_QA transition date")
            return None
        logger.info(f"Issue {issue.key} has ON_QA transition date: {on_qa_datetime}")

        notification_dates = self.get_latest_notification_dates_after_on_qa_transition(issue, on_qa_datetime)

        if not notification_dates.get(NotificationType.QA_CONTACT):
            logger.info("Removing ON_QA pending label.")
            self.remove_ert_all_notified_onqa_pending_label(issue)  # Issue can be again in ON_QA state.
            
            if self.is_more_than_24_weekday_hours(on_qa_datetime):
                logger.info("Notifying QA Contact")
                return self.notify_qa_contact(issue)
            else:
                logger.info("Skipping notifying QA Contact - less than 24 hour from transition to ON_QA.")
        elif not notification_dates.get(NotificationType.TEAM_LEAD): 
            logger.info(f"Issue {issue.key} has QA Contact notification date: {notification_dates.get(NotificationType.QA_CONTACT)}")
            if self.is_more_than_24_weekday_hours(notification_dates.get(NotificationType.QA_CONTACT)):
                logger.info("Notifying Team Lead")
                return self.notify_team_lead(issue)
            else:
                logger.info("Skipping notifying Team Lead - less than 24 hour from QA Contact notification.")
        elif not notification_dates.get(NotificationType.MANAGER):
            logger.info(f"Issue {issue.key} has Team Lead notification date: {notification_dates.get(NotificationType.TEAM_LEAD)}")
            if self.is_more_than_24_weekday_hours(notification_dates.get(NotificationType.TEAM_LEAD)):
                logger.info("Notifying Manager")
                return self.notify_manager(issue)
            else:
                logger.info("Skipping notifying Manager - less than 24 hour from Team Lead notification.")
        else:
            logger.info(f"Issue {issue.key} has Manager notification date: {notification_dates.get(NotificationType.MANAGER)}")
            logger.info("All contacts have been notified.")
            if self.is_more_than_24_weekday_hours(notification_dates.get(NotificationType.MANAGER)):
                logger.info("Adding ON_QA pending label to the issue.")
                self.add_ert_all_notified_onqa_pending_label(issue)
            else:
                logger.info("Skipping adding ON_QA pending label - less than 24 hour from Manager notification.")

        return None

    def get_on_qa_filter(self, from_date: Optional[datetime] = None) -> str:
        """
        Constructs a JIRA JQL filter string for ON_QA issues optionally filtered by a date.

        Args:
            from_date (Optional[datetime]): If provided, filters issues that transitioned to ON_QA after this date.

        Returns:
            str: The JQL filter string.
        """

        base_filter = (
            "project = OCPBUGS AND issuetype in (Bug, Vulnerability) "
            "AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z, 4.20.z, 4.21.z)"
        )

        date_suffix = f" AND status changed to ON_QA after {from_date.strftime('%Y-%m-%d')}" if from_date else ""

        return base_filter + date_suffix

    def get_on_qa_issues(self, search_batch_size: int, from_date: Optional[datetime]) -> List[Issue]:
        """
        Retrieves ON_QA issues from JIRA in batches, optionally filtered by a date.

        Args:
            search_batch_size (int): Number of issues to fetch per batch.
            from_date (Optional[datetime]): If provided, fetches issues transitioned to ON_QA after this date.

        Returns:
            List[Issue]: A list of JIRA issues matching the ON_QA criteria.
        """

        start_at = 0
        on_qa_issues = []

        while True:
            # FIXME: OCPERT-135 Find a solution to access Jira tickets with limited permissions
            issues = self.jira.search_issues(
                self.get_on_qa_filter(from_date), startAt=start_at, maxResults=search_batch_size, expand="changelog"
            )
            if not issues:
                break
            on_qa_issues.extend(issues)
            start_at += len(issues)

        return on_qa_issues

    def process_on_qa_issues(self, search_batch_size: int, from_date: Optional[datetime]) -> List[Notification]:
        """
        Processes ON_QA issues by checking and notifying responsible people.

        Args:
            search_batch_size (int): Number of issues to fetch per batch.
            from_date (Optional[datetime]): If provided, process issues transitioned to ON_QA after this date.
        
        Returns:
            List[Notification]: List of successfully sent notifications.
        """
        sent_notifications: list[Notification] = []
        error_occurred = False

        for issue in self.get_on_qa_issues(search_batch_size, from_date):
            logger.info(f"Processing issue: {issue.key}")
            try:
                notification = self.check_issue_and_notify_responsible_people(issue)
            except Exception as e:
                logger.error(f"An error occured while processing the Issue {issue.key}: {e}")
                error_occurred = True
            if notification:
                sent_notifications.append(notification)

        if error_occurred:
            raise RuntimeError("An error occured while processing the issues. See the logs for details.")

        return sent_notifications

@click.command()
@click.option("--search-batch-size", default=100, type=int, help="Maximum number of results to retrieve in each search iteration or batch.")
@click.option("--dry-run", is_flag=True, default=False, help="Run without sending Jira notifications.")
@click.option("--from-date", default=None, type=click.DateTime(formats=["%Y-%m-%d"]), required=False, help="Filters issues that changed to ON_QA state after this date.")
def jira_notificator(search_batch_size: int, dry_run: bool, from_date: Optional[datetime]) -> None:
    """
    CLI entry point to process ON_QA issues and notify responsible people.

    Args:
        search_batch_size (int): Number of issues to fetch per batch.
        dry_run (bool): If True, simulate notifications without sending.
        from_date (Optional[datetime]): Filter issues transitioned to ON_QA after this date.

    Returns:
        None
    """

    jira_token = os.environ.get("JIRA_TOKEN")

    if not jira_token:
        raise RuntimeError("JIRA token is missing or empty. Please set the JIRA_TOKEN environment variable.")

    jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)

    ns = NotificationService(jira, dry_run)
    ns.process_on_qa_issues(search_batch_size, from_date)

if __name__ == "__main__":
    jira_notificator()
