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
@click.option(
    "-e",
    "--email",
    help="email address of the owner, if option is not set, will use default owner setting instead",
)
@click.pass_context
def take_ownership(ctx, email):
    """
    Take ownership for advisory and jira subtasks
    """
    # get config store from context
    cs = ctx.obj["cs"]
    if not email:
        logger.warn("email option is not set, will use default setting")
    else:
        cs.set_owner(email)

    try:
        # get existing report
        wm = WorksheetManager(cs)
        report = wm.get_test_report()
        # update task status to in progress
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_INPROGRESS)
        # update assignee of QE subtasks and change status of test verification ticket to in_progress
        JiraManager(cs).change_assignee_of_qe_subtasks()
        # update owner of advisories which status is QE
        AdvisoryManager(cs).change_ad_owners()
        # update task status to pass
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("take ownership of advisory and jira subtasks failed")
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_FAIL)
        raise
