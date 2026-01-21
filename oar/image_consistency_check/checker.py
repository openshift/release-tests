import logging
import sys
import click
import requests

from oar.image_consistency_check.image import ImageMetadata
from oar.image_consistency_check.payload import Payload, PayloadImage
from oar.image_consistency_check.shipment import ShipmentComponent, Shipment


logger = logging.getLogger(__name__)


class ImageConsistencyChecker:

    def __init__(self, payload: Payload, shipment: Shipment, check_version: bool = True):
        """
        Initialize the ImageConsistencyChecker object.

        Args:
            payload (Payload): The payload object
            shipment (Shipment): The shipment object
            check_version (bool): Whether to check if the payload and shipment versions are the same

        Raises:
            ValueError: If the payload and shipment versions are not the same and check_version is True
        """
        if check_version and not self._is_shipment_payload_version_same(payload, shipment):
            logger.error(f"Payload version {payload.version} does not match shipment version {shipment.version}")
            raise ValueError(f"Payload version {payload.version} does not match shipment version {shipment.version}")

        self.payload_images = payload.get_images()
        self.shipment_components = shipment.get_components()
        self.all_image_metadata: dict[str, ImageMetadata] = self._create_image_metadata(self.payload_images, self.shipment_components)

    def _is_shipment_payload_version_same(self, payload: Payload, shipment: Shipment) -> bool:
        """
        Check if the payload and shipment versions are the same.

        Args:
            payload (Payload): The payload object
            shipment (Shipment): The shipment object

        Returns:
            bool: True if the payload and shipment versions are the same, False otherwise
        """
        return payload.version == shipment.version

    def _create_image_metadata(self, payload_images: list[PayloadImage], shipment_components: list[ShipmentComponent]) -> dict[str, ImageMetadata]:
        """
        Create the image metadata for the payload and shipment.

        Args:
            payload_images (list[PayloadImage]): The list of payload images
            shipment_components (list[ShipmentComponent]): The list of shipment components

        Returns:
            dict[str, ImageMetadata]: The dictionary pullspecs as keys and ImageMetadata as values
        """
        all_image_metadata: dict[str, ImageMetadata] = {}
        for image in payload_images:
            if image.pullspec not in all_image_metadata.keys():
                all_image_metadata[image.pullspec] = ImageMetadata(image.pullspec)
        for component in shipment_components:
            if component.pullspec not in all_image_metadata.keys():
                all_image_metadata[component.pullspec] = ImageMetadata(component.pullspec)
        return all_image_metadata   

    def _is_payload_image_in_shipment(self, payload_image: PayloadImage) -> bool:
        """
        Check if the payload image is in the shipment.

        Args:
            payload_image (PayloadImage): The payload image

        Returns:
            bool: True if the payload image is in the shipment, False otherwise
        """
        match_images = []
        for component in self.shipment_components:
            if self.all_image_metadata[payload_image.pullspec].has_same_identifier(self.all_image_metadata[component.pullspec]):
                match_images.append(component)
        if len(match_images) > 0:
            logger.info(f"Payload image {payload_image.name} with pullspec {payload_image.pullspec} is in the shipment. Number of matches: {len(match_images)}")
            for component in match_images:
                logger.info(f"Match component: {component.name} with pullspec: {component.pullspec}")
                self.all_image_metadata[component.pullspec].log_details()
            return True
        else:
            logger.info(f"Payload image {payload_image.name} with pullspec {payload_image.pullspec} is not in the shipment")
            return False

    def _is_payload_image_released(self, payload_image: PayloadImage) -> bool:
        """
        Check if the payload image is released in Red Hat catalog.

        Args:
            payload_image (PayloadImage): The payload image

        Returns:
            bool: True if only one image is found in Red Hat catalog, False otherwise
        """
        payload_image_digest = self.all_image_metadata[payload_image.pullspec].digest
        url = f"https://catalog.redhat.com/api/containers/v1/images?filter=image_id=={payload_image_digest}"
        logger.debug(f"Checking payload pullspec: {payload_image.name} with pullspec {payload_image.pullspec} in Red Hat catalog. URL: {url}")
        resp = requests.get(url)
        if resp.ok:
            resp_data = resp.json()
            if resp_data["total"] > 0:
                logger.info(f"Image {payload_image.name} with pullspec {payload_image.pullspec} found in Red Hat catalog.")
                for data in resp_data["data"]:
                    for repo in data["repositories"]:
                        logger.info(f"Repository: {repo["registry"]}/{repo["repository"]}")
                return True
            else:
                logger.error(f"No image found in Red Hat catalog.")
                return False
        else:
            logger.error(f"Access to catalog.redhat.com failed. Status code: {resp.status_code}, Reason: {resp.reason}")
            return False

    def _find_images_with_same_name(self, payload_image: PayloadImage) -> None:
        """
        Find images with the same name but different identifier.

        Args:
            payload_image (PayloadImage): The payload image
        """
        has_same_name = False

        logger.info(f"Checking payload image {payload_image.name} with pullspec {payload_image.pullspec} for images with the same name in the shipment")
        for component in self.shipment_components:
            if self.all_image_metadata[payload_image.pullspec].has_same_name(self.all_image_metadata[component.pullspec]):
                has_same_name = True
                logger.info(f"Found an image with the same name but different identifier. Please check manually. Image: {component.name} with pullspec: {component.pullspec}")
                self.all_image_metadata[component.pullspec].log_details()

        if not has_same_name:
            logger.error(f"No image with the same name found in the shipment. Please check manually.")

    def is_consistent(self) -> bool:
        """
        Check if the images in payload are consistent with images in shipment.

        Returns:
            bool: True if the images in payload are found in the shipment or Red Hat catalog, False otherwise
        """
        all_payload_images_ok = True
        for image in self.payload_images:
            logger.info(f"Checking payload image {image.name} with pullspec {image.pullspec}")
            self.all_image_metadata[image.pullspec].log_details()
            if self._is_payload_image_in_shipment(image):
                logger.info(f"Passed. Found in the Shipment")
            elif self._is_payload_image_released(image):
                logger.info(f"Passed. Found in Red Hat catalog")
            else:
                logger.error(f"Failed. Not found in the Shipment and Red Hat catalog")
                self._find_images_with_same_name(image)
                all_payload_images_ok = False
        logger.info(f"Checked {len(self.payload_images)} payload images")
        return all_payload_images_ok

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
