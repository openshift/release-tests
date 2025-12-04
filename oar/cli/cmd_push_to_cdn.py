import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import *
from oar.core import util

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
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_PUSH_TO_CDN_STAGING, TASK_STATUS_INPROGRESS)

        # init advisory manager
        am = AdvisoryManager(cs)
        # trigger push job for cdn stage targets
        # only mark the task to pass when all jobs are completed
        all_jobs_completed = am.push_to_cdn_staging()
        if all_jobs_completed:
            # Log pass status for cli_result_callback parsing
            util.log_task_status(TASK_PUSH_TO_CDN_STAGING, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("push to cdn staging failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_PUSH_TO_CDN_STAGING, TASK_STATUS_FAIL)
        raise
