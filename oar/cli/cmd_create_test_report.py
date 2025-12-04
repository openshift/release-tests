import logging

import click

from oar.core.notification import NotificationManager
from oar.core.worksheet import WorksheetManager, WorksheetException
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException
from oar.core import util

logger = logging.getLogger(__name__)


@click.command()
@click.pass_context
def create_test_report(ctx):
    """
    Create test report for z-stream release
    """
    # get config store from context
    cs = ctx.obj["cs"]

    # Get y-stream version for StateBox path
    y_stream = util.get_y_release(cs.release)
    statebox_path = f"_releases/{y_stream}/statebox/{cs.release}.yaml"

    # Check if StateBox already exists
    try:
        statebox = StateBox(cs)

        if statebox.exists():
            # StateBox already created - just show path and return
            logger.info(f"StateBox already exists for {cs.release} at {statebox_path}")
            return

    except StateBoxException as e:
        logger.warning(f"Failed to check StateBox existence: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error checking StateBox: {e}")

    # StateBox doesn't exist - check if this is old release with existing worksheet
    try:
        wm = WorksheetManager(cs)
        # Try to get existing worksheet (will raise exception if doesn't exist)
        try:
            existing_report = wm.get_test_report()
            # Worksheet exists - this is old release, already created before
            logger.info(f"Found existing worksheet for {cs.release} (old release): {existing_report.get_url()}")
            return
        except WorksheetException:
            # Worksheet doesn't exist - this is new release, will create StateBox
            logger.info(f"No existing worksheet found, will create StateBox for new release {cs.release}")
            pass

    except Exception as e:
        logger.warning(f"Failed to check worksheet existence: {e}")

    # Neither StateBox nor worksheet exists - create StateBox for new release
    try:
        statebox = StateBox(cs)
        logger.info(f"Initializing StateBox for new release {cs.release}")

        # Load will create default state with metadata from ConfigStore
        state = statebox.load()
        # Save to GitHub to persist the initial state
        statebox.save(state, message=f"Initialize StateBox for release {cs.release}")

        statebox_url = f"https://github.com/openshift/release-tests/blob/z-stream/{statebox_path}"

        logger.info(f"StateBox initialized successfully for {cs.release} at {statebox_path}")

        # Send notification for new StateBox creation
        try:
            nm = NotificationManager(cs)
            nm.share_new_statebox(statebox_url, cs.release)
            logger.info(f"Sent notification for StateBox creation: {statebox_url}")
        except Exception as e:
            logger.warning(f"Failed to send notification for StateBox creation: {e}")

    except StateBoxException as e:
        logger.exception("Failed to create StateBox")
        raise
    except Exception as e:
        logger.exception("Unexpected error creating StateBox")
        raise
