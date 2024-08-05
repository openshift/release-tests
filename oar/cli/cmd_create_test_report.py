import click
import logging
import oar.core.util as util
from oar.core.worksheet import WorksheetManager, WorksheetException
from oar.core.notification import NotificationManager, NotificationException

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

    # send notification via email and slack
    try:
        nm = NotificationManager(cs)
        nm.share_new_report(report)
    except NotificationException as ne:
        logger.exception("send notification failed")
        raise
