import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def drop_bugs(ctx):
    """
    Drop bugs from advisories
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # init shipment data
        sd = ShipmentData(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_INPROGRESS)
        # check doc and product security approval advisories
        # TODO: need to confirm how to collabrate with doc and prodsec team 
        approved_doc_ads, approved_prodsec_ads = am.get_doc_prodsec_approved_ads()
        dropped_bugs, high_severity_bugs = sd.drop_bugs()
        # check if all bugs are verified
        nm = NotificationManager(cs)
        requested_doc_ads = []
        requested_prodsec_ads = []
        if len(dropped_bugs) or len(high_severity_bugs):
            logger.info("updating test report")
            report.update_bug_list(am.get_jira_issues())
            NotificationManager(cs).share_dropped_and_high_severity_bugs(
                dropped_bugs, high_severity_bugs
            )
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
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_PASS)
        report.update_task_status(LABEL_TASK_BUGS_TO_VERIFY, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("Drop bugs from advisories failed")
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_FAIL)
        raise
