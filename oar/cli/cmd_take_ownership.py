import logging

import click

from oar.core.const import *
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.util import is_valid_email
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)

def validate_email_for_cli(email):
    """Validate email address using util.validate_email and raise click exception if invalid"""
    if not is_valid_email(email):
        raise click.BadParameter(f"{email} is not a valid email")
    return email


@click.command()
@click.option(
    "-e",
    "--email",
    required=True,
    callback=validate_email_for_cli,
    help="email address of the owner",
)
@click.pass_context
def take_ownership(ctx, email):
    """
    Take ownership for advisory and jira subtasks
    """
    # get config store from context
    cs = ctx.obj["cs"]
    cs.set_owner(email)

    try:
        # get existing report
        wm = WorksheetManager(cs)
        report = wm.get_test_report()
        # update task status to in progress
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_INPROGRESS)
        # add QE release lead comment to shipment merge requests
        shipment = ShipmentData(cs)
        shipment.add_qe_release_lead_comment(email)
        # send notification about ownership change and shipment MRs
        nm = NotificationManager(cs)
        nm.share_shipment_mrs(cs.get_shipment_mrs(), email)
        # update task status to pass
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("take ownership of advisory and jira subtasks failed")
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_FAIL)
        raise
