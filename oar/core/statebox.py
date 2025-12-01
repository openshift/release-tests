"""
StateBox - Persistent state management for OAR release workflow

This module provides a GitHub-backed YAML storage system for managing release workflow state.
It implements SHA-based optimistic locking for concurrent access and intelligent merge logic
for conflict resolution.

Storage:
    - Repository: release-tests
    - Branch: z-stream
    - Path: _releases/{y-stream}/statebox/{release}.yaml

YAML Schema:
    release: str                    # Release version (e.g., "4.19.1")
    created_at: datetime            # Creation timestamp
    updated_at: datetime            # Last update timestamp
    metadata:                       # Release metadata
        jira_ticket: str            # ART Jira ticket
        advisory_ids: dict          # Advisory IDs from ocp-build-data (e.g., rpm, rhcos, microshift)
        release_date: str           # Planned release date
        candidate_builds: dict      # Candidate builds by arch
        shipment_mr: str            # GitLab shipment MR URL
    tasks:                          # Task execution status (latest state only)
        - name: str                 # Task name
          status: str               # Status: "Not Started", "In Progress", "Pass", "Fail"
          started_at: datetime      # When task started
          completed_at: datetime    # When task completed
          result: str               # CLI command output (AI-readable, sensitive data masked)
    issues: list                    # Issues (blocking and non-blocking)
        - issue: str                # Issue description
          reported_at: datetime     # When reported
          resolved: bool            # Resolution status
          resolution: str           # Resolution details
          blocker: bool             # Is this a blocker?
          related_tasks: list       # Related task names (empty = general issue)

Example Usage:
    # Initialize StateBox with ConfigStore
    from oar.core.configstore import ConfigStore
    cs = ConfigStore("4.19.1")
    statebox = StateBox(cs)

    # Load existing state or create new
    state = statebox.load()

    # Update task status
    statebox.update_task("image-consistency-check", status="In Progress")

    # Update task with result
    statebox.update_task(
        "image-consistency-check",
        status="Pass",
        result="Jenkins job completed successfully. All images verified."
    )

    # Add blocking issue (task-specific)
    statebox.add_issue(
        "CVE-2024-12345 not covered in advisory",
        blocker=True,
        related_tasks=["check-cve-tracker-bug"]
    )

    # Add blocking issue (general)
    statebox.add_issue(
        "ART build pipeline down - ETA: 2025-01-16",
        blocker=True,
        related_tasks=[]  # Empty = affects entire release
    )

    # Update metadata
    statebox.update_metadata({"jira_ticket": "ART-12345"})

API Reference:

Core Operations:
    StateBox(configstore, repo_name="openshift/release-tests", branch="z-stream", github_token=None)
        Initialize StateBox for a specific release.

        Args:
            configstore: ConfigStore instance (provides release version and configuration)
            repo_name: GitHub repository name (default: "openshift/release-tests")
            branch: Branch name (default: "z-stream")
            github_token: GitHub token (default: from GITHUB_TOKEN env)

        Raises:
            StateBoxException: If GitHub token is missing

        Note:
            Release version is extracted from configstore.release.
            ConfigStore can be cached (MCP server) or freshly created (CLI).

    exists() -> bool
        Check if state file exists in GitHub.

        Returns:
            True if file exists, False otherwise

    load(force_refresh=False) -> Dict[str, Any]
        Load state from GitHub with caching support.

        Args:
            force_refresh: Bypass cache and fetch from GitHub

        Returns:
            State dictionary (or default state if file doesn't exist)

        Note: Uses internal cache for performance. First call fetches from GitHub,
              subsequent calls use cache unless force_refresh=True.

    save(state, message="Update state", retry=True) -> None
        Save state to GitHub with SHA-based optimistic locking.

        Args:
            state: State dictionary to save
            message: Commit message
            retry: Enable automatic retry with merge on conflict

        Raises:
            StateBoxException: If save fails after MAX_RETRIES attempts

        Note: Automatically handles concurrent updates via intelligent merge.
              Updates state["updated_at"] timestamp automatically.

Task Management:
    update_task(task_name, status=None, result=None, auto_save=True) -> Dict[str, Any]
        Update task status and result. Creates task if doesn't exist.

        Args:
            task_name: Name of the task
            status: New status ("Not Started", "In Progress", "Pass", "Fail")
            result: CLI command output (AI-readable text)
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            Updated state dictionary

        Raises:
            StateBoxException: If status not in VALID_TASK_STATUSES

        Note: Automatically manages started_at/completed_at timestamps based
              on status transitions.

    get_task(task_name) -> Optional[Dict[str, Any]]
        Get complete task information.

        Args:
            task_name: Name of the task

        Returns:
            Task dictionary or None if task doesn't exist

    get_task_status(task_name) -> Optional[str]
        Get current status of a task.

        Args:
            task_name: Name of the task

        Returns:
            Task status or None if task doesn't exist

Metadata Management:
    update_metadata(updates, auto_save=True) -> Dict[str, Any]
        Update metadata fields with intelligent nested dict merging.

        Args:
            updates: Dictionary of metadata fields to update
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            Updated state dictionary

        Note: For advisory_ids and candidate_builds, performs dict.update()
              to merge new values with existing ones.

        Example:
            # Merge advisory IDs
            statebox.update_metadata({
                "advisory_ids": {"rpm": 12345, "rhcos": 12346}
            })

            # Update single field
            statebox.update_metadata({"jira_ticket": "ART-12345"})

    get_metadata(key=None) -> Any
        Get metadata value(s).

        Args:
            key: Specific metadata key (None returns all metadata)

        Returns:
            Metadata value or entire metadata dict

Issue Management:
    add_issue(issue, blocker=True, related_tasks=None, auto_save=True) -> Dict[str, Any]
        Add an issue with automatic deduplication.

        Args:
            issue: Issue description
            blocker: Is this a blocking issue? (default: True)
            related_tasks: List of related task names (None/empty = general issue)
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            Issue entry dictionary

        Raises:
            StateBoxException: If task already has unresolved blocker

        Note: Only one unresolved blocker per task allowed. General blockers
              (related_tasks=[]) can have multiple unresolved instances.
              Performs case-insensitive deduplication.

    resolve_issue(issue, resolution, auto_save=True) -> Dict[str, Any]
        Resolve an issue by description (supports fuzzy matching).

        Args:
            issue: Issue description (can be partial)
            resolution: Resolution description
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            Resolved issue entry dictionary

        Raises:
            StateBoxException: If issue not found

        Note: First tries exact match (case-insensitive), then partial match.

    get_task_blocker(task_name) -> Optional[Dict[str, Any]]
        Get unresolved blocking issue for a specific task.

        Args:
            task_name: Name of the task

        Returns:
            Blocking issue entry or None if task not blocked

    get_issues(unresolved_only=False, blockers_only=False, task_name=None) -> List[Dict[str, Any]]
        Get issues with optional filtering.

        Args:
            unresolved_only: Only return unresolved issues
            blockers_only: Only return blocking issues
            task_name: Only return issues related to specific task

        Returns:
            List of issue dictionaries

    get_general_blockers() -> List[Dict[str, Any]]
        Get all unresolved general blockers (not task-specific).

        Returns:
            List of general blocker issue entries

Concurrency & Performance:
    - SHA-based optimistic locking prevents lost updates
    - Automatic retry with exponential backoff (5 retries, 0.5s-10s)
    - Intelligent merge resolves conflicts automatically
    - Two-tier caching (state + SHA) reduces GitHub API calls
    - Thread-safe for read operations (writes use GitHub's atomic updates)

Error Handling:
    - StateBoxException: Raised for all StateBox-specific errors
    - Includes detailed error messages with context
    - Automatic retry on transient GitHub API failures (status 409)

Context Manager Support:
    from oar.core.configstore import ConfigStore
    cs = ConfigStore("4.19.1")
    with StateBox(cs) as statebox:
        statebox.update_task("task-name", status="Pass")
    # Automatic cleanup on exit
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import yaml
from github import Auth, Github
from github.GithubException import UnknownObjectException, GithubException

from oar.core.configstore import ConfigStore
from oar.core.const import SUPPORTED_TASK_NAMES, TASK_STATUS_PASS, TASK_STATUS_FAIL, TASK_STATUS_INPROGRESS, TASK_STATUS_NOT_STARTED
from oar.core.exceptions import StateBoxException
from oar.core.util import validate_release_version, get_current_timestamp

logger = logging.getLogger(__name__)


# Custom YAML representer for multi-line strings
def str_representer(dumper, data):
    """
    Custom YAML string representer that uses block scalar style for multi-line strings.

    This improves readability of multi-line log output in YAML files by using | style
    instead of quoted strings with escaped newlines.
    """
    if '\n' in data:
        # Multi-line string - use block scalar with strip chomping (|-)
        # This preserves line breaks and strips trailing newlines
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    # Single-line string - use default style
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


# Create custom dumper class with str representer
class StateBoxDumper(yaml.SafeDumper):
    """Custom YAML dumper for StateBox with block scalar support for multi-line strings."""
    pass


# Register the custom representer with our dumper
StateBoxDumper.add_representer(str, str_representer)


# YAML Schema Constants
SCHEMA_VERSION = "1.0"
DEFAULT_TASK_STATUS = TASK_STATUS_NOT_STARTED
VALID_TASK_STATUSES = [TASK_STATUS_NOT_STARTED, TASK_STATUS_INPROGRESS, TASK_STATUS_PASS, TASK_STATUS_FAIL]

# GitHub Repository Configuration
DEFAULT_REPO_NAME = "openshift/release-tests"
DEFAULT_BRANCH = "z-stream"
STATEBOX_PATH_PREFIX = "_releases"

# Retry Configuration
MAX_RETRIES = 5
INITIAL_BACKOFF = 0.5  # seconds
MAX_BACKOFF = 10.0  # seconds


def extract_start_timestamp(text: Optional[str]) -> Optional[str]:
    """
    Extract the first timestamp from CLI command output.

    Searches for ISO 8601 timestamps matching StateBox's datetime.now(timezone.utc).isoformat() format.
    Typical format: 2025-11-27T21:54:22.123456+00:00 or 2025-11-27T21:54:22Z

    Args:
        text: CLI command output containing timestamps

    Returns:
        First ISO 8601 timestamp found, or None if no timestamp found
    """
    if not text:
        return None

    # Match ISO 8601 format: YYYY-MM-DDTHH:MM:SS with optional microseconds and timezone
    # Handles both +00:00 and Z timezone formats
    pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})'
    match = re.search(pattern, text)

    return match.group(0) if match else None


def extract_end_timestamp(text: Optional[str]) -> Optional[str]:
    """
    Extract the last timestamp from CLI command output.

    Searches for ISO 8601 timestamps and returns the LAST occurrence,
    which typically represents when the task completed.

    Args:
        text: CLI command output containing timestamps

    Returns:
        Last ISO 8601 timestamp found, or None if no timestamp found
    """
    if not text:
        return None

    # Match ISO 8601 format: YYYY-MM-DDTHH:MM:SS with optional microseconds and timezone
    pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})'
    matches = re.findall(pattern, text)

    return matches[-1] if matches else None


def mask_sensitive_data(text: Optional[str]) -> Optional[str]:
    """
    Mask sensitive data in text before storing in public StateBox repository.

    Currently supports:
    - Email addresses: Redacted to [EMAIL_REDACTED]

    Future extensibility:
    - API tokens
    - Passwords
    - SSH keys
    - Personal identifiable information (PII)

    Args:
        text: Text to mask (e.g., command output, logs)

    Returns:
        Text with sensitive data masked, or None if input is None

    Examples:
        >>> mask_sensitive_data("Owner updated to user@redhat.com")
        'Owner updated to [EMAIL_REDACTED]'

        >>> mask_sensitive_data("Multiple emails: alice@example.com, bob@test.org")
        'Multiple emails: [EMAIL_REDACTED], [EMAIL_REDACTED]'

        >>> mask_sensitive_data(None)
        None

        >>> mask_sensitive_data("No sensitive data here")
        'No sensitive data here'
    """
    if text is None:
        return None

    # Redact email addresses
    # Pattern matches standard email format: user@domain.tld
    # Handles common formats like user.name+tag@subdomain.domain.tld
    masked_text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        '[EMAIL_REDACTED]',
        text
    )

    return masked_text


class StateBox:
    """
    Persistent state management for OAR release workflow using GitHub-backed YAML storage.

    Provides:
    - SHA-based optimistic locking for concurrent access
    - Automatic conflict resolution with intelligent merge
    - Retry logic with exponential backoff
    - Structured YAML schema

    Attributes:
        release (str): Release version (e.g., "4.19.1")
        repo_name (str): GitHub repository name
        branch (str): GitHub branch name
        file_path (str): Path to YAML file in repository
    """

    def __init__(
        self,
        configstore: ConfigStore,
        repo_name: str = DEFAULT_REPO_NAME,
        branch: str = DEFAULT_BRANCH,
        github_token: Optional[str] = None
    ):
        """
        Initialize StateBox for a specific release.

        Args:
            configstore: ConfigStore instance (provides release version and configuration)
            repo_name: GitHub repository name (default: "openshift/release-tests")
            branch: Branch name (default: "z-stream")
            github_token: GitHub personal access token (default: from GITHUB_TOKEN env)

        Raises:
            StateBoxException: If GitHub token is missing

        Note:
            Release version is extracted from configstore.release.
            ConfigStore can be cached (MCP server) or freshly created (CLI).
        """
        # Extract release from ConfigStore
        self._configstore = configstore
        self.release = configstore.release
        self.repo_name = repo_name
        self.branch = branch

        # Extract y-stream version (e.g., "4.19" from "4.19.1")
        y_stream = ".".join(self.release.split(".")[:2])
        self.file_path = f"{STATEBOX_PATH_PREFIX}/{y_stream}/statebox/{self.release}.yaml"

        # Initialize GitHub client
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise StateBoxException("GitHub token not found. Set GITHUB_TOKEN environment variable.")

        auth = Auth.Token(token)
        self._github = Github(auth=auth)
        self._repo = self._github.get_repo(repo_name)

        # Cache for current state and SHA
        self._state_cache: Optional[Dict[str, Any]] = None
        self._sha_cache: Optional[str] = None

        logger.info(f"Initialized StateBox for release {self.release} at {repo_name}/{branch}/{self.file_path}")

    def _get_default_state(self) -> Dict[str, Any]:
        """
        Create default state structure for a new release.

        Populates metadata from ConfigStore on initialization.

        Returns:
            dict: Default state dictionary
        """
        now = get_current_timestamp()
        return {
            "schema_version": SCHEMA_VERSION,
            "release": self.release,
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "jira_ticket": self._configstore.get_jira_ticket(),
                "advisory_ids": self._configstore.get_advisories() or {},
                "release_date": self._configstore.get_release_date(),
                "candidate_builds": self._configstore.get_candidate_builds() or {},
                "shipment_mr": self._configstore.get_shipment_mr() or None,
            },
            "tasks": [],
            "issues": [],
        }

    def exists(self) -> bool:
        """
        Check if state file exists in GitHub repository.

        Returns:
            bool: True if file exists, False otherwise
        """
        try:
            self._repo.get_contents(path=self.file_path, ref=self.branch)
            logger.debug(f"State file exists: {self.file_path}")
            return True
        except (UnknownObjectException, GithubException) as e:
            if isinstance(e, GithubException) and e.status != 404:
                # Re-raise non-404 errors
                raise StateBoxException(f"Failed to check file existence: {str(e)}") from e
            logger.debug(f"State file not found: {self.file_path}")
            return False

    def load(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Load state from GitHub repository.

        If file doesn't exist, returns default state structure (does not create file).
        Uses cached state unless force_refresh is True.

        Args:
            force_refresh: Force refresh from GitHub, bypass cache (default: False)

        Returns:
            dict: State dictionary

        Raises:
            StateBoxException: If loading fails
        """
        # Return cached state if available and not forcing refresh
        if not force_refresh and self._state_cache is not None:
            logger.debug("Returning cached state")
            return self._state_cache

        try:
            if not self.exists():
                logger.info(f"State file not found, returning default state")
                default_state = self._get_default_state()
                self._state_cache = default_state
                self._sha_cache = None
                return default_state

            # Fetch file content and SHA
            content = self._repo.get_contents(path=self.file_path, ref=self.branch)
            decoded_content = content.decoded_content.decode('utf-8')
            state = yaml.safe_load(decoded_content)

            # Cache state and SHA
            self._state_cache = state
            self._sha_cache = content.sha

            logger.info(f"Loaded state from {self.file_path} (SHA: {content.sha[:8]})")
            return state

        except yaml.YAMLError as e:
            raise StateBoxException(f"Failed to parse YAML: {str(e)}") from e
        except Exception as e:
            raise StateBoxException(f"Failed to load state: {str(e)}") from e

    def save(self, state: Dict[str, Any], message: str = "Update state", retry: bool = True) -> None:
        """
        Save state to GitHub repository with SHA-based optimistic locking.

        Automatically handles conflicts with retry and merge logic if retry=True.

        Args:
            state: State dictionary to save
            message: Commit message (default: "Update state")
            retry: Enable retry with merge on conflict (default: True)

        Raises:
            StateBoxException: If save fails after retries
        """
        attempt = 0
        backoff = INITIAL_BACKOFF

        while attempt < MAX_RETRIES:
            try:
                attempt += 1

                # Update timestamp on each attempt
                state["updated_at"] = get_current_timestamp()

                # Try to fetch current content (optimization: skip exists() check)
                try:
                    content = self._repo.get_contents(path=self.file_path, ref=self.branch)
                    current_sha = content.sha
                    file_exists = True
                except UnknownObjectException:
                    # File doesn't exist, will create
                    file_exists = False
                    current_sha = None

                if file_exists:
                    # Check if we need to merge with remote state
                    if self._sha_cache and current_sha != self._sha_cache:
                        logger.warning(f"SHA mismatch detected (expected: {self._sha_cache[:8]}, got: {current_sha[:8]})")

                        if retry:
                            # Load remote state and merge
                            logger.info(f"Attempt {attempt}/{MAX_RETRIES}: Merging with remote state...")
                            remote_state = yaml.safe_load(content.decoded_content.decode('utf-8'))
                            state = self._merge_states(state, remote_state)
                            # Update timestamp after merge
                            state["updated_at"] = get_current_timestamp()
                        else:
                            raise StateBoxException(
                                f"Concurrent modification detected. "
                                f"Expected SHA {self._sha_cache[:8]}, got {current_sha[:8]}. "
                                f"Enable retry=True for automatic conflict resolution."
                            )

                    # Re-fetch content immediately before update to minimize race window
                    content = self._repo.get_contents(path=self.file_path, ref=self.branch)
                    current_sha = content.sha

                    # Convert to YAML with latest state
                    # Use custom dumper for better multi-line string formatting
                    yaml_content = yaml.dump(
                        state,
                        Dumper=StateBoxDumper,
                        default_flow_style=False,
                        sort_keys=False,
                        allow_unicode=True
                    )

                    # Perform atomic update with fresh SHA
                    self._repo.update_file(
                        path=self.file_path,
                        message=message,
                        content=yaml_content,
                        branch=self.branch,
                        sha=current_sha
                    )
                    logger.info(f"Updated state file {self.file_path} (attempt {attempt})")
                else:
                    # Create new file
                    # Use custom dumper for better multi-line string formatting
                    yaml_content = yaml.dump(
                        state,
                        Dumper=StateBoxDumper,
                        default_flow_style=False,
                        sort_keys=False,
                        allow_unicode=True
                    )
                    self._repo.create_file(
                        path=self.file_path,
                        message=message,
                        content=yaml_content,
                        branch=self.branch
                    )
                    logger.info(f"Created state file {self.file_path}")

                # Update cache immediately after successful save (fix cache invalidation race)
                # Fetch fresh content to ensure cache consistency
                content = self._repo.get_contents(path=self.file_path, ref=self.branch)
                self._state_cache = yaml.safe_load(content.decoded_content.decode('utf-8'))
                self._sha_cache = content.sha
                logger.debug(f"Cache updated (SHA: {self._sha_cache[:8]})")

                return  # Success!

            except GithubException as e:
                if e.status == 409:  # Conflict - SHA changed between fetch and update
                    if retry and attempt < MAX_RETRIES:
                        logger.warning(f"Conflict detected (attempt {attempt}/{MAX_RETRIES}), retrying after {backoff}s...")
                        time.sleep(backoff)
                        backoff = min(backoff * 2, MAX_BACKOFF)  # Exponential backoff
                        # Force refresh cache before retry
                        self._state_cache = None
                        self._sha_cache = None
                        continue
                    else:
                        raise StateBoxException(f"Failed to save after {MAX_RETRIES} retries due to conflicts") from e
                else:
                    raise StateBoxException(f"GitHub API error (status {e.status}): {str(e)}") from e
            except yaml.YAMLError as e:
                raise StateBoxException(f"Failed to serialize state to YAML: {str(e)}") from e
            except Exception as e:
                raise StateBoxException(f"Unexpected error saving {self.file_path}: {type(e).__name__} {str(e)}") from e

        # Should not reach here
        raise StateBoxException(f"Failed to save state after {MAX_RETRIES} attempts")

    def _merge_states(self, local_state: Dict[str, Any], remote_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Intelligently merge local and remote states to resolve conflicts.

        Merge strategy:
        - Use remote state as base
        - Merge metadata fields (prefer local if not None)
        - Merge tasks by name (prefer local updates)
        - Append unique critical issues from both

        Args:
            local_state: Local state with changes
            remote_state: Remote state from GitHub

        Returns:
            dict: Merged state
        """
        logger.info("Merging local and remote states...")

        # Start with remote state as base
        merged = remote_state.copy()

        # Merge metadata fields (prefer local if not None)
        if "metadata" in local_state:
            for key, value in local_state["metadata"].items():
                if value is not None:
                    if key in ["advisory_ids", "candidate_builds"] and isinstance(value, dict):
                        # Merge nested dicts
                        merged["metadata"][key].update(value)
                    else:
                        merged["metadata"][key] = value

        # Merge tasks by name (prefer local updates, keep remote if task not in local)
        local_tasks_by_name = {task["name"]: task for task in local_state.get("tasks", [])}
        remote_tasks_by_name = {task["name"]: task for task in remote_state.get("tasks", [])}

        merged_tasks = []
        # Add all remote tasks, updating with local changes
        for name, remote_task in remote_tasks_by_name.items():
            if name in local_tasks_by_name:
                merged_tasks.append(local_tasks_by_name[name])
            else:
                merged_tasks.append(remote_task)

        # Add any new tasks from local that don't exist in remote
        for name, local_task in local_tasks_by_name.items():
            if name not in remote_tasks_by_name:
                merged_tasks.append(local_task)

        merged["tasks"] = merged_tasks

        # Merge issues with intelligent resolution state handling
        remote_issues = remote_state.get("issues", [])
        local_issues = local_state.get("issues", [])

        # Build index of remote issues by description (normalized)
        remote_issues_by_text = {
            issue["issue"].strip().lower(): issue
            for issue in remote_issues
        }

        # Merge local issues into remote
        for local_issue in local_issues:
            normalized_text = local_issue["issue"].strip().lower()

            if normalized_text in remote_issues_by_text:
                # Issue exists in both - merge resolution state
                remote_issue = remote_issues_by_text[normalized_text]

                # Prefer resolved state over unresolved (if either resolved, use that)
                if local_issue["resolved"] and not remote_issue["resolved"]:
                    # Local resolved but remote not - take local resolution
                    remote_issue["resolved"] = True
                    remote_issue["resolution"] = local_issue["resolution"]
                    remote_issue["resolved_at"] = local_issue.get("resolved_at")
                    logger.debug(f"Merged issue resolution from local: {local_issue['issue'][:50]}")
                elif not local_issue["resolved"] and remote_issue["resolved"]:
                    # Remote resolved but local not - keep remote resolution (already set)
                    logger.debug(f"Kept remote issue resolution: {remote_issue['issue'][:50]}")
                elif local_issue["resolved"] and remote_issue["resolved"]:
                    # Both resolved - prefer more recent resolution timestamp
                    local_resolved_at = local_issue.get("resolved_at")
                    remote_resolved_at = remote_issue.get("resolved_at")

                    if local_resolved_at and remote_resolved_at:
                        if local_resolved_at > remote_resolved_at:
                            remote_issue["resolution"] = local_issue["resolution"]
                            remote_issue["resolved_at"] = local_resolved_at
                            logger.debug(f"Updated resolution with newer local timestamp: {local_issue['issue'][:50]}")
                # If both unresolved, keep remote as-is
            else:
                # New issue from local - append to remote
                remote_issues.append(local_issue)
                logger.debug(f"Appended new issue from local: {local_issue['issue'][:50]}")

        merged["issues"] = remote_issues

        logger.info("State merge completed")
        return merged

    # ===== Validation Methods =====

    def _validate_task_name(self, task_name: str) -> None:
        """
        Validate task name format and ensure it's a supported OAR workflow task.

        Args:
            task_name: Task name to validate

        Raises:
            StateBoxException: If task name is invalid or not supported
        """
        if not task_name or not isinstance(task_name, str):
            raise StateBoxException("Task name must be a non-empty string")

        if not task_name.strip():
            raise StateBoxException("Task name cannot be whitespace only")

        if len(task_name) > 200:
            raise StateBoxException("Task name too long (max 200 characters)")

        if task_name not in SUPPORTED_TASK_NAMES:
            raise StateBoxException(
                f"Unsupported task name: '{task_name}'. "
                f"Must be one of: {', '.join(SUPPORTED_TASK_NAMES)}"
            )

    def _validate_issue_description(self, issue: str) -> None:
        """
        Validate issue description format.

        Args:
            issue: Issue description to validate

        Raises:
            StateBoxException: If issue description is invalid
        """
        if not issue or not isinstance(issue, str):
            raise StateBoxException("Issue description must be a non-empty string")

        if not issue.strip():
            raise StateBoxException("Issue description cannot be whitespace only")

        if len(issue) > 1000:
            raise StateBoxException("Issue description too long (max 1000 characters)")

    # ===== Helper Methods =====

    def update_task(
        self,
        task_name: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """
        Update task status and result.

        If task doesn't exist, creates new task entry.
        Automatically updates started_at/completed_at timestamps.

        Args:
            task_name: Name of the task
            status: New status (must be in VALID_TASK_STATUSES)
            result: CLI command output (AI-readable text)
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            dict: Updated state

        Raises:
            StateBoxException: If status is invalid or task_name is invalid
        """
        # Validate inputs
        self._validate_task_name(task_name)

        if status and status not in VALID_TASK_STATUSES:
            raise StateBoxException(f"Invalid task status: {status}. Must be one of {VALID_TASK_STATUSES}")

        state = self.load()

        # Find existing task or create new
        task = None
        for t in state["tasks"]:
            if t["name"] == task_name:
                task = t
                break

        if not task:
            # Create new task
            task = {
                "name": task_name,
                "status": DEFAULT_TASK_STATUS,
                "started_at": None,
                "completed_at": None,
                "result": None
            }
            state["tasks"].append(task)
            logger.info(f"Created new task: {task_name}")

        # Update task fields
        # Use get_current_timestamp() for consistent format: YYYY-MM-DDTHH:MM:SSZ
        now = get_current_timestamp()

        # Extract timestamps from result text (before status-specific logic to avoid duplication)
        # Use the provided result parameter, or fall back to existing task result if available
        result_to_parse = result if result is not None else task.get("result")
        extracted_start = extract_start_timestamp(result_to_parse) if result_to_parse else None
        extracted_end = extract_end_timestamp(result_to_parse) if result_to_parse else None
        if extracted_start:
            logger.debug(f"Extracted start timestamp from result: {extracted_start}")
        if extracted_end:
            logger.debug(f"Extracted end timestamp from result: {extracted_end}")

        if status:
            old_status = task["status"]
            task["status"] = status

            # Update timestamps based on status transition
            if status == TASK_STATUS_INPROGRESS:
                # Use extracted start timestamp or current time
                task["started_at"] = extracted_start or now
                # Clear completed_at for In Progress tasks
                task["completed_at"] = None
            elif status in [TASK_STATUS_PASS, TASK_STATUS_FAIL]:
                # Use extracted end timestamp or current time
                task["completed_at"] = extracted_end or now

                # If started_at is None, use extracted start or fall back to end/now
                # (handles case where task completed without going through "In Progress")
                if task["started_at"] is None:
                    task["started_at"] = extracted_start or extracted_end or now

            logger.info(f"Updated task '{task_name}' status: {old_status} -> {status}")

        if result is not None:
            # Mask sensitive data before storing
            task["result"] = mask_sensitive_data(result)
            logger.info(f"Updated task '{task_name}' result (sensitive data masked)")

        # Auto-save if enabled
        if auto_save:
            self.save(state, message=f"Update task: {task_name}")

        return state

    def update_metadata(
        self,
        updates: Dict[str, Any],
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """
        Update metadata fields.

        Supports nested updates for advisory_ids and candidate_builds.

        Args:
            updates: Dictionary of metadata fields to update
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            dict: Updated state

        Example:
            statebox.update_metadata({
                "jira_ticket": "ART-12345",
                "advisory_ids": {"rpm": 12345, "rhcos": 12346},
                "candidate_builds": {"x86_64": "4.19.1-x86_64"}
            })
        """
        state = self.load()

        for key, value in updates.items():
            if key in ["advisory_ids", "candidate_builds"] and isinstance(value, dict):
                # Nested dict update
                state["metadata"][key].update(value)
            else:
                state["metadata"][key] = value
            logger.info(f"Updated metadata '{key}': {value}")

        # Auto-save if enabled
        if auto_save:
            self.save(state, message="Update metadata")

        return state

    # ===== Issue Management =====

    def add_issue(
        self,
        issue: str,
        blocker: bool = True,
        related_tasks: Optional[List[str]] = None,
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """
        Add an issue with automatic deduplication.

        Supports both task-specific blockers and general blockers.

        Args:
            issue: Issue description
            blocker: Is this a blocking issue? (default: True)
            related_tasks: List of related task names (None/empty = general issue)
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            dict: Issue entry

        Raises:
            StateBoxException: If task already has unresolved blocker or invalid input
        """
        # Validate inputs
        self._validate_issue_description(issue)

        state = self.load()
        related_tasks = related_tasks or []

        # Rule: Only one unresolved blocker per task allowed
        if blocker and related_tasks:
            for task_name in related_tasks:
                # Check if this task already has an unresolved blocker
                for existing_issue in state.get("issues", []):
                    if (existing_issue.get("blocker", False) and
                        not existing_issue["resolved"] and
                        task_name in existing_issue.get("related_tasks", [])):
                        raise StateBoxException(
                            f"Task '{task_name}' already has unresolved blocker: "
                            f"{existing_issue['issue']}"
                        )

        # Check for duplicate issue description (normalized)
        normalized_issue = issue.strip().lower()
        for issue_entry in state.get("issues", []):
            existing_normalized = issue_entry["issue"].strip().lower()
            if existing_normalized == normalized_issue and not issue_entry["resolved"]:
                logger.info(f"Issue already exists: {issue}")
                return issue_entry

        # Create new issue
        issue_entry = {
            "issue": issue,
            "reported_at": get_current_timestamp(),
            "resolved": False,
            "resolution": None,
            "blocker": blocker,
            "related_tasks": related_tasks
        }

        state["issues"].append(issue_entry)

        issue_type = f"{'blocking' if blocker else 'non-blocking'}"
        if related_tasks:
            issue_type += f" (tasks: {', '.join(related_tasks)})"
        else:
            issue_type += " (general)"

        logger.info(f"Added {issue_type} issue: {issue}")

        if auto_save:
            self.save(state, message=f"Add issue: {issue[:50]}")

        return issue_entry

    def resolve_issue(
        self,
        issue: str,  # Can be partial match
        resolution: str,
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """
        Resolve an issue by description (supports fuzzy matching).

        Args:
            issue: Issue description (can be partial)
            resolution: Resolution description
            auto_save: Automatically save to GitHub (default: True)

        Returns:
            dict: Resolved issue entry

        Raises:
            StateBoxException: If issue not found
        """
        state = self.load()

        # Try exact match first (normalized)
        normalized_input = issue.strip().lower()

        # Collect matches (exact match is always unique due to add_issue deduplication)
        matched_issue = None
        partial_matches = []

        for issue_entry in state.get("issues", []):
            if issue_entry["resolved"]:
                continue

            normalized_existing = issue_entry["issue"].strip().lower()

            # Exact match (always unique - add_issue prevents duplicates)
            if normalized_existing == normalized_input:
                matched_issue = issue_entry
                break

            # Partial match (input is substring of existing)
            if normalized_input in normalized_existing:
                partial_matches.append(issue_entry)

        # If exact match found, use it (no ambiguity)
        if matched_issue:
            pass  # matched_issue already set
        elif partial_matches:
            if len(partial_matches) > 1:
                # Multiple partial matches - ask user to be more specific
                match_list = [m["issue"] for m in partial_matches]
                raise StateBoxException(
                    f"Multiple issues match '{issue}':\n" +
                    "\n".join(f"  - {m}" for m in match_list) +
                    "\nPlease provide more specific text to uniquely identify the issue."
                )
            matched_issue = partial_matches[0]
        else:
            # No matches - show all unresolved issues for user
            unresolved = [e["issue"] for e in state.get("issues", []) if not e["resolved"]]
            raise StateBoxException(
                f"Issue not found: '{issue}'\n"
                f"Unresolved issues: {unresolved}"
            )

        matched_issue["resolved"] = True
        matched_issue["resolution"] = resolution
        matched_issue["resolved_at"] = get_current_timestamp()

        logger.info(f"Resolved issue: {matched_issue['issue']}")

        if auto_save:
            self.save(state, message=f"Resolve issue: {issue[:50]}")

        return matched_issue

    def get_task_blocker(self, task_name: str) -> Optional[Dict[str, Any]]:
        """
        Get unresolved blocking issue for a specific task.

        Args:
            task_name: Name of the task

        Returns:
            dict: Blocking issue entry or None if task not blocked
        """
        state = self.load()

        for issue in state.get("issues", []):
            if (issue.get("blocker", False) and
                not issue["resolved"] and
                task_name in issue.get("related_tasks", [])):
                return issue

        return None

    def get_issues(
        self,
        unresolved_only: bool = False,
        blockers_only: bool = False,
        task_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get issues with optional filtering.

        Args:
            unresolved_only: Only return unresolved issues (default: False)
            blockers_only: Only return blocking issues (default: False)
            task_name: Only return issues related to specific task (default: None)

        Returns:
            list: List of issue dictionaries
        """
        state = self.load()
        issues = state.get("issues", [])

        if unresolved_only:
            issues = [i for i in issues if not i["resolved"]]

        if blockers_only:
            issues = [i for i in issues if i.get("blocker", False)]

        if task_name:
            issues = [i for i in issues if task_name in i.get("related_tasks", [])]

        return issues

    def get_general_blockers(self) -> List[Dict[str, Any]]:
        """
        Get all unresolved general blockers (not task-specific).

        Returns:
            list: List of general blocker issue entries
        """
        state = self.load()

        general_blockers = []
        for issue in state.get("issues", []):
            if (issue.get("blocker", False) and
                not issue["resolved"] and
                not issue.get("related_tasks", [])):  # Empty related_tasks = general
                general_blockers.append(issue)

        return general_blockers

    # ===== Query Methods =====

    def get_task_status(self, task_name: str) -> Optional[str]:
        """
        Get current status of a task.

        Args:
            task_name: Name of the task

        Returns:
            str: Task status or None if task doesn't exist
        """
        state = self.load()
        for task in state["tasks"]:
            if task["name"] == task_name:
                return task["status"]
        return None

    def get_task(self, task_name: str) -> Optional[Dict[str, Any]]:
        """
        Get complete task information.

        Args:
            task_name: Name of the task

        Returns:
            dict: Task dictionary or None if task doesn't exist
        """
        state = self.load()
        for task in state["tasks"]:
            if task["name"] == task_name:
                return task
        return None

    def get_metadata(self, key: Optional[str] = None) -> Any:
        """
        Get metadata value(s).

        Args:
            key: Specific metadata key (None returns all metadata)

        Returns:
            Metadata value or entire metadata dict
        """
        state = self.load()
        if key is None:
            return state["metadata"]
        return state["metadata"].get(key)

    def to_json(self, indent: Optional[int] = None) -> str:
        """
        Convert complete StateBox state to JSON string.

        Returns entire state including metadata, tasks, and issues.

        Args:
            indent: JSON indentation spaces (default: None for compact)

        Returns:
            JSON string representation of complete state
        """
        import json
        state = self.load()
        return json.dumps(state, indent=indent)

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        # Cleanup if needed
        pass