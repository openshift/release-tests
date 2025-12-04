import logging

import click

from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.operators import BugOperator
from oar.core.worksheet import WorksheetManager
from oar.core import util

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def drop_bugs(ctx):
    """
    Drop bugs from advisories

    If new pre-merge verification method is active, we only pick up verified bugs to shipment resource
    QE leads don't have to drop bugs

    NOTE: This command is not needed in Konflux release flow.
    Kept for backward compatibility with Errata flow releases.
    """
    # get config store from context
    cs = ctx.obj["cs"]

    # Prevent execution in Konflux flow
    if cs.is_konflux_flow():
        raise click.UsageError("This command is not supported in Konflux release flow. Skipping.")

    try:
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_DROP_BUGS, TASK_STATUS_INPROGRESS)

        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init bug operator
        operator = BugOperator(cs)
        # check doc and product security approval advisories
        # TODO: need to confirm how to collabrate with doc and prodsec team
        approved_doc_ads, approved_prodsec_ads = operator._am.get_doc_prodsec_approved_ads()
        dropped_bugs = operator.drop_bugs()
        # check if all bugs are verified
        nm = NotificationManager(cs)
        requested_doc_ads = []
        requested_prodsec_ads = []
        if len(dropped_bugs):
            logger.info("updating test report")
            report.update_bug_list(operator.get_jira_issues(), dropped_bugs)
            nm.share_dropped_bugs(dropped_bugs)
            if len(approved_doc_ads):
                for ad in approved_doc_ads:
                    ad.refresh()
                    if not ad.is_doc_approved() and not ad.is_doc_requested():
                        ad.request_doc_approval()
                        requested_doc_ads.append(ad.errata_id)
            if len(approved_prodsec_ads):
                for ad in approved_prodsec_ads:
                    ad.refresh()
                    if ad.is_prodsec_requested() == 'null':
                        ad.request_prodsec_approval()
                        requested_prodsec_ads.append(ad.errata_id)
            logger.info(
                f"request doc and prodsec advisories are: {requested_doc_ads} and {requested_prodsec_ads}")
        nm.share_doc_prodsec_approval_result(
            requested_doc_ads, requested_prodsec_ads)
        # Log pass status for cli_result_callback parsing
        util.log_task_status(TASK_DROP_BUGS, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("Drop bugs from advisories failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_DROP_BUGS, TASK_STATUS_FAIL)
        raise
