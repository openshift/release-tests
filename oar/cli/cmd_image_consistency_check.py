import logging

import click

from job.job import Jobs
from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.operators import ImageHealthOperator
from oar.core.statebox import StateBox
from oar.core import util

logger = logging.getLogger(__name__)


class ImageConsistencyChecker:
    def __init__(self, cs):
        self.cs = cs
        self.nm = NotificationManager(cs)
        self.io = ImageHealthOperator(cs)
        self.statebox = StateBox(cs)
        self.jobs = Jobs()

    def trigger_job(self):
        """Trigger image consistency check Prow job."""
        task_status = self.statebox.get_task_status(TASK_IMAGE_CONSISTENCY_CHECK)
        if task_status in [TASK_STATUS_PASS, TASK_STATUS_INPROGRESS]:
            logger.info(f"Image consistency check already {task_status}, skipping")
            return

        try:
            util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, TASK_STATUS_INPROGRESS)

            payload_url = f"quay.io/openshift-release-dev/ocp-release:{self.cs.release}-x86_64"
            mr_url = self.cs.get_shipment_mr()
            if not mr_url:
                raise Exception(
                    f"No shipment MR found for release {self.cs.release}. "
                    "Image consistency check requires Konflux flow with a shipment MR."
                )
            _, mr_id = util.parse_mr_url(mr_url)

            job_status = self.jobs.run_image_consistency_check(payload_url, mr_id)
            job_url = job_status.get("jobURL")
            job_id = job_status.get("jobID")
            logger.info(f"Triggered image consistency check Prow job: {job_id}")
            logger.info(f"Prow job URL: {job_url}")

            self.nm.share_prow_job_url(Jobs.IMAGE_CONSISTENCY_CHECK_JOB_NAME, job_url)
        except Exception as e:
            logger.error(f"Failed to trigger image consistency check Prow job: {e}")
            util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, TASK_STATUS_FAIL)
            raise

    def check_job_status(self, job_id):
        """Check Prow job status and update report accordingly."""
        logger.info(f"Checking image consistency check Prow job status for job ID: {job_id}")

        job_info = self.jobs.get_job_results(job_id)
        if job_info is None:
            logger.error(f"Could not retrieve job info for job ID: {job_id}")
            util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, TASK_STATUS_FAIL)
            raise Exception(f"Job {job_id} not found or Prow API error")

        job_state = job_info.get("jobState")
        job_url = job_info.get("jobURL")
        logger.info(f"Job state: {job_state}, URL: {job_url}")

        if job_state == "success":
            healthy = self.io.check_image_health()
            task_status = TASK_STATUS_PASS if healthy else TASK_STATUS_FAIL
        elif job_state in ("pending", "triggered", ""):
            task_status = TASK_STATUS_INPROGRESS
        else:
            task_status = TASK_STATUS_FAIL

        util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, task_status)


@click.command()
@click.pass_context
@click.option(
    "-i", "--job-id",
    type=str,
    help="Prow job ID to check status",
)
def image_consistency_check(ctx, job_id):
    """
    Check if images in payload are consistent with images in shipment.

    Triggers a Prow job via Gangway API or checks the status of an existing job.
    """
    checker = ImageConsistencyChecker(ctx.obj["cs"])

    if job_id:
        checker.check_job_status(job_id)
    else:
        checker.trigger_job()
