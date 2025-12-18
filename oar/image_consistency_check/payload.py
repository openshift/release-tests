import logging
import subprocess
import json

logger = logging.getLogger(__name__)


class Payload:
    """
    Represents an OpenShift release payload and provides methods to get the image pullspecs.

    Class Attributes:
        SKIPPED_TAGS (set[str]): Set of tag names to skip when extracting images.
    """

    SKIPPED_TAGS = {
        "machine-os-content",
        "rhel-coreos",
        "rhel-coreos-extensions",
    }

    def __init__(self, payload_url: str):
        """
        Initialize the Payload object.

        Args:
            payload_url (str): The URL of the OpenShift release payload
        """
        self._url = payload_url

    def get_image_pullspecs(self) -> list[str]:
        """
        Fetch image pullspecs from the payload URL, skipping unwanted tags.
        
        Returns:
            list[str]: List of container image pullspecs extracted from the payload
        """
        cmd = ["oc", "adm", "release", "info", "--pullspecs", self._url, "-o", "json"]
        logger.debug(f"Running command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        build_data = json.loads(result.stdout)

        pullspecs = []
        tags = build_data['references']['spec']['tags']
        logger.debug(f"Found {len(tags)} tags in payload")

        for tag in tags:
            tag_name = tag['name']
            if tag_name in self.SKIPPED_TAGS:
                logger.debug(f"Skipping tag: {tag_name}")
                continue

            pullspec_name = tag['from']['name']
            logger.debug(f"Adding pullspec: {pullspec_name}")
            pullspecs.append(pullspec_name)

        return pullspecs
