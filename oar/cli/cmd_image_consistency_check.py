import click
import logging
from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.exceptions import JenkinsHelperException
from oar.core.jenkins import JenkinsHelper
from oar.core.const import *
from oar.core.notification import NotificationManager
from oar.core.worksheet import WorksheetManager

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option(
    "-n", "--build_number", type=int, help="provide build number to get job status"
)
@click.option(
    "--for_nightly", is_flag=True, help="if has the flag, use candidate nightly build to test, else use stable build to test"
)
def image_consistency_check(ctx, build_number, for_nightly):
    """
    Check if images in advisories and payload are consistent
    """
    # get config store from context
    cs = ctx.obj["cs"]
    jh = JenkinsHelper(cs)
    nm = NotificationManager(cs)
    report = WorksheetManager(cs).get_test_report()
    am = AdvisoryManager(cs)

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
            build_info = ""
            try:
                if (jh.is_job_enqueue(JENKINS_JOB_IMAGE_CONSISTENCY_CHECK)):
                    logger.warning(
                        f"there is pending job in the queue, please try again later")
                else:
                    if for_nightly:
                        if "x86_64" in cs.get_candidate_builds():
                            pull_spec = (
                                "registry.ci.openshift.org/ocp/release:" + cs.get_candidate_builds().get("x86_64") 
                            )
                        else: 
                            raise JenkinsHelperException(
                                f"no candidate nightly build for x86_64 architecture"
                                )
                    else:
                        pull_spec = (
                            "quay.io/openshift-release-dev/ocp-release:" + cs.release + "-x86_64" 
                        )  
                    build_info = jh.call_image_consistency_job(pull_spec)
                    logger.info(
                        f"triggered image consistency check job: <{build_info}>")
            except JenkinsHelperException as jh:
                logger.exception("trigger image-consistency-check job failed")
                raise
            # send out notification to share new job url
            if build_info:
                nm.share_jenkins_build_url(
                    JENKINS_JOB_IMAGE_CONSISTENCY_CHECK, build_info)
                report.update_task_status(
                    LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_INPROGRESS
                )
    else:
        if(for_nightly):
            logger.error(f"no need to add '--for_nightly' option, if just want to check job status")
        else: 
            logger.info(
                f"check image-consistency-check job status with job id: {build_number}"
            )
            job_status = jh.get_build_status(
                "image-consistency-check", build_number)

            if job_status == JENKINS_JOB_STATUS_SUCCESS:
                # TODO run the advisories check only when consistency check passed?
                if am.all_advisories_grades_healthy():
                    report.update_task_status(
                        LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_PASS)
                else:
                    report.update_task_status(
                        LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_FAIL)
            elif job_status == JENKINS_JOB_STATUS_IN_PROGRESS:
                report.update_task_status(
                    LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_INPROGRESS)
            else:
                report.update_task_status(
                    LABEL_TASK_IMAGE_CONSISTENCY_TEST, TASK_STATUS_FAIL)
