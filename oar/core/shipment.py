import gitlab
import re
import yaml
import os
import logging
import time
from gitlab.exceptions import (
    GitlabError,
    GitlabGetError,
    GitlabAuthenticationError,
    GitlabCreateError,
    GitlabListError
)
from oar.core.util import is_valid_email
from typing import List, Optional, Set
from urllib.parse import urlparse
from glom import glom, PathAccessError
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
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
        self._file_content_cache = {}  # Used to cache file contents during runtime to avoid GitLab API rate limits
        if not self.private_token:
            raise GitLabMergeRequestException("No GitLab token provided and GITLAB_TOKEN env var not set")
            
        self.gl = gitlab.Gitlab(gitlab_url, private_token=self.private_token, retry_transient_errors=True)
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

    def _get_jira_issue_line_number(self, jira_key: str, file_path: str) -> Optional[int]:
        """Get the line number where a Jira issue is referenced in a file
        
        Args:
            jira_key: Jira issue key (e.g. "OCPBUGS-123")
            file_path: Path to file in repository
            
        Returns:
            Line number where the Jira key appears (first match), or None if not found
            
        Raises:
            GitLabMergeRequestException: If unable to read file or invalid inputs
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
            if self.mr.state != 'opened':
                raise GitLabMergeRequestException(
                    f"Cannot approve MR in state: {self.mr.state}"
                )
            
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
        except GitlabListError as e:
            logger.error("Failed to query GitLab users: API error")
            raise GitLabServerException("GitLab API error") from e
        except Exception as e:
            logger.error("Failed to query GitLab users: Unexpected error", exc_info=False)
            raise GitLabServerException("Failed to query users") from e


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

    def drop_bugs(self) -> tuple[list[str], list[str]]:
        """Drop bugs from shipment files by adding suggestions to merge requests
        
        For each merge request:
        1. Gets all files changed in the MR
        2. For each file:
           a. Gets Jira issues from the file
           b. Identifies high severity and droppable bugs
           c. For each droppable bug, checks for existing suggestions before adding new one
           
        Returns:
            tuple[list[str], list[str]]: list of high severity jira keys, list of jira keys that can be dropped
            
        Raises:
            ShipmentDataException: If any operation fails
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
                                line_num = mr._get_jira_issue_line_number(issue_key, file_path)
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
