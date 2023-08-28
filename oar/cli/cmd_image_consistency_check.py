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
    nm = NotificationManager(cs)
    report = WorksheetManager(cs).get_test_report()

    if not build_number:
        logger.info(
            "job id is not set, will trigger image consistency check job")
        task_status = report.get_task_status(LABEL_TASK_IMAGE_CONSISTENCY_TEST)
        if task_status == TASK_STATUS_PASS:
            logger.info(
                "image consistency check already pass, not need to trigger again"
            )
        elif task_status == TASK_STATUS_INPROGRESS:
            logger.info(
                "job [image-consistency-check] already triggered and in progress, no need to trigger again"
            )
        else:
            build_url = ""
            try:
                if (jh.is_job_enqueue(JENKINS_JOB_IMAGE_CONSISTENCY_CHECK)):
                    logger.warning(
                        f"there is pending job in the queue, please try again later")
                else:
                    build_url = jh.call_image_consistency_job()
                    logger.info(
                        f"triggered image consistency check job: <{build_url}>")
            except JenkinsHelperException as jh:
                logger.exception("trigger image-consistency-check job failed")
                raise
            # send out notification to share new job url
            if build_url:
                nm.share_jenkins_build_url(
                    JENKINS_JOB_IMAGE_CONSISTENCY_CHECK, build_url)
                report.update_task_status(
                    LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_INPROGRESS
                )
    else:
        logger.info(
            f"check image-consistency-check job status with job id:{build_number}"
        )
        job_status = jh.get_build_status(
            "image-consistency-check", build_number)

        if job_status == JENKINS_JOB_STATUS_SUCCESS:
            report.update_task_status(
                LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_PASS)
        elif job_status == JENKINS_JOB_STATUS_IN_PROGRESS:
            report.update_task_status(
                LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_INPROGRESS)
        else:
            report.update_task_status(
                LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_FAIL)
