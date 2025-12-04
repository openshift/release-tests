import logging
import time

import click
import requests
from requests.exceptions import InvalidJSONError
from requests.exceptions import RequestException

from oar.core.const import *
from oar.core import util

logger = logging.getLogger(__name__)


# 1. go to main URL and grab all links that match the build type
# 2. construct a complete URL,
def get_image_digest(url, current_try=0):
    logger.info(f"Getting digest from {url}")
    res = requests.get(url)
    if not res.ok:
        logger.info(f"CODE: {res.status_code} -- {res.reason}")
        res.raise_for_status
    change_log_json = res.json().get("changeLogJson")
    if not change_log_json:
        logger.info("No changeLogJson element is found!")
        raise InvalidJSONError("No 'changeLogJson' element is found!")

    digest = change_log_json.get("to").get("digest")
    # if there's no digest found it means the part of the system responsible checks for updated content and if
    # so recycles the underlying pods.  It takes roughly 8 mins for the git-cache to fully recycle.
    # Let's do a brute force try for every 30 seconds.
    max_retries = 16
    sleep_time = 30

    if not digest:
        if current_try == max_retries:
            logger.error(
                f"Image digest failed to show after {max_retries} retries!")
            return
        else:
            logger.debug(f"Current try: {current_try}")
            logger.warning(
                f"E001: No image digest found, going to retry after {sleep_time} seconds"
            )
            time.sleep(sleep_time)
            get_image_digest(url, current_try + 1)
    else:
        logger.info(f"Image Digest: {digest}")
    return digest


@click.command()
@click.pass_context
def image_signed_check(ctx):
    """
    Check payload image is well signed
    """
    cs = ctx.obj["cs"]

    try:
        # Log in-progress status for cli_result_callback parsing
        util.log_task_status(TASK_IMAGE_SIGNED_CHECK, TASK_STATUS_INPROGRESS)

        release_url = (
            cs.get_release_url()
            + "api/v1/releasestream/4-stable/release/"
            + cs.release
        )
        digest_sha = get_image_digest(release_url)
        reformatted_digest = digest_sha.replace(":", "=")
        # 2. query the mirror location
        mirror_url = f"{cs.get_signature_url()}{reformatted_digest}/signature-1"
        logger.info(f"Comparing digest from url: {mirror_url}")
        rest = requests.get(mirror_url)
        rest.raise_for_status()
        if rest.status_code == 200:
            logger.info("Signature check PASSED")
            # Log pass status for cli_result_callback parsing
            util.log_task_status(TASK_IMAGE_SIGNED_CHECK, TASK_STATUS_PASS)
    except RequestException:
        logger.exception("Visit release/mirror url failed")
        # Log fail status for cli_result_callback parsing
        util.log_task_status(TASK_IMAGE_SIGNED_CHECK, TASK_STATUS_FAIL)
        raise
