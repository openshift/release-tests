import logging

import click

from oar.core.const import *
from oar.core.jira import JiraManager
from oar.core.operators import NotificationOperator, ReleaseOwnershipOperator
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
        # update ownership across advisories and shipments
        ro = ReleaseOwnershipOperator(cs)
        updated_ads, abnormal_ads = ro.update_owners(email)
        # update assignee of QE subtasks
        updated_subtasks = JiraManager(cs).change_assignee_of_qe_subtasks()
        # send notification about ownership change and shipment MRs
        no = NotificationOperator(cs)
        no.share_ownership_change(
            updated_ads,
            abnormal_ads,
            updated_subtasks,
            email
        )
        # update task status to pass
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("take ownership of advisory and jira subtasks failed")
        report.update_task_status(LABEL_TASK_OWNERSHIP, TASK_STATUS_FAIL)
        raise
