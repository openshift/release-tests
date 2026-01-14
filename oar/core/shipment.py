import yaml
import os
import logging
import requests
import time
import json
import subprocess
from datetime import datetime, timezone
from gitlab import Gitlab
from gitlab.exceptions import (
    GitlabError,
    GitlabGetError,
    GitlabAuthenticationError,
    GitlabCreateError,
    GitlabListError
)
from oar.core.util import is_valid_email, parse_mr_url, get_y_release, get_release_key
from typing import List, Optional, Set
from glom import glom
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
from oar.core.exceptions import (
    GitLabMergeRequestException,
    GitLabServerException,
    ShipmentDataException
)
from oar.core.git import GitHelper
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
            file_path: Path to file in repository (must be non-empty string)
            use_cache: Whether to use cached content if available (default: True)
            
        Returns:
            str: File content as string
            
        Raises:
            GitLabMergeRequestException: If file access fails or invalid inputs
            UnicodeDecodeError: If file content cannot be decoded
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
            List[str]: List of file paths changed in the merge request
            
        Raises:
            GitLabMergeRequestException: If unable to get changed files
        """
        try:
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
            Set[str]: Set of Jira issue IDs found in the file (e.g. {"OCPBUGS-123"})
            
        Note:
            Silently handles YAML parsing errors and returns empty set
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
            List[str]: Sorted list of unique Jira issue IDs (e.g. ["OCPBUGS-123", "OCPBUGS-456"])
            
        Raises:
            GitLabMergeRequestException: If unable to process merge request
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
        """Add comment to the merge request
        
        Args:
            comment: Text to add as comment
            
        Raises:
            GitLabMergeRequestException: If comment creation fails
        """
        try:
            self.mr.notes.create({'body': comment})
        except GitlabCreateError as e:
            raise GitLabMergeRequestException("Failed to add comment to merge request") from e

    def add_suggestion(self, file_path: str, old_line: int, new_line: int, suggestion: str, relative_lines: str = "-0+0") -> None:
        """Add a suggestion comment to a specific line in the merge request diff
        
        Args:
            file_path: Path to file in repository (must be non-empty string)
            old_line: Line number in old version (use None for new files)
            new_line: Line number in new version
            suggestion: Suggested change text
            relative_lines: Relative line numbers in format "-0+0" (default: "-0+0")
            
        Raises:
            GitLabMergeRequestException: If suggestion creation fails or invalid inputs
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

    def get_jira_issue_line_number(self, jira_key: str, file_path: str) -> Optional[dict]:
        """Get the line number where a Jira issue key appears in a file
        
        Searches for exact string match of the Jira key (case sensitive) and returns
        a dictionary containing details about the match.
        
        Args:
            jira_key: Complete Jira issue key (e.g. "OCPBUGS-123")
            file_path: Path to file in repository
            
        Returns:
            dict: Dictionary containing match details with keys:
                - line_number: First line number where jira_key appears
                - line_content: The full line content where match was found  
                - file_path: The file path searched
                - jira_key: The Jira key that was matched
                or None if not found
            
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
                    return {
                        'line_number': i,
                        'line_content': line,
                        'file_path': file_path,
                        'jira_key': jira_key
                    }
                    
            return None
        except (GitlabError, UnicodeDecodeError) as e:
            raise GitLabMergeRequestException(
                f"Failed to get line number for Jira issue {jira_key} in {file_path}"
            ) from e

    def get_id(self) -> int:
        """Get the merge request ID

        Returns:
            int: The numeric ID of this merge request
        """
        return self.merge_request_id

    def get_web_url(self) -> str:
        """Get the web URL for viewing this merge request
        
        Returns:
            str: The full web URL to view this merge request in GitLab
        """
        return self.mr.web_url

    def get_status(self) -> str:
        """Get the current status of the merge request
        
        Returns:
            str: Current state of MR ('opened', 'merged', 'closed')
        """
        return self.mr.state

    def get_source_branch(self) -> str:
        """Get the source branch name of the merge request

        Returns:
            str: Name of the source branch (typically a release branch)
        """
        return self.mr.source_branch

    def get_labels(self) -> List[str]:
        """Get all labels applied to the merge request

        Returns:
            List[str]: List of label names

        Raises:
            GitLabMergeRequestException: If unable to get labels
        """
        try:
            return self.mr.labels
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to get labels: {str(e)}") from e

    def has_label(self, label_name: str) -> bool:
        """Check if merge request has a specific label

        Args:
            label_name: Name of label to check for

        Returns:
            bool: True if label exists, False otherwise

        Raises:
            GitLabMergeRequestException: If unable to check labels
        """
        try:
            labels = self.get_labels()
            return label_name in labels
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to check label '{label_name}': {str(e)}") from e


    def _get_latest_pipeline(self):
        """Get the latest pipeline for this merge request with full metadata
        
        Returns:
            gitlab.v4.objects.ProjectPipeline: The most recent pipeline object with complete metadata,
            including jobs, bridges, and status details
            
        Raises:
            GitLabMergeRequestException: If no pipelines found or error occurs
            GitlabError: For GitLab API communication failures
            
        Note:
            This is an internal method not meant for direct use
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
            
        Note:
            This is an internal method not meant for direct use
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

        Checks both:
        1. Pipeline stage status is 'success', OR
        2. MR has 'stage-release-success' label

        Returns:
            bool: True if either pipeline succeeded or label exists, False otherwise

        Raises:
            GitLabMergeRequestException: If unable to get stage status
        """
        try:
            # First check if label exists (faster and more reliable)
            if self.has_label('stage-release-success'):
                logger.info("Stage release succeeded (verified by label)")
                return True

            # Fall back to pipeline status check
            stage_info = self.get_stage_release_info()
            if stage_info['status'] == 'success':
                logger.info("Stage release succeeded (verified by pipeline status)")
                return True

            logger.error(f"Stage release failed with status {stage_info['status']}")
            logger.error(f"Job details: {stage_info['job'].pformat()}")
            return False
        except Exception as e:
            raise GitLabMergeRequestException(f"Failed to check stage release status: {str(e)}") from e

    def is_prod_release_success(self) -> bool:
        """Check if the prod-release-triggers stage has succeeded

        Checks both:
        1. Pipeline stage status is 'success', OR
        2. MR has 'prod-release-success' label

        Returns:
            bool: True if either pipeline succeeded or label exists, False otherwise

        Raises:
            GitLabMergeRequestException: If unable to get stage status
        """
        try:
            # First check if label exists (faster and more reliable)
            if self.has_label('prod-release-success'):
                logger.info("Prod release succeeded (verified by label)")
                return True

            # Fall back to pipeline status check
            stage_info = self.get_prod_release_info()
            if stage_info['status'] == 'success':
                logger.info("Prod release succeeded (verified by pipeline status)")
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
                'status': str - overall stage status ('running', 'success', 'failed', 'not_found'),
                'job': gitlab.v4.objects.ProjectPipelineJob - first job object in the stage
            }
            
        Raises:
            GitLabMergeRequestException: If stage not found or pipeline error
            GitlabError: For GitLab API communication failures
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
            
        Raises:
            GitLabMergeRequestException: If unable to get pipeline info
        """
        return self.get_release_info("stage-release-triggers")

    def get_prod_release_info(self) -> dict:
        """Get detailed info about the 'prod-release-triggers' stage from latest pipeline
        
        Returns:
            dict: See get_release_info()
            
        Raises:
            GitLabMergeRequestException: If unable to get pipeline info
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

    def is_merged(self) -> bool:
        """Check if the merge request is in 'merged' state

        Returns:
            bool: True if MR is merged, False otherwise

        Raises:
            GitLabMergeRequestException: If unable to get MR status
        """
        return self.get_status() == 'merged'

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
    """Handles server-level GitLab operations not specific to a single project.
    
    Provides functionality for operations that require server-wide access,
    such as user lookup by email across all projects.
    """
    
    def __init__(self, gitlab_url: str, private_token: str = None):
        """Initialize GitLab server connection.
        
        Args:
            gitlab_url: URL of GitLab instance (hostname only, no protocol)
            private_token: Optional personal access token, falls back to
                         GITLAB_TOKEN environment variable
                         
        Raises:
            ValueError: If no token provided and GITLAB_TOKEN env var not set
        """
        self.gitlab_url = gitlab_url
        self.private_token = private_token or os.getenv('GITLAB_TOKEN')
        
        if not self.private_token:
            raise ValueError("No GitLab token provided and GITLAB_TOKEN env var not set")
            
        self.gl = Gitlab(gitlab_url, private_token=self.private_token)
        
    def get_username_by_email(self, email: str) -> Optional[str]:
        """Look up GitLab username by email address across all projects.
        
        Args:
            email: Valid email address to search for (e.g. "user@example.com")
            
        Returns:
            Optional[str]: First matching GitLab username if found, None otherwise
            
        Raises:
            ValueError: If email is empty, not a string, or invalid format
            GitLabServerException: If unable to query GitLab users API
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

    def get_mr_by_title(self, title: str, project_name: str = None) -> GitLabMergeRequest:
        """Get a merge request matching the given title, optionally scoped to a project.
        
        Searches for merge requests with matching title (case-insensitive). When multiple 
        matches found, returns the first one. If no matches found, returns None.
        
        Args:
            title: Title string to search for in MRs (case-insensitive)
            project_name: Optional project name in 'namespace/project' format to scope search.
                         If None, searches across all projects on the GitLab server.
            
        Returns:
            GitLabMergeRequest: Initialized merge request object if found, None otherwise.
            
        Raises:
            ValueError: If title is empty or not a string
            GitLabServerException: If unable to query GitLab API
            
        Example:
            >>> server = GitLabServer("gitlab.example.com")
            >>> mr = server.get_mr_by_title("Bugfix for OCPBUGS-123")
            >>> if mr:
            ...     print(f"Found MR {mr.get_id()}")
        """
        if not title or not isinstance(title, str):
            raise ValueError("Title must be a non-empty string")
            
        try:
            if project_name:
                project = self.gl.projects.get(project_name)
                mrs = project.mergerequests.list(search=title, state='opened')
            else:
                mrs = self.gl.mergerequests.list(search=title, state='opened')
            if not mrs:
                return None
                
            return GitLabMergeRequest(
                gitlab_url=self.gitlab_url,
                project_name=mrs[0].project_id,
                merge_request_id=mrs[0].iid,
                private_token=self.private_token
            )
            
        except GitlabListError as e:
            logger.error("Failed to query GitLab merge requests: API error")
            raise GitLabServerException("GitLab API error") from e
        except Exception as e:
            logger.error("Failed to query GitLab merge requests: Unexpected error", exc_info=False)
            raise GitLabServerException(f"GitLab API error: Failed to query MRs - {str(e)}") from e

    def create_merge_request(self, source_project_name: str, source_branch: str, target_branch: str, 
                           title: str, description: str = "", labels: List[str] = None,
                           target_project_name: str = None, auto_merge: bool = False) -> GitLabMergeRequest:
        """Create a new merge request in the specified project.
        
        Args:
            source_project_name: Project name in 'namespace/project' format (source project)
            source_branch: Branch to merge from
            target_branch: Branch to merge into 
            title: Title of the merge request
            description: Optional description for the MR
            labels: Optional list of labels to apply
            target_project_name: Optional target project name in 'namespace/project' format.
                          If provided, indicates the target branch is in a different repository.
                          If None, target branch is assumed to be in the same project as source.
            auto_merge: If True, enables auto-merge for this MR when pipeline succeeds and sets squash to true
            
        Returns:
            GitLabMergeRequest: Initialized merge request object
            
        Raises:
            ValueError: If any required parameter is invalid
            GitLabServerException: If MR creation fails
            
        Example:
            >>> server = GitLabServer("gitlab.example.com")
            >>> # Same project merge request
            >>> mr = server.create_merge_request(
            ...     "mygroup/myproject",
            ...     "feature-branch",
            ...     "main",
            ...     "Implement new feature",
            ...     "Detailed description here",
            ...     ["enhancement"]
            ... )
            >>> # Forked repository merge request
            >>> mr = server.create_merge_request(
            ...     "mygroup/myproject",
            ...     "feature-branch",
            ...     "main",
            ...     "Implement new feature from fork",
            ...     "Detailed description here",
            ...     ["enhancement"],
            ...     target_project_name="namespace/project"
            ... )
            >>> # Auto-merge enabled MR
            >>> mr = server.create_merge_request(
            ...     "mygroup/myproject",
            ...     "feature-branch",
            ...     "main",
            ...     "Implement new feature",
            ...     "Detailed description here",
            ...     ["enhancement"],
            ...     None,
            ...     True
            ... )
        """
        if not source_project_name or not isinstance(source_project_name, str):
            raise ValueError("Source project name must be a non-empty string")
        if not source_branch or not isinstance(source_branch, str):
            raise ValueError("Source branch must be a non-empty string")
        if not target_branch or not isinstance(target_branch, str):
            raise ValueError("Target branch must be a non-empty string")
        if not title or not isinstance(title, str):
            raise ValueError("Title must be a non-empty string")
            
        try:
            source_project = self.gl.projects.get(source_project_name)
            mr_data = {
                'source_branch': source_branch,
                'target_branch': target_branch,
                'title': title,
                'description': description
            }
            
            # Set squash to true when auto-merge is enabled
            if auto_merge:
                mr_data['squash'] = True
                logger.info("Auto-merge enabled, setting squash to true")
            
            # Handle forked repository scenario
            target_project = None
            if target_project_name:
                target_project = self.gl.projects.get(target_project_name)
                mr_data['target_project_id'] = target_project.id
                logger.info(f"Creating MR from forked repository: {source_project_name}:{source_branch} -> {target_project_name}:{target_branch}")
                
            if labels:
                mr_data['labels'] = labels
                
            mr = source_project.mergerequests.create(mr_data)
            logger.info(f"Created MR {mr.iid} in project {source_project_name}")

            # Enable auto-merge if requested
            if auto_merge:
                # Wait for MR to be fully available before enabling auto-merge
                # This avoids 404 errors when MR is still being created
                logger.info("Waiting for MR to be fully available before setting auto-merge...")
                # A robust poller checks the merge_status property
                timeout_seconds = 300  # 5 minutes
                start_time = time.time()
                
                while time.time() - start_time < timeout_seconds:
                    # Re-fetch the MR object to get its current state
                    updated_mr = target_project.mergerequests.get(mr.iid) if target_project else source_project.mergerequests.get(mr.iid)
                    
                    # Check if the MR is ready to be merged (e.g., all checks passed)
                    if updated_mr.merge_status == 'can_be_merged':
                        logger.info("MR is ready. Proceeding with auto-merge.")
                        mr = updated_mr
                        break
                    
                    logger.info(f"MR merge status: {updated_mr.merge_status}. Waiting...")
                    time.sleep(10) # Wait 10 seconds before polling again
                else:
                    # This code runs if the loop times out
                    raise TimeoutError("Timeout: MR was not ready for auto-merge within the time limit.")
                
                # Enable auto-merge when pipeline succeeds
                mr.merge(merge_when_pipeline_succeeds=True)
                logger.info(f"Auto-merge enabled for MR {mr.iid}")
            
            return GitLabMergeRequest(
                gitlab_url=self.gitlab_url,
                project_name=target_project_name,
                merge_request_id=mr.iid,
                private_token=self.private_token
            )
        except GitlabCreateError as e:
            logger.error(f"Failed to create MR in project {source_project_name}: GitLab API error")
            raise GitLabServerException("Failed to create merge request") from e
        except Exception as e:
            logger.error(f"Failed to create MR in project {source_project_name}: Unexpected error", exc_info=False)
            raise GitLabServerException(f"Failed to create merge request: {str(e)}") from e


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
        """Initialize with ConfigStore instance
        
        Args:
            config_store: ConfigStore instance containing configuration data
        """
        self._cs = config_store
        self._mr = self._initialize_mr()
        
    def _initialize_mr(self) -> GitLabMergeRequest:
        """Initialize GitLabMergeRequest objects from shipment MRs
        
        Returns:
            GitLabMergeRequest: Initialized merge request object in 'opened' state
            
        Raises:
            ShipmentDataException: If unable to initialize merge request
        """
        url = self._cs.get_shipment_mr()
        
        mr = None
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
            
            # Only need to handle opened MR
            if not mr.is_opened():
                raise ShipmentDataException(f"Gitlab MR {mr_id} state is not open")
        except Exception as e:
            logger.warning(f"Failed to initialize MR from {url}: {str(e)}")
                
        return mr

    def get_mr(self) -> GitLabMergeRequest:
        """Get the initialized merge request
        
        Returns:
            GitLabMergeRequest: The initialized merge request instance
        """
        return self._mr

    def get_jira_issues(self) -> List[str]:
        """Get Jira issue IDs from shipment YAML files where source is issues.redhat.com
        
        Returns:
            List[str]: Sorted list of unique Jira issue IDs (e.g. ["OCPBUGS-123", "OCPBUGS-456"])
            
        Raises:
            ShipmentDataException: If unable to get issues from merge request
        """
                
        return sorted(self._mr.get_jira_issues())

    def add_qe_release_lead_comment(self, email: str) -> None:
        """Add comment to shipment merge request identifying QE release lead
        
        Args:
            email: Email address of QE release lead to look up in GitLab
            
        Raises:
            ShipmentDataException: If email is invalid or username not found
            GitLabMergeRequestException: If unable to add comment
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
            
            try:
                self._mr.add_comment(comment)
                logger.info(f"Added QE release lead comment to MR {self._mr.merge_request_id}")
            except Exception as e:
                logger.error(f"Failed to add comment to MR {self._mr.merge_request_id}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error adding QE release lead comments: {str(e)}")
            raise ShipmentDataException(f"Failed to add QE release lead comments: {str(e)}")

    def add_qe_approval(self) -> None:
        """Add QE approval to shipment merge request
        
        Raises:
            ShipmentDataException: If approval fails
            GitLabMergeRequestException: If unable to approve merge request
        """
        try:
            self._mr.approve()
            logger.info(f"Successfully added QE approval to MR {self._mr.merge_request_id}")
        except Exception as e:
            logger.error(f"Failed to approve MR {self._mr.merge_request_id}: {str(e)}")
            raise ShipmentDataException(f"Failed to approve merge request: {str(e)}")

    def is_stage_release_success(self) -> bool:
        """Check if stage-release-triggers stage has succeeded for shipment MR
        
        Returns:
            bool: True if stage release succeeded, False otherwise
            
        Raises:
            ShipmentDataException: If unable to check stage status
        """
            
        return self._mr.is_stage_release_success()

    def is_prod_release_success(self) -> bool:
        """Check if prod-release-triggers stage has succeeded for shipment MR

        Returns:
            bool: True if prod release succeeded, False otherwise

        Raises:
            ShipmentDataException: If unable to check stage status
        """

        return self._mr.is_prod_release_success()

    def is_mr_merged(self) -> bool:
        """Check if the shipment merge request is in 'merged' state

        Returns:
            bool: True if MR is merged, False otherwise

        Raises:
            ShipmentDataException: If unable to check MR status
        """
        return self._mr.is_merged()

    def drop_bugs(self) -> list[str]:
        """Create or update a merge request to drop unverified bugs from shipment YAML files.
        
        This method:
        1. Identifies ON_QA Jira issues that can be dropped (excluding CVE tracker bugs)
        2. Checks if a drop bugs merge request already exists
        3. If MR exists: checks out the existing branch and updates it
        4. If no MR exists: creates a new branch and merge request
        5. Processes all shipment YAML files to remove droppable issues using string manipulation
        6. Commits only modified files and pushes to the appropriate repository
        7. Returns the list of dropped Jira issue keys
        
        The method handles both scenarios:
        - Existing MR: Updates the existing branch with latest changes
        - New MR: Creates new branch based on release branch, push the changes to forked repository and new merge request
        
        Returns:
            list[str]: List of Jira issue keys that were dropped from shipment files
                
        Raises:
            ShipmentDataException: If unable to process merge requests or files
            GitlabError: For GitLab API communication failures
        """
        jira_manager = JiraManager(self._cs)
        jira_issues = self._mr.get_jira_issues()
        # get all onqa issues except cve trackers
        unverified_issues = jira_manager.get_unverified_issues_excluding_cve(jira_issues)

        # Check if there are any onqa issues to drop
        if not unverified_issues:
            logger.info("No ONQA issues found to drop, returning early")
            return []

        # define the MR title
        mr_title = f"{self._cs.release} drop bugs"
        # need to check if MR with above title exists or not
        gl = GitLabServer(self._cs.get_gitlab_url(), self._cs.get_gitlab_token())
        gh = GitHelper()
        mr = gl.get_mr_by_title(mr_title, self._mr.project_name)
        
        # if mr already exists, don't need to create new mr
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        repo_dir = ""
        branch = f"drop-bugs-for-{self._cs.release}-{timestamp}"
        if mr:
            # get source project info from existing mr metadata
            # check out the branch from source project
            source_project = mr.gl.projects.get(mr.mr.source_project_id)
            repo_dir = gh.checkout_repo(source_project.http_url_to_repo, mr.get_source_branch())
            # configure credential for remote origin, just need to update this branch
            gh.configure_remotes("origin", f"https://group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self._cs.get_gitlab_token()}@gitlab.cee.redhat.com/rioliu/ocp-shipment-data.git")
        else:
            # if mr does not exist, check out release branch and create new branch based on it
            repo_dir = gh.checkout_repo(branch=self._mr.get_source_branch())
            # configure git remotes, add auth credential to the url
            # ert-release-bot is forked repo, new changes will be pushed to this repo
            gh.configure_remotes("ert-release-bot", f"https://group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self._cs.get_gitlab_token()}@gitlab.cee.redhat.com/rioliu/ocp-shipment-data.git")
            gh.configure_remotes("origin", f"https://group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self._cs.get_gitlab_token()}@gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data.git")
            gh.create_branch(branch)

        # Track modified files for selective committing
        modified_files = []
        
        # get all the effective files from shipment MR
        files = self._mr.get_all_files()
        for path in files:
            abs_path = f"{repo_dir}/{path}"
            
            # Process file using string manipulation to preserve YAML formatting
            try:
                with open(abs_path, 'r') as file:
                    original_content = file.read()
                
                # Use string-based approach to remove bug items while preserving formatting
                modified_content = self._remove_bugs_from_yaml_string(original_content, unverified_issues)
                
                # Only write back if content actually changed
                if modified_content != original_content:
                    with open(abs_path, 'w') as file:
                        file.write(modified_content)
                    modified_files.append(path)
                    logger.info(f"Removed onqa issues from {path}")
                    
            except (FileNotFoundError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to process file {path}: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error processing file {path}: {str(e)}")
                continue
        
        # Only commit if files were actually modified
        if modified_files:
            # Stage and commit only the modified files
            gh.commit_changes("drop bugs from shipment yaml files", files=modified_files)
        else:
            logger.info("No files were modified - no changes to commit")
            # If no files were modified, return empty list instead of onqa_issues
            return []
        
        
        if mr:
            gh.push_changes()
        else:
            # push the local change to forked repo
            gh.push_changes("ert-release-bot")
            # create new MR on gitlab server
            new_mr = gl.create_merge_request("rioliu/ocp-shipment-data", branch, self._mr.get_source_branch(), mr_title, target_project_name="hybrid-platforms/art/ocp-shipment-data", auto_merge=True)
            self._mr.add_comment(f"Drop bug in MR: {new_mr.get_web_url()}")

        return unverified_issues

    def _remove_bugs_from_yaml_string(self, yaml_content: str, bugs_to_remove: list[str]) -> str:
        """Remove specific bug items from YAML content by identifying and removing lines.
        
        This method preserves the original YAML formatting while removing only
        the specified bug items from the fixed issues list.
        
        Args:
            yaml_content: The original YAML content as a string
            bugs_to_remove: List of bug IDs to remove (e.g. ["OCPBUGS-123", "OCPBUGS-456"])
            
        Returns:
            str: Modified YAML content with specified bugs removed, preserving all formatting
        """
        if not bugs_to_remove:
            return yaml_content
            
        # Preserve original line endings by splitting on newlines and keeping them
        lines = yaml_content.split('\n')
        lines_to_remove = set()
        
        # Identify lines to remove
        for i, line in enumerate(lines):
            for bug_id in bugs_to_remove:
                # Check if this line contains the bug ID we want to remove
                if f'id: {bug_id}' in line and line.strip().startswith('-'):
                    # Mark this line and the next line (which should contain source) for removal
                    lines_to_remove.add(i)
                    if i + 1 < len(lines) and 'source: issues.redhat.com' in lines[i + 1]:
                        lines_to_remove.add(i + 1)
        
        # Build new content without the removed lines
        modified_lines = []
        for i, line in enumerate(lines):
            if i not in lines_to_remove:
                modified_lines.append(line)
        
        # Join lines back together with original line endings
        modified_content = '\n'.join(modified_lines)
        
        return modified_content

    def _get_images_from_shipment(self, mr: GitLabMergeRequest) -> list:
        """Extract container images from advisories referenced in shipment YAML files.
        
        Args:
            mr: GitLabMergeRequest instance containing the shipment files
            
        Returns:
            list: List of image dictionaries from advisories (spec.content.images),
                  each containing containerImage, component, and architecture fields
                  
        Raises:
            ShipmentDataException: If unable to process shipment files or fetch advisories
            
        Note:
            Skips files containing ".fbc." in their path
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
        """Parse and validate the SHA256 digest from a container image pull specification.
        
        Args:
            pull_spec: Full container image pull specification string
                      (e.g. "registry.example.com/repo/image@sha256:abc123")
                      
        Returns:
            str: The image digest portion (e.g. "abc123")
            
        Raises:
            ShipmentDataException: 
                - If pull_spec is empty or None
                - If pull_spec doesn't contain a valid SHA256 digest
        """
        if not pull_spec:
            raise ShipmentDataException("Empty pull spec provided")
            
        if "@sha256:" not in pull_spec:
            raise ShipmentDataException(f"Pull spec {pull_spec} does not contain digest")
            
        return pull_spec.split("@sha256:")[1]

    def _query_pyxis_freshness(self, image_digest: str) -> list[dict]:
        """Query Pyxis container registry API for image freshness grades.
        
        Args:
            image_digest: SHA256 image digest to query (without "sha256:" prefix)
            
        Returns:
            list[dict]: List of freshness grade objects from Pyxis API response,
                       each containing start_date and grade fields
                       
        Raises:
            ShipmentDataException: If API request fails or returns invalid response
            
        Note:
            Uses corporate proxy (squid.corp.redhat.com:3128) for the request
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
        """Determine the current health status from Pyxis freshness grades.
        
        Args:
            grades: List of freshness grade dictionaries from Pyxis API,
                   each containing start_date and grade fields
                   
        Returns:
            str: Current health status grade (A, B, C, etc.) or "Unknown" if:
                 - No grades provided
                 - No valid grades found (start_date <= current time)
                 
        Note:
            Selects the most recent valid grade (newest start_date before now)
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
        """Check health status of container images referenced in shipment merge requests.
        
        Returns:
            ImageHealthData: Container with health check results including:
                - total_scanned: Number of images checked
                - unhealthy_components: List of unhealthy components
                - unhealthy_count: Count of unhealthy components
                - unknown_count: Count of components with unknown health status
                
        Raises:
            ShipmentDataException: If stage release pipeline is not completed
                                  or unable to check image health
        """
        unhealthy_components = []
        total_scanned = 0
        
        logger.info(f"Starting image health check for shipment MR {self._mr.get_id()}")

        # add this checkpoint, make sure stage release is completed successfully
        # then advisory url is available in shipment yaml
        if not self.is_stage_release_success():
            raise ShipmentDataException("Stage release pipeline is not completed yet")
        
        try:
            logger.info(f"Processing MR {self._mr.merge_request_id}")
            images = self._get_images_from_shipment(self._mr)
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
            logger.error(f"Failed to process MR {self._mr.get_id()}: {str(e)}")
                
        logger.info(f"Completed image health check. Scanned {total_scanned} images, found {len(unhealthy_components)} unhealthy")
        return ImageHealthData(
            total_scanned=total_scanned,
            unhealthy_components=unhealthy_components
        )

    def generate_image_health_summary(self, health_data: ImageHealthData = None) -> str:
        """Generate Markdown-formatted summary of container image health status.
        
        Args:
            health_data: Optional ImageHealthData from check_component_image_health().
                        If None, will run check_component_image_health() automatically.
                        
        Returns:
            str: Formatted Markdown summary containing:
                 - Total images scanned
                 - Count of unhealthy components
                 - Count of components with unknown health status
                 - Detailed list of unhealthy components (if any)
        """
        if health_data is None:
            health_data = self.check_component_image_health()
        unhealthy_count = health_data.unhealthy_count
        
        summary = f"Images scanned: {health_data.total_scanned}.  \n"
        summary += f"Unhealthy components detected: {health_data.unhealthy_count}.  \n"
        summary += f"Health info missed: {health_data.unknown_count}.  \n"
        
        if unhealthy_count > 0:
            summary += "Unhealthy components:  \n"
            for comp in health_data.unhealthy_components:
                summary += f"{comp['name']} (grade {comp['grade']}, arch {comp['architecture']}) - {comp['pull_spec']}.  \n"
                
        return summary

    def add_image_health_summary_comment(self, health_data: ImageHealthData = None) -> None:
        """Add image health summary as a comment to shipment merge requests.
        
        Args:
            health_data: Optional ImageHealthData from check_component_image_health().
                        If None, will run check_component_image_health() automatically.
                        
        Raises:
            GitLabMergeRequestException: If unable to add comment to merge request
        """
        summary = self.generate_image_health_summary(health_data)
        try:
            self._mr.add_comment(summary)
            logger.info(f"Added image health summary to MR {self._mr.merge_request_id}")
        except Exception as e:
            logger.error(f"Failed to add comment to MR {self._mr.merge_request_id}: {str(e)}")

    def check_cve_tracker_bug(self):
        """
        Call elliott cmd to check if any new CVE tracker bug found for shipment
        
        Raises:
            ShipmentDataException: error when invoke elliott cmd

        Returns:
            list: CVE tracker bugs not found in shipment yamls
        """
        cmd = [
            "elliott",
            "--data-path",
            "https://github.com/openshift-eng/ocp-build-data.git",
            "--group",
            f"openshift-{get_y_release(self._cs.release)}",
            "--assembly",
            get_release_key(self._cs.release),
            "--build-system",
            "konflux",
            "find-bugs",
            "--cve-only",
            "-o",
            "json"
        ]

        logger.debug(f"elliott cmd {cmd}")

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise ShipmentDataException(f"elliott cmd error:\n {stderr}")

        cve_tracker_bugs = []
        result = stdout.decode("utf-8")
        if result:
            logger.debug(result)
            json_obj = json.loads(result)
            
            # Get all jira issues from shipment yamls
            shipment_jira_issues = self.get_jira_issues()
            
            # Iterate through all values in the JSON output (each value is a list of bugs)
            for trackers in json_obj.values():
                if isinstance(trackers, list):
                    for tracker in trackers:
                        # add it to missed bug list if it is not found in shipment yamls
                        if tracker not in shipment_jira_issues:
                            logger.info(f"Missed CVE tracker bug {tracker} is not found in shipment data")
                            cve_tracker_bugs.append(tracker)

        return cve_tracker_bugs
