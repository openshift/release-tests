import logging

import click

from oar.core.const import *
from oar.core.worksheet import WorksheetManager
from oar.core.shipment import ShipmentData
from oar.core.jira import JiraManager

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def add_qe_approval(ctx):
    """
    Add QE approval to shipment data
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init shipment data
        sd = ShipmentData(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_ADD_QE_APPROVAL, TASK_STATUS_INPROGRESS)
        # TODO: check kernel tag and make sure all jira issues are 'finished'
        # add QE approval
        sd.add_qe_approval()
        # close jira tickets
        jm = JiraManager(cs)
        jm.close_qe_subtasks()
        # if no exception occurred, update multiple task statuses to pass
        report.update_task_status(LABEL_TASK_ADD_QE_APPROVAL, TASK_STATUS_PASS)
        report.update_task_status(LABEL_TASK_NIGHTLY_BUILD_TEST, TASK_STATUS_PASS)
        report.update_task_status(LABEL_TASK_SIGNED_BUILD_TEST, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("add QE approval failed")
        report.update_task_status(LABEL_TASK_ADD_QE_APPROVAL, TASK_STATUS_FAIL)
        raise
