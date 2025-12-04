import logging

import click

from oar.core.operators import ApprovalOperator, BugOperator
from oar.core.const import *
from oar.core.exceptions import AdvisoryException
from oar.core.jira import JiraManager
from oar.core import util

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
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_CHANGE_ADVISORY_STATUS, TASK_STATUS_INPROGRESS)

        # init approval operator
        ao = ApprovalOperator(cs)
        # check all jira issues (advisory and shipment) are finished or dropped before moving the status
        bo = BugOperator(cs)
        if not bo.has_finished_all_jiras():
            raise AdvisoryException(f"there are unfinished jiras, please check or drop them manually before moving the status")
        # check kernel tag before change advisories' status
        ads = ao._am.get_advisories()
        for ad in ads:
            if ad.check_kernel_tag():
                raise AdvisoryException("kernel tag early-kernel-stop-ship is found, stop moving advisory status, please check.")
        # change all advisories' status
        result = ao.approve_release()
        # close jira tickets
        jm = JiraManager(cs)
        jm.close_qe_subtasks()
        # only update task status to pass if approvals fully completed
        if result is True:
            # Log pass status for cli_result_callback parsing
            util.log_task_status(TASK_CHANGE_ADVISORY_STATUS, TASK_STATUS_PASS)
        elif result == "SCHEDULED":
            logger.info("Background metadata checker process started. Task status will be updated when metadata URL becomes accessible.")
            # Task remains INPROGRESS - background process will handle completion
        # otherwise task remains INPROGRESS for next attempt
        else:
            logger.info("Not all the release resources are approved e.g. ET advisories are not updated yet. Please try again later")
    except Exception as e:
        logger.exception(f"change advisory status to {status} failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_CHANGE_ADVISORY_STATUS, TASK_STATUS_FAIL)
        raise
