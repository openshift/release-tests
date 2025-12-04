import logging

import click

from oar.core.const import *
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.operators import BugOperator
from oar.core.worksheet import WorksheetManager
from oar.core import util

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option("--notify/--no-notify", default=True, help="Send notification to bug owners, default value is true")
@click.option("--confirm-droppable", is_flag=True, default=False,
              help="Send notification only to bug owners with critical and higher issue severity, default value is false")
@click.option("--notify-managers", is_flag=True, default=False, help="Send notification to managers of unverified CVE issues, default value is false")
def update_bug_list(ctx, notify, confirm_droppable, notify_managers):
    """
    Update bug status listed in report, update existing bug status and append new ON_QA bug

    NOTE: This command is not needed in Konflux release flow.
    Kept for backward compatibility with Errata flow releases.
    """
    if not notify and (confirm_droppable or notify_managers):
        raise click.UsageError("Error: --no-notify cannot be used together with --confirm-droppable or --notify-managers")
    if sum([confirm_droppable, notify_managers]) > 1:
        raise click.UsageError("Error: only one of parameters --confirm-droppable or --notify-managers can be used simultaneously")
    # get config store from context
    cs = ctx.obj["cs"]

    # Prevent execution in Konflux flow
    if cs.is_konflux_flow():
        raise click.UsageError("This command is not supported in Konflux release flow. Skipping.")
    try:
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_UPDATE_BUG_LIST, TASK_STATUS_INPROGRESS)

        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # refresh bug list using operator
        operator = BugOperator(cs)
        jira_issues = operator.get_jira_issues()
        report.update_bug_list(jira_issues)
        # send notification
        if notify:
            if confirm_droppable:
                high_severity_issues, _ = JiraManager(cs).get_high_severity_and_can_drop_issues(jira_issues)
                if len(high_severity_issues):
                    NotificationManager(cs).share_high_severity_bugs(high_severity_issues)
                else:
                    logger.info("No high severity issues found.")
            elif notify_managers:
                unverified_cve_issues = JiraManager(cs).get_unverified_cve_issues(jira_issues)
                if len(unverified_cve_issues):
                    NotificationManager(cs).share_unverified_cve_issues_to_managers(unverified_cve_issues)
                else:
                    logger.info("No unverified CVE issues found.")
            else:
                NotificationManager(cs).share_bugs_to_be_verified(jira_issues)
        # check if all bugs are verified
        if report.are_all_bugs_verified():
            # Log pass status for cli_result_callback parsing
            util.log_task_status(TASK_UPDATE_BUG_LIST, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("update bug list in report failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_UPDATE_BUG_LIST, TASK_STATUS_FAIL)
        raise
