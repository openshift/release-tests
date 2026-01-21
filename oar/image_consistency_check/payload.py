import logging
import re
import subprocess
import json

logger = logging.getLogger(__name__)

class PayloadImage:
    """
    Represents an image in the payload with its name and pullspec.
    """

    def __init__(self, name: str, pullspec: str):
        """
        Initialize the PayloadImage object.
        """
        self.name = name
        self.pullspec = pullspec

class Payload:
    """
    Represents an OpenShift release payload and provides methods to get the images.

    Class Attributes:
        SKIPPED_IMAGES_REGEX (list[str]): List of regex patterns to skip when extracting images.
    """

    SKIPPED_IMAGES_REGEX = [
        r"machine-os-content",
        r"rhel-coreos(?:-\d+)?",
        r"rhel-coreos(?:-\d+)?-extensions",
    ]

    # precompile the regex patterns
    _SKIPPED_IMAGES_PATTERNS = [re.compile(r) for r in SKIPPED_IMAGES_REGEX]

    def __init__(self, payload_url: str):
        """
        Initialize the Payload object.

        Args:
            payload_url (str): The URL of the OpenShift release payload
        """
        self._url = payload_url
        self.version = self._get_payload_version()

    def _get_payload_version(self) -> str:
        """
        Get the payload version from the payload URL.

        Returns:
            str: The payload version
        """
        match = re.match(r"^quay\.io/openshift-release-dev/ocp-release:(\d+\.\d+\.\d+.*)-x86_64$", self._url)
        if match:
            return match.group(1)
        else:
            logger.error(f"Invalid payload URL: {self._url}")
            raise ValueError(f"Invalid payload URL: {self._url}")

    def _fetch_payload_data(self) -> dict:
        """
        Get the payload data from the payload URL.

        Returns:
            dict: The payload data
        """
        logger.info(f"Fetching payload data from {self._url}")
        cmd = ["oc", "adm", "release", "info", "--pullspecs", self._url, "-o", "json"]
        logger.debug(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def _is_skipped_image(self, image_name: str) -> bool:
        """
        Check if the image name matches any of the skipped images regex patterns.

        Args:
            image_name (str): The name of the image
        Returns:
            bool: True if the image name matches any of the skipped images regex patterns, False otherwise
        """
        return any(pattern.fullmatch(image_name) for pattern in self._SKIPPED_IMAGES_PATTERNS)

    def _extract_images(self, payload_data: dict) -> list[PayloadImage]:
        """
        Extract images from the payload data.

        Args:
            payload_data (dict): The payload data

        Returns:
            list[PayloadImage]: List of images
        """
        logger.info(f"Extracting images from payload data")
        images = []
        for tag in payload_data['references']['spec']['tags']:
            if self._is_skipped_image(tag['name']):
                logger.info(f"Skipping image - name: {tag['name']}, pullspec: {tag['from']['name']}")
                continue
            images.append(PayloadImage(tag['name'], tag['from']['name']))
            logger.info(f"Adding image - name: {tag['name']}, pullspec: {tag['from']['name']}")
        logger.info(f"Extracted {len(images)} images from payload data")
        return images


    def get_images(self) -> list[PayloadImage]:
        """
        Get the images from the payload.

        Returns:
            list[PayloadImage]: List of images
        """
        payload_data = self._fetch_payload_data()
        return self._extract_images(payload_data)

