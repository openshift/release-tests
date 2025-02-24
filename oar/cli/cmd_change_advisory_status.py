import click
import logging
from oar.core.worksheet import WorksheetManager
from oar.core.advisory import AdvisoryManager
from oar.core.jira import JiraManager
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import AdvisoryException

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
@click.option(
    "-s",
    "--status",
    default=AD_STATUS_REL_PREP,
    help="Valid advisory status, default is REL_PREP",
)
def change_advisory_status(ctx, status):
    """
    Change advisory status e.g. QE, REL_PREP
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_INPROGRESS)
        # check kernel tag before change advisories' status
        ads = am.get_advisories()
        for ad in ads:
            if ad.check_kernel_tag():
                raise AdvisoryException("kernel tag early-kernel-stop-ship is found, stop moving advisory status, please check.")
        # change all advisories' status
        am.change_advisory_status(status)
        # close jira tickets
        jm = JiraManager(cs)
        jm.close_qe_subtasks()
        # if no exception occurred, update task status to pass
        report.update_task_status(LABEL_TASK_NIGHTLY_BUILD_TEST, TASK_STATUS_PASS)
        report.update_task_status(LABEL_TASK_SIGNED_BUILD_TEST, TASK_STATUS_PASS)   
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception(f"change advisory status to {status} failed")
        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
        raise
