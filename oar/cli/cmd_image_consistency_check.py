import logging

import click
from oar.core.const import *
from oar.core.exceptions import JenkinsException
from oar.core.jenkins import JenkinsHelper
from oar.core.notification import NotificationManager
from oar.core.operators import ImageHealthOperator
from oar.core.statebox import StateBox
from oar.core import util

logger = logging.getLogger(__name__)

class ImageConsistencyChecker:
    def __init__(self, cs):
        self.cs = cs
        self.jh = JenkinsHelper(cs)
        self.nm = NotificationManager(cs)
        self.io = ImageHealthOperator(cs)
        self.statebox = StateBox(cs)

    def trigger_job(self, for_nightly):
        """
        Trigger image consistency check job if needed

        Args:
            for_nightly (bool): Whether to use nightly build or stable build
        """
        # Check task status from StateBox
        task_status = self.statebox.get_task_status(TASK_IMAGE_CONSISTENCY_CHECK)
        if task_status in [TASK_STATUS_PASS, TASK_STATUS_INPROGRESS]:
            logger.info(f"Image consistency check already {task_status}, skipping")
            return

        if self.jh.is_job_enqueue(JENKINS_JOB_IMAGE_CONSISTENCY_CHECK):
            logger.warning("There is pending job in the queue, please try again later")
            return

        try:
            # Log in-progress status for cli_result_callback parsing
            util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, TASK_STATUS_INPROGRESS)

            pull_spec = self._get_pull_spec(for_nightly)
            build_info = self.jh.call_image_consistency_job(pull_spec)
            logger.info(f"Triggered image consistency check job: {build_info}")

            self.nm.share_jenkins_build_url(JENKINS_JOB_IMAGE_CONSISTENCY_CHECK, build_info)
        except JenkinsException as je:
            logger.error(f"Failed to trigger image-consistency-check job: {str(je)}")
            # Log fail status for cli_result_callback parsing
            util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, TASK_STATUS_FAIL)
            raise

    def _get_pull_spec(self, for_nightly):
        """Get pull spec based on build type"""
        if for_nightly:
            if "x86_64" not in self.cs.get_candidate_builds():
                raise JenkinsException("No candidate nightly build for architecture x86_64")
            return f"registry.ci.openshift.org/ocp/release:{self.cs.get_candidate_builds().get('x86_64')}"
        return f"quay.io/openshift-release-dev/ocp-release:{self.cs.release}-x86_64"

    def check_job_status(self, build_number):
        """Check job status and update report accordingly"""
        logger.info(f"Checking image-consistency-check job status with job id: {build_number}")

        job_status = self.jh.get_build_status("image-consistency-check", build_number)
        if job_status == JENKINS_JOB_STATUS_SUCCESS:
            # call ImageHealthOperator to check container health, it can handle errata or konflux flow automatically
            healthy = self.io.check_image_health()
            task_status = TASK_STATUS_PASS if healthy else TASK_STATUS_FAIL
        elif job_status == JENKINS_JOB_STATUS_IN_PROGRESS:
            task_status = TASK_STATUS_INPROGRESS
        else:
            task_status = TASK_STATUS_FAIL

        # Log status for cli_result_callback parsing
        util.log_task_status(TASK_IMAGE_CONSISTENCY_CHECK, task_status)

@click.command()
@click.pass_context
@click.option("-n", "--build_number", 
              type=int, 
              help="Build number to check job status")
@click.option("--for_nightly", 
              is_flag=True,
              help="Use candidate nightly build instead of stable build")
def image_consistency_check(ctx, build_number, for_nightly):
    """
    Check if images in advisories and payload are consistent
    """
    if build_number and for_nightly:
        raise click.UsageError("Cannot use --for_nightly with build number")
        
    checker = ImageConsistencyChecker(ctx.obj["cs"])
    
    if build_number:
        checker.check_job_status(build_number)
    else:
        checker.trigger_job(for_nightly)
