import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import *
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

        blocking_advisories = []
        rhsa_found = 0
        rhsa_checked = 0
        check_errors = {}

        for advisory in advisories:
            try:
                if advisory.errata_type == "RHSA":
                    rhsa_found += 1
                    if advisory.has_blocking_security_alert():
                        blocking_advisories.append(advisory)
                    rhsa_checked += 1
            except Exception as e:
                check_errors[advisory.errata_id] = str(e)
                logger.error(f"Error checking advisory {advisory.errata_id}: {e}")

        if rhsa_found == 0:
            logger.info("No RHSA advisories found, skipping security alert check")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)
            return
        elif rhsa_checked == 0:
            error_details = "; ".join(f"{eid}: {err}" for eid, err in check_errors.items())
            logger.warning(f"Found {rhsa_found} RHSA advisory(ies) but all checks failed: {error_details}")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
            return

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
        else:
            logger.info("No blocking security alerts found")
            util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_PASS)

    except Exception as e:
        logger.exception("check blocking sec-alerts failed")
        util.log_task_status(TASK_CHECK_BLOCKING_SEC_ALERTS, TASK_STATUS_FAIL)
        raise
