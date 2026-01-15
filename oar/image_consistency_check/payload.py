import logging
import re
import subprocess
import json

logger = logging.getLogger(__name__)


class Payload:
    """
    Represents an OpenShift release payload and provides methods to get the image pullspecs.

    Class Attributes:
        SKIPPED_TAGS_REGEX (list[str]): List of regex patterns to skip when extracting images.
    """

    SKIPPED_TAGS_REGEX = [
        r"machine-os-content",
        r"rhel-coreos(?:-\d+)?",
        r"rhel-coreos-extensions(?:-\d+)?",
    ]

    # precompile the regex patterns
    _SKIPPED_TAGS_PATTERNS = [re.compile(r) for r in SKIPPED_TAGS_REGEX]

    def __init__(self, payload_url: str):
        """
        Initialize the Payload object.

        Args:
            payload_url (str): The URL of the OpenShift release payload
        """
        self._url = payload_url

    def _is_skipped_tag(self, tag_name: str) -> bool:
        """
        Check if the tag name matches any of the skipped tags regex patterns.

        Args:
            tag_name (str): The name of the tag
        Returns:
            bool: True if the tag name matches any of the skipped tags regex patterns, False otherwise
        """
        return any(pattern.fullmatch(tag_name) for pattern in self._SKIPPED_TAGS_PATTERNS)

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
            if self._is_skipped_tag(tag_name):
                logger.debug(f"Skipping tag: {tag_name}")
                continue

            pullspec_name = tag['from']['name']
            logger.debug(f"Adding pullspec: {pullspec_name}")
            pullspecs.append(pullspec_name)

        return pullspecs
