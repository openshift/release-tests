import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import (
    TASK_CHECK_BLOCKING_SEC_ALERTS,
    TASK_STATUS_FAIL,
    TASK_STATUS_INPROGRESS,
    TASK_STATUS_PASS,
)
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException
from oar.core import util

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def check_blocking_sec_alerts(ctx):
    """
    Check for blocking security alerts across all RHSA advisories.
    Reports blocking alerts and updates StateBox task status.
    """
    cs = ctx.obj["cs"]

    try:
        util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_INPROGRESS)

        am = AdvisoryManager(cs)
        statebox = StateBox(cs)
        advisories = am.get_advisories()

        rhsa_advisories = [ad for ad in advisories if ad.errata_type == "RHSA"]
        if not rhsa_advisories:
            logger.info("No RHSA advisories found, skipping security alert check")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)
            return

        logger.info(f"Found {len(rhsa_advisories)} RHSA advisory(ies) to check: "
                     f"{', '.join(str(ad.errata_id) for ad in rhsa_advisories)}")

        blocking_advisories = []
        check_errors = {}

        for advisory in rhsa_advisories:
            try:
                if advisory.has_blocking_security_alert():
                    blocking_advisories.append(advisory)
            except Exception as e:
                check_errors[advisory.errata_id] = str(e)
                logger.error(f"Error checking advisory {advisory.errata_id}: {e}")

        existing_blocker = statebox.get_task_blocker(TASK_CHECK_BLOCKING_SEC_ALERTS)
        if existing_blocker:
            statebox.resolve_issue(
                issue=existing_blocker["issue"],
                resolution="Re-checked blocking security alerts",
            )

        if blocking_advisories:
            logger.warning("BLOCKING SECURITY ALERTS FOUND:")
            advisory_details = []
            for advisory in blocking_advisories:
                link = util.get_advisory_link(str(advisory.errata_id))
                logger.warning(f"  RHSA advisory {advisory.errata_id} - {link}")
                advisory_details.append(f"- RHSA advisory {advisory.errata_id}: {link}")

            issue_description = (
                f"Found blocking security alerts in {len(blocking_advisories)} RHSA advisory(ies)\n\n"
                f"Affected advisories:\n" + "\n".join(advisory_details)
            )
            try:
                statebox.add_issue(
                    issue=issue_description,
                    blocker=True,
                    related_tasks=[TASK_CHECK_BLOCKING_SEC_ALERTS],
                    auto_save=True,
                )
                logger.info(f"Created blocking issue in StateBox for {len(blocking_advisories)} RHSA advisory(ies)")
            except StateBoxException as e:
                logger.warning(f"Could not add StateBox issue (may already exist): {e}")

            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        elif check_errors:
            error_details = "; ".join(f"{eid}: {err}" for eid, err in check_errors.items())
            logger.warning(f"Security-alert checks failed for: {error_details}")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        else:
            logger.info("No blocking security alerts found")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)

    except Exception as e:
        logger.exception("check blocking sec-alerts failed")
        util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        raise
