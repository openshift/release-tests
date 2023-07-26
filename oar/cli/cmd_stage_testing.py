import click
import logging
from oar.core.exceptions import JenkinsHelperException
from oar.core.jenkins_helper import JenkinsHelper
from oar.core.const import *
from oar.core.notification_mgr import NotificationManager
from oar.core.worksheet_mgr import WorksheetManager

logger = logging.getLogger(__name__)

@click.command()
@click.pass_context
@click.option("-n","--build_number",type=int, help="provide build number to get job status")
def stage_testing(ctx, build_number):
    """
    Trigger stage pipeline test
    """
    # get config store from context
    cs = ctx.obj["cs"] 
    jh = JenkinsHelper(cs) 
    report = WorksheetManager(cs).get_test_report()
    if not build_number:
        logger.info("job id is not set, will trigger stage testing")
        try:
            stage_test_result = report.get_task_status(LABEL_TASK_STAGE_TEST)
            if stage_test_result == TASK_STATUS_PASS:
                logger.info("stage testing already pass, not need to trigger again")
            else:
                cdn_result = report.get_task_status(LABEL_TASK_PUSH_TO_CDN)
                if cdn_result == TASK_STATUS_PASS:
                    try:
                        nm = NotificationManager(cs)
                        build_url = jh.call_stage_job()    
                    except JenkinsHelperException as jh:
                        logger.exception("trigger stage pipeline job failed")
                        raise
                    logger.info(f"triggerred stage pipeline job: <{build_url}>")
                    nm.sc.post_message(cs.get_slack_channel_from_contact("qe-release"), "["+cs.release+"] stage testing job: "+build_url)
                    report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_INPROGRESS)
                else:
                    logger.info("push to cdn stage is not completed, so will not trigger stage test")
        except Exception as we:
            logger.exception("trigger stage testing failed")
    else: 
        logger.info(f"check stage job status according to job id:{build_number}")
        job_status= jh.get_job_status(jh.zstream_url, "Stage-Pipeline", build_number)
        if job_status == "SUCCESS":
            report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_PASS)
        elif job_status == "In Progress":
            report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_INPROGRESS)
        else: 
            report.update_task_status(LABEL_TASK_STAGE_TEST, TASK_STATUS_FAIL)

