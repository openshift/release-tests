import logging
import subprocess
import json
import re

logger = logging.getLogger(__name__)


class Payload:
    def __init__(self, payload_url):
        logger.info(f"Payload: init {payload_url}")
        self.url = payload_url
        self.build_data = {}
        self.images = []
        self._get_payload_images_metadata()

    def _get_payload_images_metadata(self):
        cmd = f'oc adm release info --pullspecs {self.url} -o json 2>/dev/null'
        logger.debug(f"Payload: {cmd}")
        (status, output) = subprocess.getstatusoutput(cmd)
        if status == 0:
            self.build_data = json.loads(output)
            for item in self.build_data['references']['spec']['tags']:
                logger.debug(item)
                if item['name'] == "machine-os-content" or re.match('rhel-coreos', item['name']):
                    logger.warning("Payload: skipped machine-os-content, rhel-coreos and rhel-coreos-extensions")
                else:
                    self.images.append(item['from']['name'])
            return True
        else:
            logger.error(f"Payload: {output}")
            return False