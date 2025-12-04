import logging
import click

from oar.core.const import *
from oar.core.exceptions import JenkinsException
from oar.core.jenkins import JenkinsHelper
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.statebox import StateBox
from oar.core import util

logger = logging.getLogger(__name__)


class StageTesting:
    """Class encapsulating all stage testing operations"""

    def __init__(self, cs):
        """Initialize all core modules"""
        self.jh = JenkinsHelper(cs)
        self.nm = NotificationManager(cs)
        self.sd = ShipmentData(cs)
        self.statebox = StateBox(cs)

    def check_job_status(self, build_number):
        """Check status of existing stage testing job"""
        logger.info(f"check stage job status according to job id: {build_number}")

        job_status = self.jh.get_build_status(JENKINS_JOB_STAGE_PIPELINE, build_number)
        if job_status == JENKINS_JOB_STATUS_SUCCESS:
            task_status = TASK_STATUS_PASS
        elif job_status == JENKINS_JOB_STATUS_IN_PROGRESS:
            task_status = TASK_STATUS_INPROGRESS
        else:
            task_status = TASK_STATUS_FAIL

        # Log status for cli_result_callback parsing
        util.log_task_status(TASK_STAGE_TESTING, task_status)

    def trigger_new_job(self):
        """Trigger a new stage testing job"""
        logger.info("job id is not set, will trigger stage testing")
        try:
            # Check task status from StateBox
            task_status = self.statebox.get_task_status(TASK_STAGE_TESTING)

            if task_status in [TASK_STATUS_PASS, TASK_STATUS_INPROGRESS]:
                status_msg = "already passed" if task_status == TASK_STATUS_PASS else "already triggered and in progress"
                logger.info(f"stage testing {status_msg}, no need to trigger again")
                return

            if self.sd._cs.is_konflux_flow() and not self.sd.is_stage_release_success():
                logger.info("stage release pipeline is not success, will not trigger stage test")
                return

            self._trigger_stage_job()
        except Exception as we:
            logger.exception("trigger stage testing failed")
            # Log fail status for cli_result_callback parsing
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_FAIL)
            raise

    def _trigger_stage_job(self):
        """Internal method to trigger the actual stage job"""
        if self.jh.is_job_enqueue(JENKINS_JOB_STAGE_PIPELINE):
            logger.info("there is pending job in the queue, please try again later")
            return

        try:
            # Log in-progress status for cli_result_callback parsing
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_INPROGRESS)

            build_url = self.jh.call_stage_job()
            logger.info(f"triggered stage pipeline job: <{build_url}>")
            if build_url:
                self.nm.share_jenkins_build_url(JENKINS_JOB_STAGE_PIPELINE[9:], build_url)
        except JenkinsException as jh:
            logger.exception("trigger stage pipeline job failed")
            # Log fail status for cli_result_callback parsing
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_FAIL)
            raise


@click.command()
@click.pass_context
@click.option("-n", "--build_number", type=int, help="provide build number to get job status")
def stage_testing(ctx, build_number):
    """Click command wrapper for stage testing operations"""
    cs = ctx.obj["cs"]
    stage_test = StageTesting(cs)
    if build_number:
        stage_test.check_job_status(build_number)
    else:
        stage_test.trigger_new_job()
