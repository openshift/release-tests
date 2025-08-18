import yaml
import os
import logging
import requests
from datetime import datetime, timezone
from gitlab import Gitlab
from gitlab.exceptions import (
    GitlabError,
    GitlabGetError,
    GitlabAuthenticationError,
    GitlabCreateError,
    GitlabListError
)
from oar.core.util import is_valid_email, parse_mr_url
from typing import List, Optional, Set
from glom import glom
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
from oar.core.exceptions import (
    GitLabMergeRequestException,
    GitLabServerException,
    ShipmentDataException
)
from dataclasses import dataclass
from typing import List, Dict

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
        self._file_content_cache = {}  # Used to cache file contents during runtime to avoid GitLab API rate limits
        if not self.private_token:
            raise GitLabMergeRequestException("No GitLab token provided and GITLAB_TOKEN env var not set")
            
        self.gl = Gitlab(gitlab_url, private_token=self.private_token, retry_transient_errors=True)
        self.gl.auth()
        # First get the project, then get the merge request
        try:
            project = self.gl.projects.get(project_name, max_retries=5)
            # Try to get merge request directly by ID first
            try:
                self.mr = project.mergerequests.get(merge_request_id)
            except GitlabGetError:
                # Fall back to listing and filtering if direct get fails
                mrs = project.mergerequests.list()
                self.mr = next((mr for mr in mrs if mr.iid == merge_request_id), None)
                if not self.mr:
                    raise GitLabMergeRequestException(f"Merge request {merge_request_id} not found")
        except GitlabGetError as e:
            raise GitLabMergeRequestException(f"Failed to get merge request: {str(e)}")

    def get_file_content(self, file_path: str, use_cache: bool = True) -> str:
        """Get raw file content from the merge request
        
        Args:
            file_path: Path to file in repository
            use_cache: Whether to use cached content if available (default: True)
            
        Returns:
            File content as string
            
        Raises:
            GitLabMergeRequestException: If file access fails
        """
        if not file_path or not isinstance(file_path, str):
            raise GitLabMergeRequestException("File path must be a non-empty string")
            
        if use_cache and file_path in self._file_content_cache:
            return self._file_content_cache[file_path]
            
        try:
            file_content = self.gl.projects.get(self.project_name).files.get(
                file_path=file_path,
                ref=self.mr.source_branch
            )
            content = file_content.decode().decode("utf-8") if not isinstance(file_content, str) else file_content
            self._file_content_cache[file_path] = content
            return content
        except (GitlabGetError, GitlabAuthenticationError) as e:
            raise GitLabMergeRequestException(f"Failed to access file '{file_path}': GitLab API error") from e
        except UnicodeDecodeError as e:
            raise GitLabMergeRequestException(f"Failed to decode file '{file_path}' content") from e

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
        except GitlabError as e:
            raise GitLabMergeRequestException(f"Failed to get changed files: GitLab API error") from e

    def get_jira_issues_from_file(self, file_path: str) -> Set[str]:
        """Get all Jira issue IDs from a specific file in the merge request
        
        Args:
            file_path: Path to file in repository
            
        Returns:
            Set of Jira issue IDs found in the file (e.g. {"OCPBUGS-123"})
        """
        issues = set()
        try:
            logger.debug(f"Processing file {file_path}")
            
            # Get issues from file content
            content = self.get_file_content(file_path)
            data = yaml.safe_load(content)
            
            # Extract issues from YAML structure
            fixed_issues = glom(data, 'shipment.data.releaseNotes.issues.fixed', default=[])
            
            # Add valid issues to our set
            for issue in fixed_issues:
                if isinstance(issue, dict) and issue.get('source') == 'issues.redhat.com':
                    issues.add(issue['id'])
                    
        except (yaml.YAMLError, KeyError, glom.PathAccessError) as e:
            logger.warning(f"Failed to process file {file_path}: Invalid YAML structure")
        except Exception as e:
            logger.warning(f"Failed to process file {file_path}: Unexpected error", exc_info=False)
            
        return issues

    def get_jira_issues(self) -> List[str]:
        """Get all Jira issue IDs from files in this merge request
        
        Returns:
            List of unique Jira issue IDs (e.g. ["OCPBUGS-123", "OCPBUGS-456"])
        """
        issues: Set[str] = set()
        try:
            logger.info(f"Processing MR {self.merge_request_id} for Jira issues")
            for file_path in self.get_all_files():
                issues.update(self.get_jira_issues_from_file(file_path))
        except GitlabError as e:
            logger.error(f"Error processing MR {self.merge_request_id}: GitLab API error")
            raise GitLabMergeRequestException("Failed to get Jira issues due to GitLab error") from e
        except Exception as e:
            logger.error(f"Error processing MR {self.merge_request_id}: Unexpected error", exc_info=False)
            raise GitLabMergeRequestException("Failed to get Jira issues") from e
            
        return sorted(issues)

    def add_comment(self, comment: str) -> None:
        """Add comment to the merge request"""
        try:
            self.mr.notes.create({'body': comment})
        except GitlabCreateError as e:
            raise GitLabMergeRequestException("Failed to add comment to merge request") from e

    def add_suggestion(self, file_path: str, old_line: int, new_line: int, suggestion: str, relative_lines: str = "-0+0") -> None:
        """Add a suggestion comment to a specific line in the merge request diff
        
        Args:
            file_path: Path to file in repository
            old_line: Line number in old version (use None for new files)
            new_line: Line number in new version
            suggestion: Suggested change text
            relative_lines: Relative line numbers in format "-0+0" (default: "-0+0")
            
        Raises:
            GitLabMergeRequestException: If suggestion creation fails
        """
        try:
            position = {
                'base_sha': self.mr.diff_refs['base_sha'],
                'start_sha': self.mr.diff_refs['start_sha'],
                'head_sha': self.mr.diff_refs['head_sha'],
                'position_type': 'text',
                'old_path': file_path,
                'new_path': file_path,
                'old_line': old_line,
                'new_line': new_line
            }
            
            comment = f"```suggestion:{relative_lines}\n```" if not suggestion else f"{suggestion}\n```suggestion:{relative_lines}\n```"
            self.mr.discussions.create({
                'body': comment,
                'position': position
            })
        except GitlabCreateError as e:
            raise GitLabMergeRequestException("Failed to add suggestion comment") from e

    def get_jira_issue_line_number(self, jira_key: str, file_path: str) -> Optional[int]:
        """Get the line number where a Jira issue key appears in a file
        
        Searches for exact string match of the Jira key (case sensitive) and returns
        the first line number where it appears.
        
        Args:
            jira_key: Complete Jira issue key (e.g. "OCPBUGS-123")
            file_path: Path to file in repository
            
        Returns:
            int: First line number where jira_key appears, or None if not found
            
        Raises:
            GitLabMergeRequestException: If unable to read file or invalid inputs
            UnicodeDecodeError: If file content cannot be decoded
        """
        if not jira_key or not isinstance(jira_key, str):
            raise GitLabMergeRequestException("Jira key must be a non-empty string")
        if not file_path or not isinstance(file_path, str):
            raise GitLabMergeRequestException("File path must be a non-empty string")
            
        try:
            content = self.get_file_content(file_path)
            lines = content.splitlines()
            
            # Search for jira_key in each line (case sensitive)
            for i, line in enumerate(lines, 1):
                if jira_key in line:
                    return i
                    
            return None
        except (GitlabError, UnicodeDecodeError) as e:
            raise GitLabMergeRequestException(
                f"Failed to get line number for Jira issue {jira_key} in {file_path}"
            ) from e

    def get_id(self) -> int:
        """Get the merge request ID

        Returns:
            The numeric ID of this merge request
        """
        return self.merge_request_id

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

    def _get_latest_pipeline(self):
        """Get the latest pipeline for this merge request with full metadata
        
        Returns:
            gitlab.v4.objects.ProjectPipeline: The most recent pipeline object with complete metadata,
            including jobs, bridges, and status details
            
        Raises:
            GitLabMergeRequestException: If no pipelines found or error occurs
            GitlabError: For GitLab API communication failures
        """
        try:
            project = self.gl.projects.get(self.project_name)
            pipeline_list = self.mr.pipelines.list()
            if not pipeline_list:
                raise GitLabMergeRequestException("No pipelines found for merge request")
            
            # Get full pipeline objects with all metadata
            pipelines = [
                project.pipelines.get(p.id) 
                for p in pipeline_list
            ]
            # Sort by creation date (newest first)
            pipelines = sorted(
                pipelines,
                key=lambda p: p.created_at,
                reverse=True
            )
            pipeline = pipelines[0]
            logger.info(f"Found pipeline {pipeline.id} with status {pipeline.status}")
            return pipeline
        except GitlabError as e:
            raise GitLabMergeRequestException(f"Failed to get pipeline: GitLab API error") from e
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to get pipeline: {str(e)}") from e

    def _get_stage_info_from_pipeline(self, stage_name: str, pipeline) -> dict:
        """Get status of a pipeline stage including regular jobs and trigger jobs/bridges
        
        Args:
            stage_name: Name of stage to check
            pipeline: gitlab.v4.objects.ProjectPipeline object to inspect
            
        Returns:
            dict: {
                'status': str - overall stage status ('running', 'success', 'failed', etc.),
                'job': gitlab.v4.objects.ProjectPipelineJob - first job object in the stage
            }
            
        Raises:
            GitLabMergeRequestException: If stage not found in pipeline
            GitlabError: For GitLab API communication failures
        """
        try:
            # Get all jobs and bridges (trigger jobs) with detailed logging
            jobs = pipeline.jobs.list(get_all=True)
            bridges = pipeline.bridges.list(get_all=True)
            logger.debug(f"Found {len(jobs)} jobs and {len(bridges)} bridges in pipeline {pipeline.id}")
            
            # Combine jobs and bridges for stage checking
            all_work = list(jobs) + list(bridges)
            
            # Log all unique stages found
            all_stages = {w.stage for w in all_work if hasattr(w, 'stage')}
            logger.debug(f"Available stages in pipeline: {all_stages}")
            
            stage_work = [w for w in all_work if hasattr(w, 'stage') and w.stage == stage_name]
            
            if not stage_work:
                # Log all work for debugging
                logger.debug(f"All pipeline work: {[(w.name, getattr(w, 'stage', None), w.status) for w in all_work]}")
                raise GitLabMergeRequestException(
                    f"Stage '{stage_name}' not found in pipeline. Available stages: {all_stages}")
                
            # Return status from first job in stage (GitLab handles failed status automatically)
            job = stage_work[0]
            status = job.status
            logger.debug(f"Stage '{stage_name}' status: {status}")
            
            return {
                'status': status,
                'job': job
            }
        except Exception as e:
            logger.error(f"Error getting stage status: {str(e)}")
            raise

    def is_stage_release_success(self) -> bool:
        """Check if the stage-release-triggers stage has succeeded
        
        Returns:
            bool: True if stage status is 'success', False otherwise
            
        Raises:
            GitLabMergeRequestException: If unable to get stage status
        """
        try:
            stage_info = self.get_stage_release_info()
            if stage_info['status'] == 'success':
                return True
                
            logger.error(f"Stage release failed with status {stage_info['status']}")
            logger.error(f"Job details: {stage_info['job'].pformat()}")
            return False
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to check stage release status: {str(e)}") from e

    def is_prod_release_success(self) -> bool:
        """Check if the prod-release-triggers stage has succeeded
        
        Returns:
            bool: True if stage status is 'success', False otherwise
            
        Raises:
            GitLabMergeRequestException: If unable to get stage status
        """
        try:
            stage_info = self.get_prod_release_info()
            if stage_info['status'] == 'success':
                return True
                
            logger.error(f"Prod release failed with status {stage_info['status']}")
            logger.error(f"Job details: {stage_info['job'].pformat()}")
            return False
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to check prod release status: {str(e)}") from e

    def get_release_info(self, stage_name: str) -> dict:
        """Get detailed info about a release stage from latest pipeline
        
        Args:
            stage_name: Name of the stage to check
        
        Returns:
            dict: {
                'status': overall stage status (e.g. 'running', 'success', 'failed'),
                'job': gitlab.v4.objects.ProjectPipelineJob - first job object in the stage
            }
            
        Raises:
            GitLabMergeRequestException: If stage not found or pipeline error
        """
        try:
            pipeline = self._get_latest_pipeline()
            
            try:
                stage_status = self._get_stage_info_from_pipeline(stage_name, pipeline)
                logger.info(f"Stage '{stage_name}' status: {stage_status}")
                return stage_status
            except GitLabMergeRequestException as e:
                logger.error(f"Stage '{stage_name}' not found in pipeline {pipeline.id}")
                return {
                    'status': 'not_found',
                    'job': []
                }
            
        except GitlabError as e:
            logger.error(f"Failed to get status for '{stage_name}': GitLab API error")
            raise GitLabMergeRequestException(f"Failed to get status: GitLab API error") from e
        except Exception as e:
            logger.error(f"Failed to get status for '{stage_name}': Unexpected error", exc_info=False)
            raise GitLabMergeRequestException(f"Failed to get status: {str(e)}") from e

    def get_stage_release_info(self) -> dict:
        """Get detailed info about the 'stage-release-triggers' stage from latest pipeline
        
        Returns:
            dict: See get_release_info()
        """
        return self.get_release_info("stage-release-triggers")

    def get_prod_release_info(self) -> dict:
        """Get detailed info about the 'prod-release-triggers' stage from latest pipeline
        
        Returns:
            dict: See get_release_info()
        """
        return self.get_release_info("prod-release-triggers")

    def is_opened(self) -> bool:
        """Check if the merge request is in 'opened' state

        Returns:
            bool: True if MR is opened, False otherwise

        Raises:
            GitLabMergeRequestException: If unable to get MR status
        """
        return self.get_status() == 'opened'

    def approve(self) -> None:
        """Approve the current merge request (adds your approval)
        
        Note: 
        - This does not merge the MR, just adds your approval
        - The MR will still need all required approvals before it can be merged
        - Will not approve if current user has already approved
        
        Raises:
            GitLabMergeRequestException: If unable to approve the MR
        """
        try:
            if not self.is_opened():
                raise GitLabMergeRequestException(f"Cannot approve MR in state: {self.get_status()}")
            
            # Get current user
            current_user = self.gl.user
            if not current_user:
                raise GitLabMergeRequestException("Could not identify current user")
                
            # Check if already approved
            approved_by = [a['user']['username'] for a in self.mr.approvals.get().approved_by]
            if current_user.username in approved_by:
                logger.info(f"User {current_user.username} has already approved MR {self.merge_request_id}")
                return
                
            self.mr.approve()
            logger.info(f"Successfully approved MR {self.merge_request_id}")
        except GitlabError as e:
            logger.error(f"Failed to approve MR {self.merge_request_id}: GitLab API error")
            raise GitLabMergeRequestException("Failed to approve merge request due to GitLab error") from e
        except Exception as e:
            logger.error(f"Failed to approve MR {self.merge_request_id}: Unexpected error", exc_info=False)
            raise GitLabMergeRequestException("Failed to approve merge request") from e

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
            
        self.gl = Gitlab(gitlab_url, private_token=self.private_token)
        
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
        except GitlabListError as e:
            logger.error("Failed to query GitLab users: API error")
            raise GitLabServerException("GitLab API error") from e
        except Exception as e:
            logger.error("Failed to query GitLab users: Unexpected error", exc_info=False)
            raise GitLabServerException(f"GitLab API error: Failed to query users - {str(e)}") from e


@dataclass
class ImageHealthData:
    """Container for image health check results"""
    total_scanned: int
    unhealthy_components: List[Dict]
    unhealthy_count: int = 0
    unknown_count: int = 0

    def __post_init__(self):
        """Calculate counts if not provided"""
        if not self.unhealthy_count:
            self.unhealthy_count = len(self.unhealthy_components)
        if not self.unknown_count:
            self.unknown_count = len([
                c for c in self.unhealthy_components 
                if c.get("grade") == "Unknown"
            ])

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
                project, mr_id = parse_mr_url(url)
                gitlab_url = self._cs.get_gitlab_url()
                token = self._cs.get_gitlab_token()
                
                mr = GitLabMergeRequest(
                    gitlab_url=gitlab_url,
                    project_name=project,
                    merge_request_id=mr_id,
                    private_token=token
                )
                
                # Only include opened MRs
                if mr.is_opened():
                    mrs.append(mr)
            except Exception as e:
                logger.warning(f"Failed to initialize MR from {url}: {str(e)}")
                continue
                
        return mrs

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
                issues.update(mr.get_jira_issues())
            except Exception as e:
                logger.error(f"Error getting issues from MR {mr.merge_request_id}: {str(e)}")
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

    def add_qe_approval(self) -> None:
        """Add QE approval to all shipment merge requests
        
        Raises:
            ShipmentDataException: If any MR approval fails
        """
        for mr in self._mrs:
            try:
                mr.approve()
                logger.info(f"Successfully added QE approval to MR {mr.merge_request_id}")
            except Exception as e:
                logger.error(f"Failed to approve MR {mr.merge_request_id}: {str(e)}")
                raise ShipmentDataException(f"Failed to approve merge request: {str(e)}")

    def is_stage_release_success(self) -> bool:
        """Check if stage-release-triggers stage has succeeded for all shipment MRs
        
        Returns:
            bool: True if all MRs have successful stage releases, False otherwise
            
        Raises:
            ShipmentDataException: If unable to check stage status for any MR
        """
        all_success = True
        failed_mrs = []
        
        for mr in self._mrs:
            try:
                if not mr.is_stage_release_success():
                    failed_mrs.append(mr.merge_request_id)
                    all_success = False
            except Exception as e:
                logger.error(f"Failed to check stage release status for MR {mr.merge_request_id}: {str(e)}")
                raise ShipmentDataException(f"Failed to check stage release status: {str(e)}") from e
                
        if not all_success:
            logger.error(f"Stage release failed for MRs: {', '.join(str(mr_id) for mr_id in failed_mrs)}")
            
        return all_success

    def is_prod_release_success(self) -> bool:
        """Check if prod-release-triggers stage has succeeded for all shipment MRs
        
        Returns:
            bool: True if all MRs have successful prod releases, False otherwise
            
        Raises:
            ShipmentDataException: If unable to check stage status for any MR
        """
        all_success = True
        failed_mrs = []
        
        for mr in self._mrs:
            try:
                if not mr.is_prod_release_success():
                    failed_mrs.append(mr.merge_request_id)
                    all_success = False
            except Exception as e:
                logger.error(f"Failed to check prod release status for MR {mr.merge_request_id}: {str(e)}")
                raise ShipmentDataException(f"Failed to check prod release status: {str(e)}") from e
                
        if not all_success:
            logger.error(f"Prod release failed for MRs: {', '.join(str(mr_id) for mr_id in failed_mrs)}")
            
        return all_success

    def drop_bugs(self) -> tuple[list[str], list[str]]:
        """Drop bugs from shipment files by adding suggestions to merge requests
        
        Processes all shipment merge requests to:
        1. Identify high severity and droppable Jira issues
        2. Add suggestions to remove droppable issues from YAML files
        3. Cache processed issues to avoid duplicate suggestions
        
        Note:
        - Uses JiraManager to classify issue severity
        - Caches existing suggestions to avoid duplicates
        - Tracks processed issues across all MRs/files
        
        Returns:
            tuple[list[str], list[str]]: 
                [0] list of high severity Jira keys found,
                [1] list of Jira keys that can be dropped
                
        Raises:
            ShipmentDataException: If any operation fails
            GitlabError: For GitLab API communication failures
        """
        jira_manager = JiraManager(self._cs)
        all_high_severity_bugs = []
        all_can_drop_issues = []
        processed_issues = set()  # Track issues we've already processed
        existing_suggestions_cache = {}  # Cache of existing suggestions per MR
        
        for mr in self._mrs:
            try:
                # Get all files changed in MR
                files = mr.get_all_files()
                
                # Process each file
                for file_path in files:
                    try:
                        # Get Jira issues from this file
                        jira_issues = mr.get_jira_issues_from_file(file_path)
                        
                        # Get high severity and droppable bugs for these issues
                        high_severity_bugs, can_drop_issues = jira_manager.get_high_severity_and_can_drop_issues(jira_issues)
                        all_high_severity_bugs.extend(high_severity_bugs)
                        all_can_drop_issues.extend(can_drop_issues)
                        
                        # For each droppable bug in this file
                        for issue_key in can_drop_issues:
                            try:
                                # Skip if we've already processed this issue
                                if issue_key in processed_issues:
                                    logger.debug(f"Skipping already processed issue {issue_key}")
                                    continue
                                    
                                # Get line number where issue appears
                                line_num = mr.get_jira_issue_line_number(issue_key, file_path)
                                if line_num:
                                    # Initialize discussions cache for this MR if not already done
                                    if mr.merge_request_id not in existing_suggestions_cache:
                                        try:
                                            existing_suggestions_cache[mr.merge_request_id] = mr.mr.discussions.list()
                                        except GitlabError:
                                            existing_suggestions_cache[mr.merge_request_id] = []
                                    
                                    # Check if suggestion already exists for this issue or line
                                    has_suggestion = any(
                                        f"Drop bug {issue_key}" in note['body'] or
                                        (note.get('position', {}).get('new_path') == file_path and
                                         note.get('position', {}).get('new_line') == line_num)
                                        for discussion in existing_suggestions_cache[mr.merge_request_id]
                                        for note in discussion.attributes['notes']
                                    )
                                    
                                    # Only add suggestion if none exists for this issue or line
                                    # When dropping a bug from YAML, need to remove both lines:
                                    #   - id: OCPBUGS-12345
                                    #     source: issues.redhat.com
                                    if not has_suggestion:
                                        mr.add_suggestion(
                                            file_path=file_path,
                                            old_line=None,
                                            new_line=line_num,
                                            suggestion=f"Drop bug {issue_key}",
                                            relative_lines="-0+1"
                                        )
                                        logger.info(f"Added suggestion to drop {issue_key} in {file_path}")
                                    else:
                                        logger.debug(f"Skipping {issue_key} - suggestion already exists")
                                    
                                    # Mark issue as processed
                                    processed_issues.add(issue_key)
                            except Exception as e:
                                logger.warning(f"Failed to process {issue_key} in {file_path}: {str(e)}")
                                continue
                                
                    except Exception as e:
                        logger.warning(f"Failed to process file {file_path}: {str(e)}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error processing MR {mr.merge_request_id}: {str(e)}")
                raise ShipmentDataException(f"Failed to drop bugs: {str(e)}")
        
        return all_high_severity_bugs, all_can_drop_issues

    def _get_images_from_shipment(self, mr: GitLabMergeRequest) -> list:
        """Get all images from advisories in shipment YAML files
        
        Args:
            mr: GitLabMergeRequest instance to get files from
            
        Returns:
            List of all images from advisories (spec.content.images)
            
        Raises:
            ShipmentDataException: If unable to process shipment files
        """
        images = []
        try:
            yaml_files = mr.get_all_files()
            for file_path in yaml_files:
                # Skip files containing ".fbc." in their path
                if ".fbc." in file_path.lower():
                    continue
                    
                try:
                    content = mr.get_file_content(file_path)
                    data = yaml.safe_load(content)
                    
                    # Get advisory URL and images
                    advisory_url = glom(data, 'shipment.environments.stage.advisory.internal_url', default=None)
                    if advisory_url:
                        try:
                            # Fetch advisory content and extract images
                            advisory_content = yaml.safe_load(requests.get(advisory_url).text)
                            images.extend(glom(advisory_content, 'spec.content.images', default=[]))
                        except Exception as e:
                            logger.warning(f"Failed to process advisory {advisory_url}: {str(e)}")
                            continue
                            
                except Exception as e:
                    logger.warning(f"Failed to process file {file_path}: {str(e)}")
                    continue
        except Exception as e:
            raise ShipmentDataException(f"Failed to get images from shipment: {str(e)}")
        return images

    def _get_image_digest(self, pull_spec: str) -> str:
        """Extract image digest from container image pull spec
        
        Args:
            pull_spec: Container image pull spec string
            
        Returns:
            Image digest (sha256:...)
            
        Raises:
            ShipmentDataException: If pull spec is invalid or missing digest
        """
        if not pull_spec:
            raise ShipmentDataException("Empty pull spec provided")
            
        if "@sha256:" not in pull_spec:
            raise ShipmentDataException(f"Pull spec {pull_spec} does not contain digest")
            
        return pull_spec.split("@sha256:")[1]

    def _query_pyxis_freshness(self, image_digest: str) -> list[dict]:
        """Query Pyxis API for image freshness grades
        
        Args:
            image_digest: Image digest to query (sha256:...)
            
        Returns:
            List of freshness grade objects from Pyxis API
            
        Raises:
            ShipmentDataException: If API request fails
        """
        
        try:
            url = f"https://catalog.stage.redhat.com/api/containers/v1/images?filter=image_id==sha256:{image_digest}&page_size=100&page=0"
            proxies = {"https": "squid.corp.redhat.com:3128"}
            
            response = requests.get(url, proxies=proxies)
            response.raise_for_status()
            
            data = response.json()
            if not data.get("data"):
                return []
            return data["data"][0].get("freshness_grades", [])
        except Exception as e:
            raise ShipmentDataException(f"Failed to query Pyxis API: {str(e)}")

    def _get_current_image_health_status(self, grades: list[dict]) -> str:
        """Get current container image health status from Pyxis freshness grades
        
        Args:
            grades: List of freshness grade objects from Pyxis API
            
        Returns:
            Current health status (A, B, C, etc.) or "Unknown" if not found
            
        Note:
            Filters grades to find the one with start_date before now
            Uses Pyxis API's freshness attribute to determine health
        """
        
        if not grades:
            return "Unknown"
            
        now = datetime.now(timezone.utc)
        # Get all grades that started before now and sort by start_date (newest first)
        valid_grades = sorted(
            [g for g in grades if datetime.fromisoformat(g["start_date"]) <= now],
            key=lambda g: datetime.fromisoformat(g["start_date"]),
            reverse=True
        )
        
        if not valid_grades:
            return "Unknown"
            
        # Return the most recent grade (first in the sorted list)
        return valid_grades[0].get("grade", "Unknown")

    def check_component_image_health(self) -> ImageHealthData:
        """Check container image health status for all components in shipment MRs
        
        Returns:
            ImageHealthData: Container with health check results
        """
        unhealthy_components = []
        total_scanned = 0
        
        logger.info(f"Starting image health check for {len(self._mrs)} shipment MRs")

        # add this checkpoint, make sure stage release is completed successfully
        # then advisory url is available in shipment yaml
        if not self.is_stage_release_success():
            raise ShipmentDataException("Stage release pipeline is not completed yet")
        
        for mr in self._mrs:
            try:
                logger.info(f"Processing MR {mr.merge_request_id}")
                images = self._get_images_from_shipment(mr)
                logger.info(f"Found {len(images)} images to check")
                for image in images:
                    try:
                        pull_spec = image.get("containerImage")
                        if not pull_spec:
                            continue
                            
                        digest = self._get_image_digest(pull_spec)
                        component = image.get("component")
                        architecture = image.get("architecture")
                        logger.debug(f"Checking image health for {component} ({digest}) architecture={architecture}")
                        grades = self._query_pyxis_freshness(digest)
                        grade = self._get_current_image_health_status(grades)
                        
                        total_scanned += 1
                        logger.debug(f"Component {component} health grade: {grade}")
                        if grade and (grade == "Unknown" or grade > "B"):
                            unhealthy_components.append({
                                "name": component,
                                "grade": grade,
                                "pull_spec": pull_spec,
                                "architecture": architecture
                            })
                    except Exception as e:
                        logger.warning(f"Failed to check freshness for image: {str(e)}")
                        continue
            except Exception as e:
                logger.error(f"Failed to process MR {mr.merge_request_id}: {str(e)}")
                continue
                
        logger.info(f"Completed image health check. Scanned {total_scanned} images, found {len(unhealthy_components)} unhealthy")
        return ImageHealthData(
            total_scanned=total_scanned,
            unhealthy_components=unhealthy_components
        )

    def generate_image_health_summary(self, health_data: ImageHealthData = None) -> str:
        """Generate formatted summary of container image health check
        
        Args:
            health_data: Optional ImageHealthData from check_component_image_health()
        
        Returns:
            Formatted summary string for MR comment
        """
        if health_data is None:
            health_data = self.check_component_image_health()
        unhealthy_count = health_data.unhealthy_count
        
        summary = f"Images scanned: {health_data.total_scanned}. \n"
        summary += f"Unhealthy components detected: {health_data.unhealthy_count}. \n"
        summary += f"Health info missed: {health_data.unknown_count}. \n"
        
        if unhealthy_count > 0:
            summary += "Unhealthy components:\n"
            for comp in health_data.unhealthy_components:
                summary += f"{comp['name']} (grade {comp['grade']}, arch {comp['architecture']}) - {comp['pull_spec']}  \n"
                
        return summary

    def add_image_health_summary_comment(self, health_data: ImageHealthData = None) -> None:
        """Add container image health summary comment to all shipment MRs
        
        Args:
            health_data: Optional ImageHealthData from check_component_image_health()
        """
        summary = self.generate_image_health_summary(health_data)
        for mr in self._mrs:
            try:
                mr.add_comment(summary)
                logger.info(f"Added image health summary to MR {mr.merge_request_id}")
            except Exception as e:
                logger.error(f"Failed to add comment to MR {mr.merge_request_id}: {str(e)}")
                continue
