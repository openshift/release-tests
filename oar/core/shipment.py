import gitlab
import re
import yaml
import os
import logging
from typing import List, Optional, Set
from urllib.parse import urlparse
from glom import glom
from oar.core.configstore import ConfigStore

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
            raise ValueError("No GitLab token provided and GITLAB_TOKEN env var not set")
            
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
                    raise Exception(f"Merge request {merge_request_id} not found")
        except gitlab.exceptions.GitlabGetError as e:
            raise Exception(f"Failed to get merge request: {str(e)}")

    def get_file_content(self, file_path: str) -> str:
        """Get raw file content from the merge request"""
        if not file_path or not isinstance(file_path, str):
            raise ValueError("File path must be a non-empty string")
            
        try:
            file_content = self.gl.projects.get(self.project_name).files.get(
                file_path=file_path,
                ref=self.mr.source_branch
            )
            if isinstance(file_content, str):
                return file_content
            return file_content.decode().decode("utf-8")
        except Exception as e:
            raise Exception(f"Failed to access file '{file_path}': {str(e)}")

    def get_all_files(self, file_extension: str = None) -> List[str]:
        """Get all files changed in the merge request, optionally filtered by extension
        
        Args:
            file_extension: Optional file extension to filter by (e.g. 'yaml')
            
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
            raise Exception(f"Failed to get changed files: {str(e)}")

    def add_comment(self, comment: str) -> None:
        """Add comment to the merge request"""
        try:
            self.mr.notes.create({'body': comment})
        except Exception as e:
            raise Exception(f"Failed to add comment: {e}")


class ShipmentData:
    """Class for handling shipment merge request operations"""
    
    def __init__(self, config_store: ConfigStore):
        """Initialize with ConfigStore instance"""
        self._cs = config_store
        self._mrs = self._initialize_mrs()
        
    def _initialize_mrs(self) -> List[GitLabMergeRequest]:
        """Initialize GitLabMergeRequest objects from shipment MRs"""
        mrs = []
        mr_urls = self._cs.get_shipment_mrs()
        
        for url in mr_urls:
            if not url:
                continue
                
            try:
                project, mr_id = self._parse_mr_url(url)
                gitlab_url = self._cs.get_gitlab_url()
                token = self._cs.get_gitlab_token()
                
                mrs.append(GitLabMergeRequest(
                    gitlab_url=gitlab_url,
                    project_name=project,
                    merge_request_id=mr_id,
                    private_token=token
                ))
            except Exception as e:
                continue
                
        return mrs
        
    def _parse_mr_url(self, url: str) -> tuple:
        """Parse MR URL to extract project and MR ID
        
        Args:
            url: MR URL in format https://gitlab.cee.redhat.com/namespace/project/-/merge_requests/123
            
        Returns:
            tuple: (project_path, mr_id)
            
        Raises:
            ValueError: If URL is invalid
        """
        parsed = urlparse(url)
        if not parsed.netloc or not parsed.path:
            raise ValueError("Invalid MR URL")
            
        # Extract project path (namespace/project)
        path_parts = parsed.path.split('/-/merge_requests/')
        if len(path_parts) != 2:
            raise ValueError("Invalid MR URL format")
            
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
                # Get all YAML files from merge request using get_all_files()
                yaml_files = mr.get_all_files('yaml')
                
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
        """Get all NVRS from image shipment YAML files
        
        Returns:
            List of unique NVRS (e.g. ["package-1.2.3-1", "package-4.5.6-2"])
        """
        nvrs: Set[str] = set()
        pattern = re.compile(r'^\d+\.\d+\.\d+-image\.\d+\.yaml$')
        
        for mr in self._mrs:
            try:
                logger.info(f"Processing MR {mr.merge_request_id} for NVRS")
                # Get all YAML files from merge request
                yaml_files = mr.get_all_files('yaml')
                
                for file_path in yaml_files:
                    try:
                        if not pattern.match(os.path.basename(file_path)):
                            logger.debug(f"Skipping non-image file: {file_path}")
                            continue
                            
                        logger.debug(f"Processing image file: {file_path}")
                        content = mr.get_file_content(file_path)
                        data = yaml.safe_load(content)
                        
                        # Extract NVRS from YAML structure
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
