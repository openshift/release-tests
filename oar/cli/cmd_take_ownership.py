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
    # init worksheet manager
    try:
        wm = WorksheetManager(cs)
        report = wm.get_test_report()
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_INPROGRESS)
    except WorksheetException as we:
        logger.exception("get test report failed")
        raise

    # update assignee of QE subtasks and change status of test verification ticket to in_progress
    try:
        JiraManager(cs).change_assignee_of_qe_subtasks()
    except JiraException as je:
        logger.exception("change assignee of qe subtasks failed")
        raise

    # update owner of advisories which status is QE
    try:
        AdvisoryManager(cs).change_ad_owners()
    except AdvisoryException as ae:
        logger.exception("change qe owner of advisory failed")
        raise

    try:
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_PASS)
    except WorksheetException as we:
        logger.exception("update task status failed")
        raise
