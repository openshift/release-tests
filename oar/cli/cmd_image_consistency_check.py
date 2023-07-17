import click
import logging
from oar.core.config_store import ConfigStore
from oar.core.exceptions import JenkinsHelperException
from oar.core.jenkins_helper import JenkinsHelper
from oar.core.const import *
from oar.core.notification_mgr import NotificationManager
from oar.core.worksheet_mgr import WorksheetManager

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option(
    "-n", "--build_number", type=int, help="provide build number to get job status"
)
def image_consistency_check(ctx, build_number):
    """
    Check if images in advisories and payload are consistent
    """
    # get config store from context
    cs = ctx.obj["cs"]
    jh = JenkinsHelper(cs)
    if not build_number:
        logger.info("job id is not set, will trigger image consistency check job")
        report = WorksheetManager(cs).get_test_report()
        image_consistency_result = report.get_task_status(
            LABEL_TASK_IMAGE_CONSISTENCY_TEST
        )
        if image_consistency_result == TASK_STATUS_PASS:
            logger.info(
                "image consistency check already pass, not need to trigger again"
            )
        elif image_consistency_result == TASK_STATUS_INPROGRESS:
            logger.info(
                "job[image-consistency-check] already triggered and in progress, not need to trigger again"
            )
        else:
            nm = NotificationManager(cs)
            try:
                build_url = jh.call_image_consistency_job()
            except JenkinsHelperException as jh:
                logger.exception("trigger image-consistency-check job failed")
                raise
            logger.info(f"triggerred image consistency check job: <{build_url}>")
            nm.sc.post_message(
                cs.get_slack_channel_from_contact("qe"),
                "[" + cs.release + "] image-consistency-check job: " + build_url,
            )
            report.update_task_status(
                LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_INPROGRESS
            )
    else:
        logger.info(
            f"check image-consistency-check job status with job id:{build_number}"
        )
        jh.get_job_status(
            cs.get_jenkins_server(), "image-consistency-check", build_number
        )
