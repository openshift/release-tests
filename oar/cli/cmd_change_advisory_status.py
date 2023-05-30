import click
import logging
from oar.core.worksheet_mgr import WorksheetManager
from oar.core.advisory_mgr import AdvisoryManager
from oar.core.jira_mgr import JiraManager
from oar.core.config_store import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option(
    "-s",
    "--status",
    default=AD_STATUS_REL_PREP,
    help="Valid advisory status, default is REL_PREP",
)
def change_advisory_status(ctx, status):
    """
    Change advisory status e.g. QE, REL_PREP
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_INPROGRESS)
        # change all advisories' status
        am.change_advisory_status(status)
        # close jira tickets
        jm = JiraManager(cs)
        sub_tasks = jm.get_sub_tasks(cs.get_jira_ticket())
        for sub_task in sub_tasks:
            if sub_task.get_summary() in JIRA_QE_TASK_SUMMARIES:
                jm.transition_issue(sub_task.get_key(), JIRA_STATUS_CLOSED)
        # if no exception occurred, update task status to pass
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception(f"change advisory status to {status} failed")
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
        raise
