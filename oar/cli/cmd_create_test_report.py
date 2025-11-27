import logging

import click

from oar.core.notification import NotificationManager, NotificationException
from oar.core.worksheet import WorksheetManager, WorksheetException, WorksheetExistsException
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def create_test_report(ctx):
    """
    Create test report for z-stream release
    """
    # get config store from context
    cs = ctx.obj["cs"]

    # Initialize StateBox before creating test report
    try:
        statebox = StateBox(cs)

        # Initialize state if it doesn't exist yet
        if not statebox.exists():
            logger.info(f"Initializing StateBox for {cs.release}")
            # Load will create default state with metadata from ConfigStore
            state = statebox.load()
            # Save to GitHub to persist the initial state
            statebox.save(state, message=f"Initialize StateBox for release {cs.release}")
            logger.info(f"StateBox initialized successfully for {cs.release}")
        else:
            logger.info(f"StateBox already exists for {cs.release}")
    except StateBoxException as e:
        logger.warning(f"Failed to initialize StateBox for {cs.release}: {e}")
        logger.warning("Continuing with test report creation despite StateBox initialization failure")
    except Exception as e:
        logger.warning(f"Unexpected error initializing StateBox for {cs.release}: {e}")
        logger.warning("Continuing with test report creation despite StateBox initialization failure")

    # init worksheet manager
    try:
        wm = WorksheetManager(cs)
        report = wm.create_test_report()
    except WorksheetExistsException:
        return
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
