import logging

import click

from oar.core.const import *
from oar.core.jira import JiraManager
from oar.core.operators import NotificationOperator, ReleaseOwnershipOperator
from oar.core.statebox import StateBox
from oar.core import util

logger = logging.getLogger(__name__)

def validate_email_for_cli(ctx, param, value):
    """Validate email address using util.is_valid_email and raise click exception if invalid"""
    if not util.is_valid_email(value):
        raise click.BadParameter(f"{value} is not a valid email")
    return value


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
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_TAKE_OWNERSHIP, TASK_STATUS_INPROGRESS)

        # update ownership across advisories and shipments
        ro = ReleaseOwnershipOperator(cs)
        updated_ads, abnormal_ads = ro.update_owners(email)

        # Create StateBox blocker issue if abnormal advisories detected
        if abnormal_ads:
            _create_abnormal_advisory_blocker(cs, abnormal_ads)

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

        # Log pass status for cli_result_callback parsing
        util.log_task_status(TASK_TAKE_OWNERSHIP, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("take ownership of advisory and jira subtasks failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_TAKE_OWNERSHIP, TASK_STATUS_FAIL)
        raise


def _create_abnormal_advisory_blocker(cs, abnormal_ads: list) -> None:
    """Create StateBox blocker issue for abnormal advisory states

    Args:
        cs: ConfigStore instance
        abnormal_ads (list): List of advisory IDs with abnormal states
    """
    try:
        statebox = StateBox(cs)

        # Check if StateBox exists (only create blocker for new releases using StateBox)
        if not statebox.exists():
            logger.info("StateBox does not exist, skipping blocker issue creation")
            return

        # Create issue description with advisory IDs
        advisory_ids = ", ".join(str(ad_id) for ad_id in abnormal_ads)
        issue_description = f"Advisories in abnormal state (NEW_FILES instead of QE): {advisory_ids}"

        # Add blocker issue linked to push-to-cdn-staging task
        statebox.add_issue(
            issue=issue_description,
            blocker=True,
            related_tasks=[TASK_PUSH_TO_CDN_STAGING]
        )

        logger.info(f"Created StateBox blocker issue for abnormal advisories: {issue_description}")

    except Exception as e:
        # Log error but don't fail the entire operation
        logger.error(f"Failed to create StateBox blocker issue: {str(e)}")
