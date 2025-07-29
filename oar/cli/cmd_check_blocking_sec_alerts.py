import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import *
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)

@click.command()
@click.option("--check-only", is_flag=True, default=False, help="Only check for blocking alerts without updating worksheet")
@click.pass_context
def check_blocking_sec_alerts(ctx, check_only):
    """
    Check for blocking security alerts across all advisories and update Others column with results
    """
    # get config store from context
    cs = ctx.obj["cs"]

    try:
        # Get existing report
        wm = WorksheetManager(cs)
        report = wm.get_test_report()



        # Get all advisories and check them directly
        am = AdvisoryManager(cs)
        advisories = am.get_advisories()

        # Initialize result structure
        has_blocking = False
        blocking_advisories = []

        # Check each advisory using existing has_blocking_secruity_alert method
        for advisory in advisories:
            try:
                # Only check RHSA advisories (RHBA don't have security alerts)
                if advisory.errata_type == "RHSA":
                    # Use existing has_blocking_secruity_alert method
                    advisory_blocking = advisory.has_blocking_secruity_alert()

                    if advisory_blocking:
                        has_blocking = True
                        blocking_advisories.append(advisory)

            except Exception as e:
                logger.error(f"Error checking advisory {advisory.errata_id}: {e}")

        # Log results - show only RHSA advisories with blocking security alerts
        if has_blocking:
            logger.warning("BLOCKING SECURITY ALERTS FOUND:")
            for advisory in blocking_advisories:
                logger.warning(f"  RHSA {advisory.errata_id}")
        else:
            logger.info("No blocking security alerts found")

        # Update worksheet if not in check-only mode
        if not check_only:
            if report.add_security_alert_status_to_others_section(has_blocking, blocking_advisories):
                logger.info("Worksheet updated")
            else:
                logger.error("Failed to update worksheet")


    except Exception as e:
        logger.error(f"Error: {e}")
