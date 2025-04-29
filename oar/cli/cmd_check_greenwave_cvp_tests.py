import logging

import click

from oar.core.advisory import AdvisoryManager
from oar.core.const import *
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.worksheet import WorksheetManager

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
            # create jira ticket under project CVP with abnormal test details
            jm = JiraManager(cs)
            if not jm.is_cvp_issue_reported():
                issue = jm.create_cvp_issue(abnormal_tests)
                # Update test report
                issue_key = issue.get_key()
                report.add_jira_to_others_section(issue_key)
                # Send Slack notification
                NotificationManager(cs).share_greenwave_cvp_failures(issue_key)
        else:
            report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_PASS)
    except Exception as e:
        logger.exception("check Greenwave CVP test failed")
        report.update_task_status(LABEL_TASK_GREENWAVE_CVP_TEST, TASK_STATUS_FAIL)
        raise
