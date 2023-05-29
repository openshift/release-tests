import click
import logging
from oar.core.worksheet_mgr import WorksheetManager
from oar.core.advisory_mgr import AdvisoryManager
from oar.core.config_store import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def push_to_cdn_staging(ctx):
    """
    Trigger push job for cdn stage targets
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_PUSH_TO_CDN, TASK_STATUS_INPROGRESS)
        # trigger push job for cdn stage targets
        am.push_to_cdn_staging()
        report.update_task_status(LABEL_TASK_PUSH_TO_CDN, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("push to cdn staging failed")
        report.update_task_status(LABEL_TASK_PUSH_TO_CDN, TASK_STATUS_FAIL)
        raise
