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
@click.option("-n","--build_number",type=int, help="provide build number to get job status")
def image_signed_check(ctx,build_number):
    """
    Check payload image is well signed
    """
    # get config store from context
    cs = ctx.obj["cs"] 
    jh = JenkinsHelper(cs) 
    if not build_number:
        report = WorksheetManager(cs).get_test_report()
        image_signed_check_result = report.get_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY)
        if image_signed_check_result == TASK_STATUS_PASS:
            logger.info("image signed check already pass, not need to trigger again")
        elif image_signed_check_result == TASK_STATUS_INPROGRESS:   
            logger.info("job[signature_check] already triggered and in progress, not need to trigger again")
        else:
            nm = NotificationManager(cs)
            try: 
                build_url = jh.call_signature_check_job()    
            except JenkinsHelperException as jh:
                logger.exception("trigger signature_check job failed")
                raise
            logger.info(f"triggerred signature_check job: {build_url}")
            nm.sc.post_message(cs.get_slack_channel_from_contact("qe"), "["+cs.release+"] image signed check job: "+build_url)
            report.update_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY, TASK_STATUS_INPROGRESS)
    else: 
        logger.info(f"check signature_check job status according to job id:{build_number}")
        jh.get_job_status(jh.zstream_url, "signature_check", build_number)
