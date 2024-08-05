import click
import logging
import oar.core.util as util
from oar.core.worksheet import WorksheetManager, WorksheetException
from oar.core.jira import JiraManager, JiraException
from oar.core.advisory import AdvisoryManager, AdvisoryException
from oar.core.configstore import ConfigStore
from oar.core.notification import NotificationManager
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option("--notify/--no-notify", default=True, help="Send notification to bug owner, default value is true")
def update_bug_list(ctx, notify):
    """
    Update bug status listed in report, update existing bug status and append new ON_QA bug
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # update task status to in progress
        report.update_task_status(LABEL_TASK_BUGS_TO_VERIFY, TASK_STATUS_INPROGRESS)
        # refresh bug list
        jira_issues = AdvisoryManager(cs).get_jira_issues()
        report.update_bug_list(jira_issues)
        # send notification
        if notify:
            NotificationManager(cs).share_bugs_to_be_verified(jira_issues)
        # check if all bugs are verified
        if report.are_all_bugs_verified():
            report.update_task_status(LABEL_TASK_BUGS_TO_VERIFY, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("update bug list in report failed")
        raise
