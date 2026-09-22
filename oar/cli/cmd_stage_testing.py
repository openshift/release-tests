import logging
import re

import click

from job.job import Jobs
from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.statebox import StateBox
from oar.core import util

logger = logging.getLogger(__name__)


class StageTesting:
    """Class encapsulating all stage testing operations"""

    def __init__(self, cs):
        """Initialize all core modules"""
        self.cs = cs
        self.nm = NotificationManager(cs)
        self.sd = ShipmentData(cs)
        self.statebox = StateBox(cs)
        self.jobs = Jobs()

    def check_job_status(self, job_id):
        """Check status of existing stage testing Prow job"""
        logger.info(f"Checking stage testing Prow job status for job ID: {job_id}")

        job_info = self.jobs.get_job_results(job_id)
        if job_info is None:
            logger.error(f"Could not retrieve job info for job ID: {job_id}")
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_FAIL)
            raise Exception(f"Job {job_id} not found or Prow API error")

        job_state = job_info.get("jobState")
        job_url = job_info.get("jobURL")
        logger.info(f"Job state: {job_state}, URL: {job_url}")

        if job_state == "success":
            task_status = TASK_STATUS_PASS
        elif job_state in ("triggered", "pending"):
            task_status = TASK_STATUS_INPROGRESS
        elif job_state in ("aborted", "error"):
            logger.warning(f"Prow job {job_id} ended with state '{job_state}', resetting for re-trigger")
            task_status = TASK_STATUS_NOT_STARTED
        else:
            task_status = TASK_STATUS_FAIL

        util.log_task_status(TASK_STAGE_TESTING, task_status)

    def trigger_new_job(self):
        """Trigger a new stage testing Prow job"""
        logger.info("Triggering stage testing Prow job")
        try:
            task_status = self.statebox.get_task_status(TASK_STAGE_TESTING)

            if task_status == TASK_STATUS_PASS:
                logger.info("Stage testing already passed, no need to trigger again")
                return

            if task_status == TASK_STATUS_INPROGRESS:
                task = self.statebox.get_task(TASK_STAGE_TESTING)
                result_text = (task or {}).get("result", "") or ""
                match = re.search(r"Triggered stage testing Prow job: (\S+)", result_text)
                if match:
                    existing_job_id = match.group(1)
                    job_info = self.jobs.get_job_results(existing_job_id)
                    job_state = (job_info or {}).get("jobState", "")
                    if job_state in ("triggered", "pending", "success"):
                        logger.info(f"Prow job {existing_job_id} already in state '{job_state}', skipping duplicate trigger")
                        return
                    logger.info(f"Prow job {existing_job_id} ended with state '{job_state}', re-triggering")

            if not self.sd.is_stage_release_success():
                logger.info("Stage release pipeline is not success, will not trigger stage test")
                return

            self._trigger_stage_job()
        except Exception:
            logger.exception("Trigger stage testing failed")
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_FAIL)
            raise

    def _trigger_stage_job(self):
        """Internal method to trigger the actual stage Prow job"""
        try:
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_INPROGRESS)

            payload_url = f"quay.io/openshift-release-dev/ocp-release:{self.cs.release}-x86_64"
            job_status = self.jobs.run_stage_testing(payload_url)
            job_url = job_status.get("jobURL")
            job_id = job_status.get("jobID")
            logger.info(f"Triggered stage testing Prow job: {job_id}")
            logger.info(f"Prow job URL: {job_url}")

            self.nm.share_prow_job_url(
                Jobs.STAGE_TESTING_JOB_NAME_TEMPLATE.format(
                    minor_release=util.get_y_release(self.cs.release)
                ),
                job_url,
            )
        except Exception as e:
            logger.error(f"Failed to trigger stage testing Prow job: {e}")
            util.log_task_status(TASK_STAGE_TESTING, TASK_STATUS_FAIL)
            raise


@click.command()
@click.pass_context
@click.option(
    "-i", "--job-id",
    type=str,
    help="Prow job ID to check status",
)
def stage_testing(ctx, job_id):
    """
    Trigger stage testing or check status of an existing Prow job.

    Triggers a Prow job via Gangway API or checks the status of an existing job.
    """
    cs = ctx.obj["cs"]
    stage_test = StageTesting(cs)
    if job_id:
        stage_test.check_job_status(job_id)
    else:
        stage_test.trigger_new_job()
