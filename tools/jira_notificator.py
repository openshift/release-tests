import click
import logging
import os

from enum import Enum
from typing import List, Optional, Tuple
from jira import JIRA, Issue
from jira.resources import User
from datetime import datetime, timedelta, timezone
from dateutil import parser
from oar.core.ldap import LdapHelper

logger = logging.getLogger(__name__)

ERT_NOTIFICATION_PREFIX = "Errata Reliability Team Notification"

class NotificationType(Enum):
    QA_CONTACT = (24, "QA Contact Action Request")
    TEAM_LEAD = (48, "Team Lead Action Request")
    MANAGER = (72, "Manager Action Request")
    ASSIGNEE = (24, "Assignee Action Request")

    def __init__(self, hours: int, label: str):
        self.hours = hours
        self.label = label

class Contact(Enum):
    QA_CONTACT = "QA Contact"
    TEAM_LEAD = "Team Lead"
    MANAGER = "Manager"

class Notification:
    issue: Issue
    type: NotificationType
    text: str

    def __init__(self, issue, type, text):
        self.issue = issue
        self.type = type
        self.text = text

def create_notification_title(notification_type: NotificationType) -> str:
    return (
        f"{ERT_NOTIFICATION_PREFIX} - {notification_type.label}\n"
        f"This issue has been in the ON_QA state for over {notification_type.hours} hours.\n"
    )

def get_notification_type(notification_message: str) -> Optional[NotificationType]:
    for notification_type in NotificationType:
        if notification_type.label in notification_message:
            return notification_type
    return None

def create_jira_comment_mentions(users: List[User]) -> str:
    jira_comment_mentions = ""
    for u in users:
        jira_comment_mentions += f"[~{u.name}] "
    return jira_comment_mentions

def process_notification(jira: JIRA, notification: Notification, dry_run: bool) -> None:
    log_message = f"'{notification.type.label}' notification to Issue {notification.issue.key}: {notification.text}"
    if not dry_run:
        logger.info(f"Sending {log_message}")
        jira.add_comment(notification.issue, notification.text)
    else:
        logger.info(f"Skipping sending {log_message}")

def find_user_by_email(jira: JIRA, email: str) -> Optional[User]:
    for user in jira.search_users(user=email):
        if user.emailAddress == email:
            return user
    logger.warning(f"User was not found for email {email}.")
    return None

def get_qa_contact(issue: Issue) -> Optional[User]:
    qa_contact = issue.fields.customfield_12315948
    if qa_contact:
        return qa_contact
    else:
        logger.warning(f"Issue {issue.key} does not have a QA contact.")
        return None

def get_manager(jira: JIRA, user: User) -> Optional[User]:
    ldap = LdapHelper()
    manager_email = ldap.get_manager_email(user.emailAddress)
    if manager_email:
        manager = find_user_by_email(jira, manager_email)
        if manager:
            return manager
        else:
            logger.warning(f"Manager {manager_email} was not found in Jira.")
    else:
        logger.warning(f"Manager of {user.emailAddress} was not found in LDAP.")
    return None

def get_assignee(issue: Issue) -> User:
    assignee = issue.fields.assignee
    if assignee:
        return assignee
    else:
        logger.warning(f"Issue {issue.key} does not have an Assignee.")
        return None

def create_assignee_notification_text(missing_contact: Contact, notified_assignees: list[User]) -> str:
    message = ""
    if missing_contact == Contact.QA_CONTACT:
        message = f"The QA contact is missing."
    elif missing_contact == Contact.TEAM_LEAD or missing_contact == Contact.MANAGER:
        message = f"There has been no response from the QA contact and the {missing_contact.value} is not listed in Jira."
    else:
        raise ValueError(f"Unknown Contact value: {missing_contact}.")
    
    return (
        f"{create_notification_title(NotificationType.ASSIGNEE)}"
        f"{create_jira_comment_mentions(notified_assignees)}"
        f"{message} Could you please help us identify someone who could review the issue?"
    )

def has_assignee_notification(issue: Issue) -> bool:
    for comment in issue.fields.comment.comments:
        if comment.body.startswith(create_notification_title(NotificationType.ASSIGNEE)):
            return True
    return False

def notify_assignees(jira: JIRA, issue: Issue, missing_contact: Contact, dry_run: bool) -> None:
    if not has_assignee_notification(issue):
        assignee = get_assignee(issue)
        if assignee:
            notified_assignees = [assignee]
            assignee_manager = get_manager(jira, assignee)
            if assignee_manager:
                notified_assignees.append(assignee_manager)
            assignee_notification = Notification(
                issue, 
                NotificationType.ASSIGNEE, 
                create_assignee_notification_text(missing_contact, notified_assignees)
            )
            process_notification(jira, assignee_notification, dry_run)
        else:
            raise Exception(f"No contact is available. Issue {issue.key} does not have assignee.")
    else:
        logger.warning(f"Assignees have already been notified about the missing {missing_contact.value} contact.")

def create_qa_notification_text(qa_contact: User) -> str:
    return (
        f"{create_notification_title(NotificationType.QA_CONTACT)}"
        f"{create_jira_comment_mentions([qa_contact])}Please verify the Issue as soon as possible."
    )

def notify_qa_contact(jira: JIRA, issue: Issue, dry_run: bool) -> None:
    qa_contact = get_qa_contact(issue)
    if qa_contact:
        qa_notification = Notification(
            issue,
            NotificationType.QA_CONTACT,
            create_qa_notification_text(qa_contact)
        )
        process_notification(jira, qa_notification, dry_run)
    else:
        logger.warning("QA contact is missing. Assignees will be notified.")
        notify_assignees(jira, issue, Contact.QA_CONTACT, dry_run)

def create_team_lead_notification_text(qa_contact: User) -> Optional[str]:
    return (
        f"{create_notification_title(NotificationType.TEAM_LEAD)}"
        f"{create_jira_comment_mentions([qa_contact])}Please verify the Issue as soon as possible or arrange a reassignment with your team lead."
    )

def notify_team_lead(jira: JIRA, issue: Issue, dry_run: bool) -> None:
    logger.info("Notification to the team lead is not yet implemented. Notifying the QA contact again.")

    qa_contact = get_qa_contact(issue)
    if qa_contact:
        team_lead_notification = Notification(
            issue,
            NotificationType.TEAM_LEAD,
            create_team_lead_notification_text(qa_contact)
        )
        process_notification(jira, team_lead_notification, dry_run)
    else:
        logger.warning("QA contact is missing. Assignees will be notified.")
        notify_assignees(jira, issue, Contact.QA_CONTACT, dry_run)

def create_manager_notification_text(manager: User) -> str:
    return (
        f"{create_notification_title(NotificationType.MANAGER)}"
        f"{create_jira_comment_mentions([manager])}Please prioritize the Issue verification or consider reassigning it to another available QA Contact."
    )

def notify_manager(jira: JIRA, issue: Issue, dry_run: bool) -> None:
    qa_contact = get_qa_contact(issue)
    if qa_contact:
        manager = get_manager(jira, qa_contact)
        if manager:
            manager_notification = Notification(
                issue,
                NotificationType.MANAGER,
                create_manager_notification_text(manager)
            )
            process_notification(jira, manager_notification, dry_run)
        else:
            logger.warning("Manager was not found. Assignees will be notified.")
            notify_assignees(jira, issue, Contact.MANAGER, dry_run)
    else:
        logger.warning("QA contact is missing. Assignees will be notified.")
        notify_assignees(jira, issue, Contact.QA_CONTACT, dry_run)

def get_latest_on_qa_transition_datetime(issue: Issue) -> Optional[datetime]:
    latest_on_qa: datetime = None

    for history in issue.changelog.histories:
        for item in history.items:
            if item.field == "status" and item.toString == "ON_QA":
                transition_time = parser.parse(history.created)
                if not latest_on_qa or transition_time > latest_on_qa:
                    latest_on_qa = transition_time

    if not latest_on_qa:
        logger.error(f"Issue {issue.key} does not have ON_QA transition date")

    return latest_on_qa

def get_latest_ert_notification_type_after_on_qa_transition(issue: Issue, on_qa_transition: datetime) -> Optional[NotificationType]:
    latest_notification_type: NotificationType = None
    latest_datetime: datetime = None

    for comment in issue.fields.comment.comments:
        if not comment.body.startswith(ERT_NOTIFICATION_PREFIX):
            continue

        created_datetime = parser.parse(comment.created)
        if created_datetime < on_qa_transition:
            continue

        if not latest_datetime or created_datetime > latest_datetime:
            latest_datetime = created_datetime
            latest_notification_type = get_notification_type(comment.body)

    return latest_notification_type


def check_issue_and_notify_responsible_people(jira: JIRA, issue: Issue, dry_run: bool) -> None:
    try:
        on_qa_datetime = get_latest_on_qa_transition_datetime(issue)
        if not on_qa_datetime:
            return

        delta = datetime.now(timezone.utc) - on_qa_datetime
        latest_notification_type = get_latest_ert_notification_type_after_on_qa_transition(issue, on_qa_datetime)

        if delta > timedelta(hours=NotificationType.MANAGER.hours):
            if latest_notification_type != NotificationType.MANAGER:
                notify_manager(jira, issue, dry_run)
        elif delta > timedelta(hours=NotificationType.TEAM_LEAD.hours):
            if latest_notification_type != NotificationType.TEAM_LEAD:
                notify_team_lead(jira, issue, dry_run)
        elif delta > timedelta(hours=NotificationType.QA_CONTACT.hours):
            if latest_notification_type != NotificationType.QA_CONTACT:
                notify_qa_contact(jira, issue, dry_run)
    except Exception as e:
        logger.error(f"An error occured while processing the Issue {issue.key}: {e}")

def get_on_qa_issues(jira: JIRA, search_batch_size: int) -> list[Issue]:
    ON_QA_ISSUES_FILTER = "project = OCPBUGS AND issuetype in (Bug, Vulnerability) AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"

    start_at = 0
    on_qa_issues = []

    while True:
        # FIXME: OCPERT-135 Find a solution to access Jira tickets with limited permissions
        issues = jira.search_issues(
            ON_QA_ISSUES_FILTER, startAt=start_at, maxResults=search_batch_size, expand="changelog"
        )
        if not issues:
            break
        on_qa_issues.extend(issues)
        start_at += len(issues)

    return on_qa_issues

def process_on_qa_issues(jira: JIRA, search_batch_size: int, dry_run: bool) -> None:
    for issue in get_on_qa_issues(jira, search_batch_size):
        check_issue_and_notify_responsible_people(jira, issue, dry_run)

@click.command()
@click.option("--search-batch-size", default=100, type=int, help="Maximum number of results to retrieve in each search iteration or batch.")
@click.option('--dry-run', is_flag=True, default=False, help='Run without sending Jira notifications.')
def main(search_batch_size: int, dry_run: bool):
    jira_token = os.environ.get("JIRA_TOKEN")
    jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)
    process_on_qa_issues(jira, search_batch_size, dry_run)

if __name__ == '__main__':
    main()
