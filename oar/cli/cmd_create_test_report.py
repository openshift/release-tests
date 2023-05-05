import click
import logging
import oar.core.util as util
from oar.core.worksheet_mgr import WorksheetManager, WorksheetException

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def create_test_report(ctx):
    """
    Create test report for z-stream release
    """
    # get config store from context
    cs = ctx.obj["cs"]
    # init worksheet manager
    try:
        wm = WorksheetManager(cs)
        report = wm.create_test_report()
    except WorksheetException as we:
        logger.exception("create new test report failed")
        raise

    logger.info(f"new test report is created: {report.get_url()}")

    # TODO: update assignee of JIRA tasks
    # TODO: send email to QE and ART
