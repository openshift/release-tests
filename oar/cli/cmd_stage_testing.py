import click
import logging
from oar.core.exceptions import JenkinsHelperException
from oar.core.jenkins import JenkinsHelper
from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option("-n", "--build_number", type=int, help="provide build number to get job status")
def stage_testing(ctx, build_number):
    """
    Trigger stage pipeline test
    """
    # get config store from context
    cs = ctx.obj["cs"]
    jh = JenkinsHelper(cs)
    nm = NotificationManager(cs)
    report = WorksheetManager(cs).get_test_report()
    if not build_number:
        logger.info("job id is not set, will trigger stage testing")
        try:
            task_status = report.get_task_status(LABEL_TASK_STAGE_TEST)
            if task_status == TASK_STATUS_PASS:
                logger.info(
                    "stage testing already passed, no need to trigger again")
            elif task_status == TASK_STATUS_INPROGRESS:
                logger.info(
                    "job [Stage-Pipeline] already triggered and in progress, no need to trigger again"
                )
            else:
                cdn_result = report.get_task_status(LABEL_TASK_PUSH_TO_CDN)
                if cdn_result == TASK_STATUS_PASS:
                    build_url = ""
                    try:
                        if jh.is_job_enqueue(JENKINS_JOB_STAGE_PIPELINE):
                            logger.info(
                                f"there is pending job in the queue, please try again later")
                        else:
                            build_url = jh.call_stage_job()
                            logger.info(
                                f"triggered stage pipeline job: <{build_url}>")
                    except JenkinsHelperException as jh:
                        logger.exception("trigger stage pipeline job failed")
                        raise

                    if build_url:
                        nm.share_jenkins_build_url(
                            JENKINS_JOB_STAGE_PIPELINE[9:], build_url)
                        report.update_task_status(
                            LABEL_TASK_STAGE_TEST, TASK_STATUS_INPROGRESS)
                else:
                    logger.info(
                        "push to cdn stage is not completed, will not trigger stage test")
        except Exception as we:
            logger.exception("trigger stage testing failed")
    else:
        logger.info(
            f"check stage job status according to job id: {build_number}")
        job_status = jh.get_build_status(
            JENKINS_JOB_STAGE_PIPELINE, build_number)
        if job_status == JENKINS_JOB_STATUS_SUCCESS:
            report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_PASS)
        elif job_status == JENKINS_JOB_STATUS_IN_PROGRESS:
            report.update_task_status(
                LABEL_TASK_STAGE_TEST, TASK_STATUS_INPROGRESS)
        else:
            report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_FAIL)
