import click
import logging
import oar.core.util as util
from oar.core.worksheet_mgr import WorksheetManager, WorksheetException
from oar.core.jira_mgr import JiraManager, JiraException
from oar.core.advisory_mgr import AdvisoryManager, AdvisoryException
from oar.core.config_store import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def update_bug_list(ctx):
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
        report.update_bug_list(AdvisoryManager(cs).get_jira_issues())
        # check if all bugs are verified
        if report.are_all_bugs_verified():
            report.update_task_status(LABEL_TASK_BUGS_TO_VERIFY, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("take ownership of advisory and jira subtasks failed")
        raise
