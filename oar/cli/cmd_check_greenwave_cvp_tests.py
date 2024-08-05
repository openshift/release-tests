import click
import logging
from oar.core.worksheet import WorksheetManager
from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def check_greenwave_cvp_tests(ctx):
    """
    Check Greenwave CVP test results for all advisories
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_INPROGRESS)
        # check the greenwave test results for all advisories
        abnormal_tests = am.check_greenwave_cvp_tests()
        # check if all bugs are verified
        if len(abnormal_tests):
            report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_FAIL)
            # TODO: create jira ticket under proejct CVP with abnormal test details
            # TODO: send slack notification
        else:
            report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("check Greenwave CVP test failed")
        report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_FAIL)
        raise
