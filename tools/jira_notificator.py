import click
import logging
import os

from enum import Enum
from typing import Optional
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

    def __init__(self, hours: int, label: str):
        self.hours = hours
        self.label = label

def create_notification_title(notification_type: NotificationType) -> str:
    return (
        f"{ERT_NOTIFICATION_PREFIX} - {notification_type.label}\n"
        f"This issue has been in the ON_QA state for over {notification_type.hours} hours."
    )

def get_notification_type(notification_message: str) -> Optional[NotificationType]:
    for notification_type in NotificationType:
        if notification_type.label in notification_message:
            return notification_type
    return None

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

def get_manager(jira: JIRA, qa_contact: User) -> Optional[User]:
    ldap = LdapHelper()
    manager_email = ldap.get_manager_email(qa_contact.emailAddress)
    if manager_email:
        manager = find_user_by_email(jira, manager_email)
        if manager:
            return manager
        else:
            logger.warning(f"Manager {manager_email} was not found in Jira.")
    else:
        logger.warning(f"Manager of QA contact {qa_contact.emailAddress} was not found in LDAP.")
    return None

def create_qa_notification_text(issue: Issue)  -> str:
    qa_contact_link = ""
    qa_contact = get_qa_contact(issue)
    if qa_contact:
        qa_contact_link = f"[~{qa_contact.name}] "
    else:
        logger.warning(f"Notification text was generated without a link to the QA Contact for Jira ticket {issue.key}.")
    return f"{create_notification_title(NotificationType.QA_CONTACT)}\n{qa_contact_link}Please verify the Jira ticket as soon as possible."

def notify_qa_contact(jira: JIRA, issue: Issue) -> None:
    jira.add_comment(issue, create_qa_notification_text(issue))

def create_team_lead_notification_text(issue: Issue) -> str:
    qa_contact_link = ""
    qa_contact = get_qa_contact(issue)
    if qa_contact:
        qa_contact_link = f"[~{qa_contact.name}] "
    else:
        logger.warning(f"Notification text was generated without a link to the QA Contact for Jira ticket {issue.key}.")
    return f"{create_notification_title(NotificationType.TEAM_LEAD)}\n{qa_contact_link}Please verify the Jira ticket as soon as possible or arrange a reassignment with your team lead."

def notify_team_lead(jira: JIRA, issue: Issue) -> None:
    logger.info("Notification to the team lead is not yet implemented. Notifying the QA contact again.")
    jira.add_comment(issue, create_team_lead_notification_text(issue))

def create_manager_notification_text(jira: JIRA, issue: Issue) -> str:
    qa_contact = get_qa_contact(issue)
    manager_link = ""
    if qa_contact:
        manager = get_manager(jira, qa_contact)
        if manager:
            manager_link = f"[~{manager.name}] "
        else:
            logger.warning(f"Notification text was generated without a link to the Manager for Jira ticket {issue.key} (Missing Manager).")
    else:
        logger.warning(f"Notification text was generated without a link to the Manager for Jira ticket {issue.key} (Missing QA Contact).")
    return f"{create_notification_title(NotificationType.MANAGER)}\n{manager_link}Please prioritize the Jira ticket verification or consider reassigning it to another available QA Contact."

def notify_manager(jira: JIRA, issue: Issue) -> None:
    jira.add_comment(issue, create_manager_notification_text(jira, issue))
   
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


def check_issue_and_notify_responsible_people(jira: JIRA, issue: Issue) -> None:
    try:
        on_qa_datetime = get_latest_on_qa_transition_datetime(issue)
        if not on_qa_datetime:
            return

        delta = datetime.now(timezone.utc) - on_qa_datetime
        latest_notification_type = get_latest_ert_notification_type_after_on_qa_transition(issue, on_qa_datetime)

        if delta > timedelta(hours=NotificationType.MANAGER.hours):
            if latest_notification_type != NotificationType.MANAGER:
                notify_manager(jira, issue)
        elif delta > timedelta(hours=NotificationType.TEAM_LEAD.hours):
            if latest_notification_type != NotificationType.TEAM_LEAD:
                notify_team_lead(jira, issue)
        elif delta > timedelta(hours=NotificationType.QA_CONTACT.hours):
            if latest_notification_type != NotificationType.QA_CONTACT:
                notify_qa_contact(jira, issue)
    except Exception as e:
        logger.error(f"An error occured while processing the Jira ticket {issue.key}: {e}")

def get_on_qa_issues(jira: JIRA) -> list[Issue]:
    ON_QA_ISSUES_FILTER = "project = OCPBUGS AND issuetype in (Bug, Vulnerability) AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)"

    start_at = 0
    batch_size = 100
    on_qa_issues = []

    while True:
        issues = jira.search_issues(
            ON_QA_ISSUES_FILTER, startAt=start_at, maxResults=batch_size, expand="changelog"
        )
        if not issues:
            break
        on_qa_issues.extend(issues)
        start_at += len(issues)

    return on_qa_issues

def process_on_qa_issues(jira: JIRA) -> None:
    for issue in get_on_qa_issues(jira):
        check_issue_and_notify_responsible_people(jira, issue)

@click.command()
def main():
    jira_token = os.environ.get("JIRA_TOKEN")
    jira = JIRA(server="https://issues.redhat.com", token_auth=jira_token)
    process_on_qa_issues(jira)

if __name__ == '__main__':
    main()
