import logging

import click

from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.operators import CVETrackerOperator
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)


@click.command()
@click.option("--notify/--no-notify", default=True, help="Send notification to release artist, default value is true")
@click.pass_context
def check_cve_tracker_bug(ctx, notify):
    """
    Check if there is any missed CVE tracker bug from both advisory and shipment data
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init CVE tracker operator
        cve_operator = CVETrackerOperator(cs)
        # update task status to in progress
        report.update_task_status(
            LABEL_TASK_CHECK_CVE_TRACKERS, TASK_STATUS_INPROGRESS)
        # Check for missed CVE tracker bugs from both advisory and shipment sources
        advisory_cve_bugs, shipment_cve_bugs = cve_operator.check_cve_tracker_bugs()
        all_cve_bugs = advisory_cve_bugs + shipment_cve_bugs
        
        if len(all_cve_bugs):
            # Log the source of the missed bugs for debugging
            if advisory_cve_bugs:
                logger.info(f"Found {len(advisory_cve_bugs)} missed CVE tracker bugs in advisories: {advisory_cve_bugs}")
            if shipment_cve_bugs:
                logger.info(f"Found {len(shipment_cve_bugs)} missed CVE tracker bugs in shipments: {shipment_cve_bugs}")
            
            appended = report.append_missed_cve_tracker_bugs(all_cve_bugs)
            if notify and appended:
                # Share notification about all missed CVE tracker bugs
                cve_operator.share_new_cve_tracker_bugs(all_cve_bugs)
        else:
            logger.info("no new CVE tracker bug found in either advisories or shipments")
        
        report.update_task_status(
            LABEL_TASK_CHECK_CVE_TRACKERS, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("check cve tracker bug failed")
        report.update_task_status(
            LABEL_TASK_CHECK_CVE_TRACKERS, TASK_STATUS_FAIL)
        raise
