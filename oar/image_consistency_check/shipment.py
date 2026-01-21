import os
import logging
import re
import yaml
from gitlab import Gitlab
from glom import glom

logger = logging.getLogger(__name__)


class ShipmentComponent:
    """
    Represents a shipment component with its name and pullspec.
    """

    def __init__(self, name: str, pullspec: str):
        """
        Initialize the ShipmentComponent object.

        Args:
            name (str): The name of the shipment component
            pullspec (str): The pullspec of the shipment component
        """
        self.name = name
        self.pullspec = pullspec

class Shipment:
    """
    Handles loading and parsing shipment data from a GitLab Merge Request.
    """

    def __init__(self, mr_id: int, project_path: str = 'hybrid-platforms/art/ocp-shipment-data',
                 gitlab_url: str = 'https://gitlab.cee.redhat.com') -> None:
        """
        Initialize Shipment and authenticate with GitLab.

        Args:
            mr_id (int): GitLab merge request ID
            project_path (str): GitLab project path. Defaults to 'hybrid-platforms/art/ocp-shipment-data'
            gitlab_url (str): GitLab instance URL. Defaults to 'https://gitlab.cee.redhat.com'
        """
        self._mr_id = mr_id
        self._project_path = project_path
        self._gitlab_url = gitlab_url

        self._gl = Gitlab(self._gitlab_url, private_token=self._get_gitlab_token(), retry_transient_errors=True)
        self._gl.auth()
        self._project = self._gl.projects.get(self._project_path)
        self._mr = self._project.mergerequests.get(self._mr_id)
        self.version = self._get_version()

    def _get_version(self) -> str:
        """
        Get the version from the merge request title.

        Returns:
            str: The version extracted from the MR title

        Raises:
            ValueError: If the version is not found in the merge request title
        """
        match = re.search(r"Shipment for (\d+\.\d+\.\d+(?:-\S+)?)", self._mr.title, re.IGNORECASE)
        if match:
            return match.group(1)
        else:
            logger.error(f"Invalid shipment MR title: {self._mr.title}")
            raise ValueError(f"Invalid shipment MR title: {self._mr.title}")

    def _get_gitlab_token(self) -> str:
        """
        Get GitLab token from GITLAB_TOKEN environment variable.

        Returns:
            str: GitLab API token

        Raises:
            ValueError: If GITLAB_TOKEN environment variable is not set
        """
        token = os.getenv('GITLAB_TOKEN')
        if not token:
            raise ValueError("GITLAB_TOKEN environment variable is not set")
        return token

    def _get_shipment_data_list(self) -> list:
        """
        Get the list of shipment data from the merge request.
        
        Returns:
            list: List of shipment data
        """

        shipment_data_list = []

        logger.info(f"Fetching MR {self._mr_id} data from project {self._project_path}")
        changes = self._mr.changes()
        change_list = changes.get('changes', [])
        logger.debug(f"Found {len(change_list)} changes in MR")

        for change in change_list:
            if not change['new_path'].endswith('.yaml'):
                logger.debug(f"Skipping non-YAML file: {change['new_path']}")
                continue

            logger.info(f"Processing YAML file: {change['new_path']}")
            file_content = self._project.files.get(
                file_path=change['new_path'],
                ref=self._mr.source_branch
            ).decode().decode('utf-8')
            shipment_data = yaml.safe_load(file_content)
            shipment_data_list.append(shipment_data)
            logger.debug(f"Successfully loaded shipment data from {change['new_path']}")
        return shipment_data_list

    def get_components(self) -> list[ShipmentComponent]:
        """
        Get the list of shipment components from the shipment data.
        
        Returns:
            list[ShipmentComponent]: List of shipment components
        """
        shipment_data_list = self._get_shipment_data_list()

        if not shipment_data_list:
            logger.warning("No shipment data available - cannot retrieve components")
            return []

        all_components = []
        try:
            for shipment_data in shipment_data_list:
                logger.info("Retrieving components from shipment data")
                components = glom(shipment_data, 'shipment.snapshot.spec.components', default=[])
                if not components:
                    logger.warning("No shipment components found in shipment data")
                    continue

                logger.info(f"Found {len(components)} shipment components in shipment data")
                for component in components:
                    pullspec = component.get('containerImage')
                    name = component.get('name')
                    if pullspec:
                        logger.info(f"Found shipment component {name} with pullspec: {pullspec}")
                        all_components.append(ShipmentComponent(name, pullspec))
                    else:
                        logger.warning(f"No pullspec found for shipment component {name}")

            logger.info(f"Found {len(all_components)} shipment components in shipment data")
            return all_components

        except Exception as e:
            logger.error(f"Error retrieving components from shipment: {str(e)}", exc_info=True)
            return []
