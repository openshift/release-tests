import json
import logging
import subprocess

logger = logging.getLogger(__name__)


class ImageMetadata:
    """
    Represents an image and its metadata.
    """
    def __init__(self, pull_spec):
        """
        Initialize the ImageMetadata object.

        Args:
            pull_spec (str): The pull spec of the image
        """
        self.pull_spec = pull_spec
        self.metadata = self._get_image_metadata() or {}
        self.digest = self.metadata.get('digest', '')
        self.listdigest = self.metadata.get('listDigest', '')
        self.labels = self.metadata.get('config', {}).get('config', {}).get('Labels', {})
        self.build_commit_id = self.labels.get('io.openshift.build.commit.id', '')
        self.vcs_ref = self.labels.get('vcs-ref', '')
        self.name = self.labels.get('name', '')
        self.version = self.labels.get('version', '')
        self.release = self.labels.get('release', '')
        self.tag = f"{self.version}-{self.release}"

    def _get_image_metadata(self) -> dict:
        """
        Get the metadata of the image.

        Returns:
            dict: The metadata of the image
        """
        cmd = ["oc", "image", "info", "--filter-by-os", "linux/amd64", "-o", "json", "--insecure=true", self.pull_spec]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            logger.error(f"Command {cmd} returned with error. Return code: {result.returncode}")
            logger.error(f"Stderr: {result.stderr}")
            return None

    def has_same_identifier(self, other) -> bool:
        """
        Check if the image matches another image.

        Args:
            other (ImageMetadata): The other image to compare to

        Returns:
            bool: True if the images match, False otherwise
        """
        if self.listdigest != "" and self.listdigest == other.listdigest:
            return True
        if self.digest != "" and self.digest == other.digest:
            return True
        if self.vcs_ref != "" and self.vcs_ref == other.vcs_ref:
            return True
        return False

    def has_same_name(self, other) -> bool:
        """
        Check if the image has the same name as another image.

        Args:
            other (ImageMetadata): The other image to compare to

        Returns:
            bool: True if the images have the same name, False otherwise
        """
        return self.name != "" and self.name == other.name

    def log_pullspec_details(self) -> None:
        """
        Log the details of the image pullspec.
        """
        logger.debug(f"Digest: {self.digest}")
        logger.debug(f"Listdigest: {self.listdigest}")
        logger.debug(f"Build commit ID: {self.build_commit_id}")
        logger.debug(f"VCS ref: {self.vcs_ref}")
        logger.debug(f"Name: {self.name}")
        logger.debug(f"Tag: {self.tag}")
