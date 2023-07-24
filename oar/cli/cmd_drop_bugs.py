import click
import logging
from oar.core.worksheet_mgr import WorksheetManager
from oar.core.advisory_mgr import AdvisoryManager
from oar.core.config_store import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def drop_bugs(ctx):
    """
    Drop bugs from advisories
    """
    # get config store from context
    cs = ctx.obj["cs"]
    try:
        # get existing report
        report = WorksheetManager(cs).get_test_report()
        # init advisory manager
        am = AdvisoryManager(cs)
        # update task status to in progress
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_INPROGRESS)
        # check the greenwave test results for all advisories
        dropped_bugs, must_verify_bugs = am.drop_bugs()
        # check if all bugs are verified
        if len(dropped_bugs):
            logger.info("updating test report")
            report.update_bug_list(am.get_jira_issues())
            # TODO: send slack message to notify dropped bugs and must verified bugs
            pass
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_PASS)
        report.update_task_status(LABEL_TASK_BUGS_TO_VERIFY, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("Drop bugs from advisories failed")
        report.update_task_status(LABEL_TASK_DROP_BUGS, TASK_STATUS_FAIL)
        raise
