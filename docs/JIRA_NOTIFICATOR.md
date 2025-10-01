# Jira Notificator
This is copy of [Jira Notificator](https://spaces.redhat.com/spaces/OCPERT/pages/653924138/Jira+Notificator) Confluence article.

## Overview
This Jira Notificator Python script is a command-line tool designed to monitor OCPBUGS jira issues in the ON_QA status and send escalating notifications if they remain in that state for extended periods. It automatically notifies the QA Contact, Team Lead, and Manager in sequence to ensure timely verification of issues.

## Process flow
The Jira Notificator searches for all ON QA issues based on the specified filter and, for each issue:

1. Checks whether a QA Contact notification has already been sent.

2. If not, and 24 weekday hours have passed since the issue transitioned to the ON QA state, the QA contact is notified.

    - If no QA contact is assigned, the assignees and their manager are notified instead.

3. Checks whether a Team Lead notification has already been sent.

4. If not, and 24 weekday hours have passed since the QA Contact notification, the QA contact is notified again (instead of the Team Lead, as Team Lead notifications are not yet implemented).

5. Checks whether a Manager notification has already been sent.

6. If not, and 24 weekday hours have passed since the Team Lead (second QA Contact) notification, the manager is notified.

    - If no manager is found, the assignees and their manager are notified instead.

10. If yes, and 24 weekday hours have passed since the Manager notification, ON QA pending label (`ert:pending-onqa-over-96hrs`) is added to the issue.

## ON QA issues Jira filter
The Jira filter searches **ON QA** issues from project **OCPBUGS** where the issue type is **Bug** or **Vulnerability** and the target version is **4.12.z**, **4.13.z**, **4.14.z**, **4.15.z**, **4.16.z**, **4.17.z**, **4.18.z** or **4.19.z**.


```
project = OCPBUGS AND issuetype in (Bug, Vulnerability) AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z)
```

If the search is limited by the from-date parameter, the filter searches for issues only from that date onward.

```
project = OCPBUGS AND issuetype in (Bug, Vulnerability) AND status = ON_QA AND 'Target Version' in (4.12.z, 4.13.z, 4.14.z, 4.15.z, 4.16.z, 4.17.z, 4.18.z, 4.19.z) AND status changed to ON_QA after {from-date}
```

## Types of notification
- **QA Contact notification**
  - Sent after 24 weekday hours if the QA contact has not verified the issue. Requests verification of the issue. If no QA contact is assigned, an Assignees notification is sent instead.
- **Team Lead notification**
  - Sent after 48 hours if the issue is still in the ON QA status. Notifies the QA contact again (notification for the Team Lead is currently not available). Requests verification of the issue or reassignment via the team lead.
- **Manager notification**
  - Sent after 72 hours if the issue is still in the ON QA status. Requests the manager to prioritize issue verification or reassign to another available QA contact. If manager is not found, an Assignees notification is sent instead.
- **Assignees notification**
  - Sent if the QA contact is missing, or if the QA contact has not responded within 48 weekday hours and their manager cannot be found. Requests the assignee and their manager to help identify someone to verify the issue.

## Notification Recipients
- **QA contact**
  - First to be notified if the Jira issue remains unverified for more than 24 weekday hours after transitioning to the ON_QA state. 
- **Team Lead**
  - Second in the escalation chain, notified if the QA contact does not verify the issue within the next 24 weekday hours - i.e., at least 48 hours after the issue transitioned to ON_QA. (Currently, contacting the Team Lead is not supported; instead, the QA contact is notified again - see the Areas for Improvement section for details.)
- **Manager**
  - Final person in the escalation chain, notified 24 weekday hours after the Team Lead notification (the second QA contact notification) if the issue is still in the ON_QA state - no earlier than 72 hours after the initial transition to ON_QA.
- **Assignee**
  - Notified together with their manager in two cases: (1) the QA contact is missing from the issue, or (2) the QA contact has not responded within 48 weekday hours and their manager cannot be found.
- **Assignee manager**
  - Notified together with the assignee in the cases described above.

## CLI Usage

```
oarctl jira-notificator [OPTIONS]
```

### Options
- `--search-batch-size INTEGER`
  - Maximum number of results to retrieve in each search iteration or batch. This does not limit the total number of issues found - all matching issues will be retrieved in multiple batches.
- `--dry-run`
  - A flag that runs the script in simulation mode. It will log all the notifications without actually posting any comments to Jira.
- `--from-date YYYY-MM-DD`
  - An optional date filter. If provided, the script will only process issues that were transitioned to ON_QA state after this date.
- `--help`
  - Shows the help message and exits.
