import gitlab
import re
import yaml
import os
import logging
from oar.core.util import is_valid_email
from typing import List, Optional, Set
from urllib.parse import urlparse
from glom import glom
from oar.core.configstore import ConfigStore
from oar.core.exceptions import (
    GitLabMergeRequestException,
    GitLabServerException,
    ShipmentDataException
)

logger = logging.getLogger(__name__)

class GitLabMergeRequest:
    def __init__(self, gitlab_url: str, project_name: str, merge_request_id: int, private_token: str = None):
        """Initialize with GitLab connection details and merge request ID
        
        Args:
            gitlab_url: URL of GitLab instance (hostname only)
            project_name: Project name in 'namespace/project' format
            merge_request_id: ID of merge request to work with
            private_token: Optional token, falls back to GITLAB_TOKEN env var
        """
        self.gitlab_url = gitlab_url
        self.project_name = project_name
        self.merge_request_id = merge_request_id
        
        self.private_token = private_token or os.getenv('GITLAB_TOKEN')
        if not self.private_token:
            raise GitLabMergeRequestException("No GitLab token provided and GITLAB_TOKEN env var not set")
            
        self.gl = gitlab.Gitlab(gitlab_url, private_token=self.private_token)
        # First get the project, then get the merge request
        try:
            project = self.gl.projects.get(project_name)
            # Try to get merge request directly by ID first
            try:
                self.mr = project.mergerequests.get(merge_request_id)
            except gitlab.exceptions.GitlabGetError:
                # Fall back to listing and filtering if direct get fails
                mrs = project.mergerequests.list()
                self.mr = next((mr for mr in mrs if mr.iid == merge_request_id), None)
                if not self.mr:
                    raise GitLabMergeRequestException(f"Merge request {merge_request_id} not found")
        except gitlab.exceptions.GitlabGetError as e:
            raise GitLabMergeRequestException(f"Failed to get merge request: {str(e)}")

    def get_file_content(self, file_path: str) -> str:
        """Get raw file content from the merge request"""
        if not file_path or not isinstance(file_path, str):
            raise GitLabMergeRequestException("File path must be a non-empty string")
            
        try:
            file_content = self.gl.projects.get(self.project_name).files.get(
                file_path=file_path,
                ref=self.mr.source_branch
            )
            if isinstance(file_content, str):
                return file_content
            return file_content.decode().decode("utf-8")
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to access file '{file_path}': {str(e)}")

    def get_all_files(self, file_extension: str = 'yaml') -> List[str]:
        """Get all files changed in the merge request, optionally filtered by extension
        
        Args:
            file_extension: File extension to filter by (default: 'yaml')
            
        Returns:
            List of file paths changed in the merge request
        """
        try:
            project = self.gl.projects.get(self.project_name)
            changes =  self.mr.changes()
            all_files = [change['new_path'] for change in changes.get('changes', [])]
            
            if file_extension:
                return [f for f in all_files if f.lower().endswith(f'.{file_extension.lower()}')]
            return all_files
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to get changed files: {str(e)}")

    def add_comment(self, comment: str) -> None:
        """Add comment to the merge request"""
        try:
            self.mr.notes.create({'body': comment})
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to add comment: {e}")

    def get_status(self) -> str:
        """Get the current status of the merge request
        
        Returns:
            str: Current state of MR ('opened', 'merged', 'closed')
            
        Raises:
            GitLabMergeRequestException: If unable to get status
        """
        try:
            return self.mr.state
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to get MR status: {str(e)}")

class GitLabServer:
    """Class for performing GitLab server-level operations"""
    
    def __init__(self, gitlab_url: str, private_token: str = None):
        """Initialize with GitLab connection details
        
        Args:
            gitlab_url: URL of GitLab instance (hostname only)
            private_token: Optional token, falls back to GITLAB_TOKEN env var
        """
        self.gitlab_url = gitlab_url
        self.private_token = private_token or os.getenv('GITLAB_TOKEN')
        
        if not self.private_token:
            raise ValueError("No GitLab token provided and GITLAB_TOKEN env var not set")
            
        self.gl = gitlab.Gitlab(gitlab_url, private_token=self.private_token)
        
    def get_username_by_email(self, email: str) -> Optional[str]:
        """Query GitLab username by email address
        
        Args:
            email: email address to search for
            
        Returns:
            first matching GitLab username if found, None otherwise
            
        Raises:
            ValueError: if email is empty, not a string, or invalid format
            Exception: if there are errors accessing GitLab API
        """
        if not email or not isinstance(email, str):
            raise ValueError("Email must be a non-empty string")
            
        if not is_valid_email(email):
            raise ValueError("Email must be in valid format (e.g. user@example.com)")
            
        try:
            users = self.gl.users.list(search=email)
            if users:
                return users[0].username
            return None
        except Exception as e:
            logger.error(f"Failed to query GitLab users: {str(e)}")
            raise GitLabServerException(f"GitLab API error: {str(e)}")


class ShipmentData:
    """Class for handling shipment merge request operations"""
    
    def __init__(self, config_store: ConfigStore):
        """Initialize with ConfigStore instance"""
        self._cs = config_store
        self._mrs = self._initialize_mrs()
        
    def _initialize_mrs(self) -> List[GitLabMergeRequest]:
        """Initialize GitLabMergeRequest objects from shipment MRs
        
        Returns:
            List of GitLabMergeRequest objects that are in 'opened' state
        """
        mrs = []
        mr_urls = self._cs.get_shipment_mrs()
        
        for url in mr_urls:
            if not url:
                continue
                
            try:
                project, mr_id = self._parse_mr_url(url)
                gitlab_url = self._cs.get_gitlab_url()
                token = self._cs.get_gitlab_token()
                
                mr = GitLabMergeRequest(
                    gitlab_url=gitlab_url,
                    project_name=project,
                    merge_request_id=mr_id,
                    private_token=token
                )
                
                # Only include opened MRs
                if mr.get_status() == 'opened':
                    mrs.append(mr)
            except Exception as e:
                logger.warning(f"Failed to initialize MR from {url}: {str(e)}")
                continue
                
        return mrs
        
    def _parse_mr_url(self, url: str) -> tuple:
        """Parse MR URL to extract project and MR ID
        
        Args:
            url: MR URL in format https://gitlab.cee.redhat.com/namespace/project/-/merge_requests/123
            
        Returns:
            tuple: (project_path, mr_id)
            
        Raises:
            ShipmentDataException: If URL is invalid
        """
        parsed = urlparse(url)
        if not parsed.netloc or not parsed.path:
            raise ShipmentDataException("Invalid MR URL")
            
        # Extract project path (namespace/project)
        path_parts = parsed.path.split('/-/merge_requests/')
        if len(path_parts) != 2:
            raise ShipmentDataException("Invalid MR URL format")
            
        project_path = path_parts[0].strip('/')
        mr_id = int(path_parts[1].split('/')[0])
        
        return (project_path, mr_id)
        
    def get_mrs(self) -> List[GitLabMergeRequest]:
        """Get list of initialized merge requests"""
        return self._mrs
        
    def get_mr_by_id(self, mr_id: int) -> Optional[GitLabMergeRequest]:
        """Get merge request by ID if exists"""
        for mr in self._mrs:
            if mr.merge_request_id == mr_id:
                return mr
        return None

    def get_jira_issues(self) -> List[str]:
        """Get Jira issue IDs from shipment YAML files where source is issues.redhat.com
        
        Returns:
            List of unique Jira issue IDs (e.g. ["OCPBUGS-123", "OCPBUGS-456"])
        """
        issues: Set[str] = set()
        
        for mr in self._mrs:
            try:
                logger.info(f"Processing MR {mr.merge_request_id} for Jira issues")
                # Get all YAML files from merge request
                yaml_files = mr.get_all_files()
                
                for file_path in yaml_files:
                    try:
                        logger.debug(f"Processing file {file_path}")
                        content = mr.get_file_content(file_path)
                        data = yaml.safe_load(content)
                        
                        # Extract issues from YAML structure
                        fixed_issues = glom(data, 'shipment.data.releaseNotes.issues.fixed', default=[])
                        
                        # Add valid issues to our set
                        for issue in fixed_issues:
                            if isinstance(issue, dict) and issue.get('source') == 'issues.redhat.com':
                                issues.add(issue['id'])
                    except Exception as e:
                        logger.warning(f"Failed to process file {file_path}: {str(e)}")
                        continue
            except Exception as e:
                logger.error(f"Error processing MR {mr.merge_request_id}: {str(e)}")
                continue
                
        return sorted(issues)

    def get_nvrs(self) -> List[str]:
        """Get all NVRS from shipment YAML files by checking jsonpath shipment.snapshot.spec.nvrs
        
        Returns:
            List of unique NVRS (e.g. ["package-1.2.3-1", "package-4.5.6-2"])
        """
        nvrs: Set[str] = set()
        
        for mr in self._mrs:
            try:
                logger.info(f"Processing MR {mr.merge_request_id} for NVRS")
                # Get all YAML files from merge request
                yaml_files = mr.get_all_files()
                
                for file_path in yaml_files:
                    try:
                        logger.debug(f"Processing file: {file_path}")
                        content = mr.get_file_content(file_path)
                        data = yaml.safe_load(content)
                        
                        # Try to extract NVRS from YAML structure
                        nvrs_list = glom(data, 'shipment.snapshot.spec.nvrs', default=[])
                        
                        if isinstance(nvrs_list, list):
                            logger.debug(f"Found {len(nvrs_list)} NVRS in {file_path}")
                            nvrs.update(nvrs_list)
                    except Exception as e:
                        logger.warning(f"Failed to process file {file_path}: {str(e)}")
                        continue
            except Exception as e:
                logger.error(f"Error processing MR {mr.merge_request_id}: {str(e)}")
                continue
                
        return sorted(nvrs)

    def add_qe_release_lead_comment(self, email: str) -> None:
        """Add comment to all shipment merge requests identifying QE release lead
        
        Args:
            email: Email address of QE release lead to look up in GitLab
            
        Raises:
            ShipmentDataException: If email is invalid or username not found
        """
        if not email or not isinstance(email, str):
            raise ShipmentDataException("Email must be a non-empty string")
            
        try:
            gitlab_url = self._cs.get_gitlab_url()
            token = self._cs.get_gitlab_token()
            gl_server = GitLabServer(gitlab_url, token)
            
            username = gl_server.get_username_by_email(email)
            if not username:
                raise ShipmentDataException(f"No GitLab user found for email: {email}")
                
            comment = f"QE Release Lead is @{username}"
            
            for mr in self._mrs:
                try:
                    mr.add_comment(comment)
                    logger.info(f"Added QE release lead comment to MR {mr.merge_request_id}")
                except Exception as e:
                    logger.error(f"Failed to add comment to MR {mr.merge_request_id}: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error adding QE release lead comments: {str(e)}")
            raise ShipmentDataException(f"Failed to add QE release lead comments: {str(e)}")
