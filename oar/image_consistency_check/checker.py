import logging
import sys
import click
import requests

from oar.image_consistency_check.image import ImageMetadata
from oar.image_consistency_check.payload import Payload
from oar.image_consistency_check.shipment import Shipment


logger = logging.getLogger(__name__)


class ImageConsistencyChecker:

    def __init__(self, payload: Payload, shipment: Shipment):
        """
        Initialize the ImageConsistencyChecker object.

        Args:
            payload (Payload): The payload object
            shipment (Shipment): The shipment object
        """
        self.payload_image_pullspecs = payload.get_image_pullspecs()
        self.shipment_image_pullspecs = shipment.get_image_pullspecs()
        self.all_image_metadata: dict[str, ImageMetadata] = self._create_image_metadata(self.payload_image_pullspecs, self.shipment_image_pullspecs)

    def _create_image_metadata(self, payload_image_pullspecs: list[str], shipment_image_pullspecs: list[str]) -> dict[str, ImageMetadata]:
        """
        Create the image metadata for the payload and shipment.

        Args:
            payload_image_pullspecs (list[str]): The list of payload image pullspecs
            shipment_image_pullspecs (list[str]): The list of shipment image pullspecs

        Returns:
            dict[str, ImageMetadata]: The dictionary of image metadata
        """
        all_image_metadata: dict[str, ImageMetadata] = {}
        for payload_pullspec in payload_image_pullspecs:
            if payload_pullspec not in all_image_metadata.keys():
                all_image_metadata[payload_pullspec] = ImageMetadata(payload_pullspec)
        for shipment_pullspec in shipment_image_pullspecs:
            if shipment_pullspec not in all_image_metadata.keys():
                all_image_metadata[shipment_pullspec] = ImageMetadata(shipment_pullspec)
        return all_image_metadata   

    def _is_payload_image_in_shipment(self, payload_pullspec: str) -> bool:
        """
        Check if the payload image is in the shipment.

        Args:
            payload_pullspec (str): The pullspec of the payload image

        Returns:
            bool: True if the payload image is in the shipment, False otherwise
        """
        match_pullspecs = []
        for shipment_pullspec in self.shipment_image_pullspecs:
            if self.all_image_metadata[payload_pullspec].has_same_identifier(self.all_image_metadata[shipment_pullspec]):
                match_pullspecs.append(shipment_pullspec)
        if len(match_pullspecs) > 0:
            logger.info(f"Payload pullspec {payload_pullspec} is in the shipment. Number of matches: {len(match_pullspecs)}")
            for mp in match_pullspecs:
                logger.info(f"Match pullspec: {mp}")
                self.all_image_metadata[mp].log_pullspec_details()
            return True
        else:
            logger.info(f"Payload pullspec {payload_pullspec} is not in the shipment")
            return False

    def _is_payload_image_released(self, payload_pullspec: str) -> bool:
        """
        Check if the payload image is released in Red Hat catalog.

        Args:
            payload_pullspec (str): The pullspec of the payload image

        Returns:
            bool: True if only one image is found in Red Hat catalog, False otherwise
        """
        payload_image_digest = self.all_image_metadata[payload_pullspec].digest
        url = f"https://catalog.redhat.com/api/containers/v1/images?filter=image_id=={payload_image_digest}"
        logger.debug(f"Checking payload pullspec: {payload_pullspec} in Red Hat catalog. URL: {url}")
        resp = requests.get(url)
        if resp.ok:
            resp_data = resp.json()
            if resp_data["total"] == 1:
                logger.info(f"Image {payload_pullspec} found in Red Hat catalog.")
                return True
            elif resp_data["total"] > 1:
                # FIXME: If multiple images are found, should we fail the check?
                logger.error(f"Multiple images found in Red Hat catalog. Please check manually.")
                return False
            else:
                logger.error(f"No image found in Red Hat catalog.")
                return False
        else:
            logger.error(f"Access to catalog.redhat.com failed. Status code: {resp.status_code}, Reason: {resp.reason}")
            return False

    def _find_images_with_same_name(self, payload_pullspec: str) -> None:
        """
        Find images with the same name but different identifier.

        Args:
            payload_pullspec (str): The pullspec of the payload image
        """
        has_same_name = False

        for shipment_pullspec in self.shipment_image_pullspecs:
            if self.all_image_metadata[payload_pullspec].has_same_name(self.all_image_metadata[shipment_pullspec]):
                has_same_name = True
                logger.info(f"Found an image with the same name but different identifier. Please check manually.")
                self.all_image_metadata[shipment_pullspec].log_pullspec_details()

        if not has_same_name:
            logger.error(f"No image with the same name found in the shipment. Please check manually.")

    def is_consistent(self) -> bool:
        """
        Check if the images in payload are consistent with images in shipment.

        Returns:
            bool: True if the images in payload are found in the shipment or Red Hat catalog, False otherwise
        """
        all_pullspecs_ok = True
        for payload_pullspec in self.payload_image_pullspecs:
            logger.info(f"Checking payload pullspec: {payload_pullspec}")
            self.all_image_metadata[payload_pullspec].log_pullspec_details()
            if self._is_payload_image_in_shipment(payload_pullspec):
                logger.info(f"Checking payload pullspec: {payload_pullspec} is passed. Found in the Shipment")
            elif self._is_payload_image_released(payload_pullspec):
                logger.info(f"Checking payload pullspec: {payload_pullspec} is passed. Found in Red Hat catalog")
            else:
                logger.error(f"Checking payload pullspec: {payload_pullspec} is failed. Not found in the Shipment and Red Hat catalog")
                self._find_images_with_same_name(payload_pullspec)
                all_pullspecs_ok = False
        return all_pullspecs_ok

@click.command()
@click.option("-p", "--payload-url", type=str, required=True, help="Payload URL")
@click.option("-m", "--mr-id", type=int, required=True, help="Merge request ID")
def image_consistency_check(payload_url: str, mr_id: int) -> None:
    """
    Check if images in payload are consistent with images in shipment.

    Args:
        payload_url (str): The URL of the payload
        mr_id (int): The ID of the merge request
    """
    payload = Payload(payload_url)
    shipment = Shipment(mr_id)
    checker = ImageConsistencyChecker(payload, shipment)
    if checker.is_consistent():
        logger.info("All payload images are consistent with images in shipment.")
        sys.exit(0)
    else:
        logger.error("Payload images are not consistent with images in shipment.")
        sys.exit(1)

if __name__ == "__main__":
    image_consistency_check()