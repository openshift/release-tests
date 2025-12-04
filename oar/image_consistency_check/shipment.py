import os
import logging
import yaml
from gitlab import Gitlab
from glom import glom

logger = logging.getLogger(__name__)


class Shipment:
    def __init__(self, mr_id: int, project_path: str = 'hybrid-platforms/art/ocp-shipment-data',
                 gitlab_url: str = 'https://gitlab.cee.redhat.com') -> None:
        """
        Initialize with merge request ID

        Args:
            mr_id: Merge request ID
            project_path: GitLab project path (default: 'hybrid-platforms/art/ocp-shipment-data')
            gitlab_url: GitLab instance URL (default: 'https://gitlab.cee.redhat.com')
        """
        self.project_path = project_path
        self.mr_id = mr_id
        self.gitlab_url = gitlab_url
        logger.info(f"Initializing Shipment for MR {mr_id} in project {project_path}")
        self.gl = Gitlab(gitlab_url, private_token=self._get_gitlab_token())
        self.shipment_data_list = []  # Initialize empty list for shipment data
        self._fetch_mr_data()

    def _get_gitlab_token(self) -> str:
        """
        Get GitLab token from GITLAB_TOKEN environment variable

        Returns:
            GitLab API token as string

        Raises:
            ValueError: If GITLAB_TOKEN environment variable is not set
        """
        token = os.getenv('GITLAB_TOKEN')
        if not token:
            raise ValueError("GITLAB_TOKEN environment variable not set")
        return token

    def _fetch_mr_data(self) -> None:
        """
        Fetch MR changes and shipment data from GitLab

        Populates self.shipment_data_list with parsed YAML content from all YAML files found in MR changes

        Raises:
            Exception: If any error occurs during GitLab API operations
        """
        try:
            self.shipment_data_list = []  # Initialize list to store all YAML data
            logger.info(
                f"Fetching MR {self.mr_id} data from project {self.project_path}")
            project = self.gl.projects.get(self.project_path)
            mr = project.mergerequests.get(self.mr_id)
            changes = mr.changes()
            change_list = changes.get('changes', [])
            logger.debug(f"Found {len(change_list)} changes in MR")

            # Process all YAML files in MR changes
            for change in change_list:
                if not change['new_path'].endswith('.yaml'):
                    logger.debug(
                        f"Skipping non-YAML file: {change['new_path']}")
                    continue

                logger.info(f"Processing YAML file: {change['new_path']}")
                # Get shipment file content
                file_content = project.files.get(
                    file_path=change['new_path'],
                    ref=mr.source_branch
                ).decode().decode('utf-8')
                shipment_data = yaml.safe_load(file_content)
                self.shipment_data_list.append(shipment_data)
                logger.debug(
                    f"Successfully loaded shipment data from {change['new_path']}")

        except Exception as e:
            logger.error(
                f"Error fetching MR {self.mr_id} data from {self.project_path}: {str(e)}", exc_info=True)

    def get_image_pullspecs(self) -> list[str]:
        """
        Get all component pullspecs from shipment data

        Returns:
            List of pullspec strings from shipment components
        """
        if not self.shipment_data_list:
            logger.warning("No shipment data available - cannot fetch pullspecs")
            return []

        all_pullspecs = []
        try:
            for shipment_data in self.shipment_data_list:
                logger.info("Retrieving pullspecs from shipment components")
                components = glom(shipment_data, 'shipment.snapshot.spec.components', default=[])
                if not components:
                    logger.warning("No components found in shipment data")
                    continue

                logger.info(f"Found {len(components)} components in shipment")
                for component in components:
                    container_image = component.get('containerImage')
                    name = component.get('name')
                    if container_image:
                        logger.info(f"Found pullspec for component {name}: {container_image}")
                        all_pullspecs.append(container_image)

            return all_pullspecs

        except Exception as e:
            logger.error(
                f"Error retrieving pullspecs from shipment: {str(e)}", exc_info=True)
            return []

    def get_mr_url(self) -> str:
        """
        Get the GitLab URL for the current merge request

        Returns:
            String containing the full GitLab URL for the merge request
        """
        mr_url = f"{self.gitlab_url}/{self.project_path}/-/merge_requests/{self.mr_id}"
        logger.debug(f"Generated MR URL: {mr_url}")
        return mr_url
