import click
import logging
import re
import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from oar.core.const import *
from oar.core.worksheet_mgr import WorksheetManager


logger = logging.getLogger(__name__)

@click.command()
@click.pass_context
def image_signed_check(ctx):
    """
    Check payload image is well signed
    """
    cs = ctx.obj["cs"] 
    report = WorksheetManager(cs).get_test_report()
    image_signed_check_result = report.get_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY)
    if image_signed_check_result == TASK_STATUS_PASS:
        logger.info("image signed check already pass, not need to trigger again")
    else:
        report.update_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY, TASK_STATUS_INPROGRESS)
        try:
            res = requests.get(cs.get_release_url() + "/releasestream/4-stable/release/" + cs.release)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'lxml')
            # 1. get the digest
            digest_sha = soup.find(string=re.compile("sha256:"))
            if len(digest_sha) == 0:
                logger.error("No image digest found!")
            logger.info(f"found image digest: {digest_sha}")
            reformatted_digest = digest_sha.replace(':', '=')
            # 2. query the mirror location
            mirror_url = cs.get_signature_url() + reformatted_digest + "/"
            logger.info(f'Comparing digest from url: {mirror_url}')
            rest = requests.get(mirror_url)
            rest.raise_for_status()
            if rest.status_code == 200:
                logger.info("Signature check PASSED")
                report.update_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY, TASK_STATUS_PASS)
        except RequestException:
            logger.error("Visit release/mirror url failed")
            report.update_task_status(LABEL_TASK_PAYLOAD_IMAGE_VERIFY, TASK_STATUS_FAIL)  
