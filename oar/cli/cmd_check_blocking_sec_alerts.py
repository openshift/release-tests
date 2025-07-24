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
        details = {
            "checked_advisories": [],
            "blocking_advisories": [],
            "errors": []
        }

        # Check each advisory using existing has_blocking_secruity_alert method
        for advisory in advisories:
            advisory_info = {
                "errata_id": advisory.errata_id,
                "type": advisory.errata_type,
                "impetus": getattr(advisory, 'impetus', 'unknown'),
                "has_blocking": False,
                "checked": False
            }

            try:
                # Only check RHSA advisories (RHBA don't have security alerts)
                if advisory.errata_type == "RHSA":
                    advisory_info["checked"] = True
                    # Use existing has_blocking_secruity_alert method
                    advisory_blocking = advisory.has_blocking_secruity_alert()
                    advisory_info["has_blocking"] = advisory_blocking

                    if advisory_blocking:
                        has_blocking = True
                        details["blocking_advisories"].append(advisory_info)
                else:
                    advisory_info["reason"] = "RHBA advisories don't have security alerts"

            except Exception as e:
                advisory_info["error"] = str(e)
                details["errors"].append(advisory_info)

            details["checked_advisories"].append(advisory_info)

        # Log results - show only RHSA advisories with blocking security alerts
        if has_blocking:
            logger.warning("BLOCKING SECURITY ALERTS FOUND:")
            for advisory in details['blocking_advisories']:
                logger.warning(f"  RHSA {advisory['errata_id']}")
        else:
            logger.info("No blocking security alerts found")

        # Update worksheet if not in check-only mode
        if not check_only:
            others_added = report.add_security_alert_status_to_others_section(has_blocking, details["blocking_advisories"])
            if others_added:
                logger.info("Worksheet updated")
            else:
                logger.error("Failed to update worksheet")


    except Exception as e:
        logger.error(f"Error: {e}")
