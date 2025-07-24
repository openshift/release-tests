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

        logger.info("Checking for blocking security alerts across all advisories...")

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
                        logger.warning(f"BLOCKING: Advisory {advisory.errata_id} has blocking security alerts!")
                    else:
                        logger.debug(f"OK: Advisory {advisory.errata_id} has no blocking security alerts")
                else:
                    advisory_info["reason"] = "RHBA advisories don't have security alerts"
                    logger.debug(f"SKIP: Skipping {advisory.errata_type} advisory {advisory.errata_id} (no security alerts)")

            except Exception as e:
                advisory_info["error"] = str(e)
                details["errors"].append(advisory_info)
                logger.error(f"ERROR: Error checking advisory {advisory.errata_id}: {e}")

            details["checked_advisories"].append(advisory_info)

        # Log summary
        total_advisories = len(details["checked_advisories"])
        rhsa_checked = len([a for a in details["checked_advisories"] if a.get("checked", False)])
        blocking_count = len(details["blocking_advisories"])
        error_count = len(details["errors"])

        logger.info(f"CHECK: Security alert check complete: {total_advisories} total, {rhsa_checked} RHSA checked, {blocking_count} blocking, {error_count} errors")

        if blocking_count > 0:
            blocking_ids = [str(a["errata_id"]) for a in details["blocking_advisories"]]
            logger.warning(f"WARNING: Blocking alerts found in advisories: {', '.join(blocking_ids)}")

        # Output results in text format
        click.echo(f"CHECK: Blocking Security Alerts Check for {cs.release}")
        click.echo("=" * 50)

        total_advisories = len(details['checked_advisories'])
        rhsa_checked = len([a for a in details['checked_advisories'] if a.get('checked', False)])
        blocking_count = len(details['blocking_advisories'])
        error_count = len(details['errors'])

        click.echo(f"SUMMARY:")
        click.echo(f"  • Total advisories: {total_advisories}")
        click.echo(f"  • RHSA advisories checked: {rhsa_checked}")
        click.echo(f"  • Blocking advisories found: {blocking_count}")
        click.echo(f"  • Errors encountered: {error_count}")
        click.echo()

        if has_blocking:
            click.echo(f"WARNING: BLOCKING SECURITY ALERTS DETECTED:")
            for advisory in details['blocking_advisories']:
                click.echo(f"    ALERT: Advisory {advisory['errata_id']} ({advisory['type']}/{advisory['impetus']})")
                click.echo(f"       URL: https://errata.devel.redhat.com/advisory/{advisory['errata_id']}")
            click.echo()
        else:
            click.echo("OK: No blocking security alerts found")
            click.echo()

        # Show checked advisories details
        if details['checked_advisories']:
            click.echo("INFO: Advisory Details:")
            for advisory in details['checked_advisories']:
                status_icon = "ALERT" if advisory.get('has_blocking') else "OK" if advisory.get('checked') else "SKIP"
                reason = ""
                if not advisory.get('checked', True) and 'reason' in advisory:
                    reason = f" ({advisory['reason']})"
                elif 'error' in advisory:
                    reason = f" (Error: {advisory['error']})"
                    status_icon = "ERROR"

                click.echo(f"  {status_icon} {advisory['errata_id']} ({advisory['type']}/{advisory['impetus']}){reason}")

        if details['errors']:
            click.echo()
            click.echo("ERRORS:")
            for error_advisory in details['errors']:
                click.echo(f"  • Advisory {error_advisory['errata_id']}: {error_advisory['error']}")

        # Update worksheet if not in check-only mode
        if not check_only:
            logger.info("Updating Others column with blocking security alerts status...")

            # Add to Others column based on blocking alerts status
            others_added = report.add_security_alert_status_to_others_section(has_blocking, details["blocking_advisories"])
            if others_added:
                if has_blocking:
                    advisory_count = len(details["blocking_advisories"])
                    click.echo(f"INFO: Added hyperlinked blocking sec-alerts to Others column ({advisory_count} advisory{'ies' if advisory_count > 1 else 'y'})")
                else:
                    click.echo(f"INFO: Added 'No Blocking Sec-Alerts' status to Others column")
            else:
                click.echo(f"INFO: Failed to add entry to Others column")


        # Set exit code based on results
        if has_blocking:
            click.echo("\nALERT: Exit code 1: Blocking security alerts detected")
            ctx.exit(1)  # Non-zero exit code indicates blocking alerts found
        else:
            click.echo("\nOK: Exit code 0: No blocking security alerts")
            ctx.exit(0)

    except Exception as e:
        logger.exception("check blocking security alerts failed")
        click.echo(f"ERROR: {e}")
        ctx.exit(2)  # Exit code 2 indicates error in checking
