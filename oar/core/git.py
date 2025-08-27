import logging
import os
import shutil
import tempfile
from typing import Optional
from urllib.parse import urlparse, urlunparse

import git
from git import Repo
from git.exc import GitCommandError

from oar.core.const import *
from oar.core.exceptions import GitException

logger = logging.getLogger(__name__)


class GitHelper:
    """
    Helper class for Git operations including:
    - Repository cloning and checkout
    - Branch operations
    - Commit and push
    - Merge request creation
    
    Used primarily for automated Git operations in the release process.
    """

    def __init__(self):
        self._temp_dir = None
        self._repo = None
        self._check_git_config()

    def _sanitize_url(self, url: str) -> str:
        """
        Sanitize URL by removing authentication credentials to prevent logging sensitive information
        
        Args:
            url: URL that may contain authentication credentials
            
        Returns:
            str: Sanitized URL without authentication credentials
        """
        try:
            parsed = urlparse(url)
            if parsed.username or parsed.password:
                # Remove username and password from netloc
                netloc = parsed.hostname
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                # Reconstruct URL without credentials
                sanitized = urlunparse((
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
                return sanitized
            return url
        except Exception:
            # If URL parsing fails, return original URL to avoid breaking functionality
            return url

    def _check_git_config(self):
        """Check if required git config (user.name and user.email) exists"""
        try:
            config = git.GitConfigParser()
            if not config.has_option("user", "name") or not config.has_option("user", "email"):
                logger.warning("Missing required git config (user.name and/or user.email)")
                logger.info("Initializing minimal git config with default values")
                config.set_value("user", "name", "OAR Automation")
                config.set_value("user", "email", "ert-release-bot@redhat.com")
        except Exception as e:
            logger.warning(f"Failed to check/set git config: {str(e)}")

    def configure_remotes(self, remote_name: str, remote_url: str) -> None:
        """
        Configure additional remotes for the repository if needed
        
        Args:
            remote_name: Name of the remote to add
            remote_url: URL of the remote to add
            
        Raises:
            GitException: If remote configuration fails
        """
        try:
            # Get list of existing remote names
            existing_remotes = [remote.name for remote in self._repo.remotes]
            
            # Only add if remote doesn't already exist
            if remote_name not in existing_remotes:
                self._repo.create_remote(remote_name, remote_url)
                sanitized_url = self._sanitize_url(remote_url)
                logger.info(f"Added remote {remote_name}: {sanitized_url}")
            else:
                # Update URL if remote already exists
                remote = self._repo.remote(remote_name)
                remote.set_url(remote_url)
                sanitized_url = self._sanitize_url(remote_url)
                logger.info(f"Updated remote {remote_name} URL to: {sanitized_url}")
        except Exception as e:
            logger.warning(f"Failed to configure additional remotes: {str(e)}")
            raise GitException(f"Remote configuration failed: {str(e)}") from e

    def checkout_repo(self, repo_url: str = "https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data.git", branch: str = "main", temp_parent_dir: str = "/tmp") -> str:
        """
        Clone repository and checkout specified branch in a temp directory
        
        Args:
            repo_url: Git repository URL to clone (default: "https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data.git")
            branch: Branch to checkout (default: "main")
            temp_parent_dir: Parent directory for temp dir (default: "/tmp")
            
        Returns:
            str: Path to the cloned repository
            
        Raises:
            GitException: If clone or checkout fails
        """

        try:
            # Create temp directory under specified parent
            self._temp_dir = tempfile.mkdtemp(prefix="oar-git-", dir=temp_parent_dir)
            logger.info(f"Cloning {repo_url} to {self._temp_dir}")
            
            # Clone repo
            self._repo = Repo.clone_from(repo_url, self._temp_dir)
            # Checkout branch
            self._repo.git.checkout(branch)
            logger.info(f"Checked out branch {branch}")
            
            return self._temp_dir
        except GitCommandError as gce:
            raise GitException(f"Failed to clone repository: {str(gce)}") from gce

    def create_branch(self, branch_name: str) -> None:
        """
        Create and checkout new branch from current branch
        
        Args:
            branch_name: Name of new branch to create
            
        Raises:
            GitException: If branch creation fails
        """
        if not self._repo:
            raise GitException("Repository not initialized - call checkout_repo() first")
            
        try:
            # Create and checkout new branch from current branch
            self._repo.git.checkout("-b", branch_name)
            logger.info(f"Created and checked out branch {branch_name} from current branch")
        except GitCommandError as gce:
            raise GitException(f"Failed to create branch: {str(gce)}") from gce

    def commit_changes(self, message: str, files: list = None) -> None:
        """
        Commit changes to the current branch
        
        Args:
            message: Commit message
            files: Specific files to commit (None for all changes)
            
        Raises:
            GitException: If commit fails
        """
        if not self._repo:
            raise GitException("Repository not initialized - call checkout_repo() first")
            
        try:
            # Stage changes
            if files:
                self._repo.git.add(files)
            else:
                self._repo.git.add("--all")
                
            # Commit changes
            self._repo.index.commit(message)
            logger.info(f"Committed changes with message: {message}")
        except GitCommandError as gce:
            raise GitException(f"Failed to commit changes: {str(gce)}") from gce

    def push_changes(self, remote: str = "origin", branch: str = None, force: bool = False) -> None:
        """
        Push changes to remote repository
        
        Args:
            remote: Remote name (default: "origin")
            branch: Branch to push (None for current branch)
            force: Whether to force push (default: False)
            
        Raises:
            GitException: If push fails
        """
        if not self._repo:
            raise GitException("Repository not initialized - call checkout_repo() first")
            
        try:
            # Get current branch if none specified
            if not branch:
                branch = self._repo.active_branch.name
                
            # Push changes
            push_args = [remote, branch]
            if force:
                push_args.insert(1, "--force")
                
            self._repo.git.push(*push_args)
            logger.info(f"Pushed changes to {remote}/{branch}")
        except GitCommandError as gce:
            raise GitException(f"Failed to push changes: {str(gce)}") from gce

    def show_status(self) -> str:
        """
        Show the current git status including:
        - Current branch
        - Changes to be committed
        - Changes not staged for commit
        - Untracked files
        
        Returns:
            str: Git status output
            
        Raises:
            GitException: If status command fails
        """
        if not self._repo:
            raise GitException("Repository not initialized - call checkout_repo() first")
            
        try:
            status_output = self._repo.git.status()
            logger.info("Git status retrieved successfully")
            return status_output
        except GitCommandError as gce:
            raise GitException(f"Failed to get git status: {str(gce)}") from gce

    def cleanup(self) -> None:
        """Clean up temporary directory if it exists"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
                logger.info(f"Cleaned up temp directory: {self._temp_dir}")
                self._temp_dir = None  # Prevent double cleanup
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {str(e)}")

    def __del__(self) -> None:
        """Destructor - automatically clean up when object is garbage collected"""
        self.cleanup()

