import logging

import click

from oar.core.const import *
from oar.core.operators import CVETrackerOperator
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException
from oar.core import util

logger = logging.getLogger(__name__)


@click.command()
@click.option("--notify/--no-notify", default=True, help="Send notification to release artist, default value is true")
@click.pass_context
def check_cve_tracker_bug(ctx, notify):
    """
    Check if there is any missed CVE tracker bug from both advisory and shipment data.
    Creates blocking issue in StateBox when CVE bugs are found.
    """
    # get config store from context
    cs = ctx.obj["cs"]

    try:
        # Initialize CVE tracker operator and StateBox
        cve_operator = CVETrackerOperator(cs)
        statebox = StateBox(cs)

        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_INPROGRESS)

        # Check for missed CVE tracker bugs from both advisory and shipment sources
        advisory_cve_bugs, shipment_cve_bugs = cve_operator.check_cve_tracker_bugs()
        all_cve_bugs = advisory_cve_bugs + shipment_cve_bugs

        if len(all_cve_bugs):
            # Log the source of the missed bugs for debugging
            if advisory_cve_bugs:
                logger.info(f"Found {len(advisory_cve_bugs)} missed CVE tracker bugs in advisories: {[str(bug) for bug in advisory_cve_bugs]}")
            if shipment_cve_bugs:
                logger.info(f"Found {len(shipment_cve_bugs)} missed CVE tracker bugs in shipments: {[str(bug) for bug in shipment_cve_bugs]}")

            # Create blocking issue in StateBox with detailed bug information
            issue_description = f"Found {len(all_cve_bugs)} missed CVE tracker bugs"
            if advisory_cve_bugs and shipment_cve_bugs:
                issue_description += f": {len(advisory_cve_bugs)} in advisories, {len(shipment_cve_bugs)} in shipments"
            elif advisory_cve_bugs:
                issue_description += f" in advisories"
            elif shipment_cve_bugs:
                issue_description += f" in shipments"

            # Add bug details
            issue_description += f"\n\nMissed CVE tracker bugs:\n"
            for bug in all_cve_bugs:
                issue_description += f"- {bug}\n"

            statebox.add_issue(
                issue=issue_description,
                blocker=True,
                related_tasks=[TASK_CHECK_CVE_TRACKER_BUG],
                auto_save=True
            )
            logger.info(f"Created blocking issue in StateBox for {len(all_cve_bugs)} CVE tracker bugs")

            # Send notification
            if notify:
                cve_operator.share_new_cve_tracker_bugs(all_cve_bugs)

            # Log fail status for cli_result_callback parsing (CVE bugs found = failure)
            util.log_task_status(TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_FAIL)
        else:
            logger.info("no new CVE tracker bug found in either advisories or shipments")
            # Log pass status for cli_result_callback parsing
            util.log_task_status(TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_PASS)

    except Exception as e:
        logger.exception("check cve tracker bug failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_FAIL)
        raise
