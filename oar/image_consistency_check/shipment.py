import os
import logging
import yaml
from gitlab import Gitlab
from glom import glom

logger = logging.getLogger(__name__)


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
        project = self._gl.projects.get(self._project_path)
        mr = project.mergerequests.get(self._mr_id)
        changes = mr.changes()
        change_list = changes.get('changes', [])
        logger.debug(f"Found {len(change_list)} changes in MR")

        for change in change_list:
            if not change['new_path'].endswith('.yaml'):
                logger.debug(f"Skipping non-YAML file: {change['new_path']}")
                continue

            logger.info(f"Processing YAML file: {change['new_path']}")
            file_content = project.files.get(
                file_path=change['new_path'],
                ref=mr.source_branch
            ).decode().decode('utf-8')
            shipment_data = yaml.safe_load(file_content)
            shipment_data_list.append(shipment_data)
            logger.debug(f"Successfully loaded shipment data from {change['new_path']}")
        return shipment_data_list

    def get_image_pullspecs(self) -> list[str]:
        """
        Get the list of image pullspecs from the shipment data.
        
        Returns:
            list[str]: List of image pullspecs
        """
        shipment_data_list = self._get_shipment_data_list()

        if not shipment_data_list:
            logger.warning("No shipment data available - cannot fetch pullspecs")
            return []

        all_pullspecs = []
        try:
            for shipment_data in shipment_data_list:
                logger.info("Retrieving pullspecs from shipment components")
                components = glom(shipment_data, 'shipment.snapshot.spec.components', default=[])
                if not components:
                    logger.warning("No components found in shipment data")
                    continue

                logger.info(f"Found {len(components)} components in shipment")
                for component in components:
                    pullspec = component.get('containerImage')
                    name = component.get('name')
                    if pullspec:
                        logger.info(f"Found pullspec for component {name}: {pullspec}")
                        all_pullspecs.append(pullspec)

            return all_pullspecs

        except Exception as e:
            logger.error(f"Error retrieving pullspecs from shipment: {str(e)}", exc_info=True)
            return []

    def get_mr_url(self) -> str:
        """
        Get the GitLab URL for the current merge request.

        Returns:
            str: Full GitLab URL for the merge request

        Example:
            'https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/123'
        """
        return f"{self._gitlab_url}/{self._project_path}/-/merge_requests/{self._mr_id}"
