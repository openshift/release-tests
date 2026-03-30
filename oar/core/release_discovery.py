"""
Release Discovery Module

Provides auto-discovery of active z-stream releases from GitHub tracking files.

This module uses authenticated GitHub API to avoid rate limits and provides
a central source of truth for supported y-streams and active releases.

Usage:
    from oar.core.release_discovery import ReleaseDiscovery

    # Initialize with GitHub token
    discovery = ReleaseDiscovery()  # Uses GITHUB_TOKEN env var

    # Get all supported y-streams
    y_streams = discovery.get_supported_ystreams()
    # Returns: ["4.12", "4.13", "4.14", ..., "4.21"]

    # Get active releases (within date window)
    active = discovery.get_active_releases(keep_days_after_release=1)
    # Returns: ["4.14.63", "4.18.36", "4.20.17", "4.21.8"]

    # Get latest release for specific y-stream
    latest = discovery.get_latest_release_for_ystream("4.20")
    # Returns: "4.20.17"
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Callable, List, Optional

import yaml
from github import Auth, Github, GithubException
from github.GithubException import UnknownObjectException

from oar.core.configstore import ConfigStore
from oar.core.exceptions import ConfigStoreException, ReleaseDiscoveryException

logger = logging.getLogger(__name__)


class ReleaseDiscovery:
    """
    Discover active z-stream releases from GitHub tracking files.

    Uses authenticated GitHub API to avoid rate limits.
    """

    DEFAULT_REPO = "openshift/release-tests"
    DEFAULT_BRANCH = "z-stream"
    RELEASES_PATH = "_releases"

    def __init__(
        self,
        github_token: Optional[str] = None,
        repo_name: Optional[str] = None,
        branch: Optional[str] = None,
        configstore_factory: Optional[Callable[[str], ConfigStore]] = None
    ):
        """
        Initialize ReleaseDiscovery with authenticated GitHub API.

        Args:
            github_token: GitHub personal access token (default: from GITHUB_TOKEN env)
            repo_name: GitHub repository name (default: "openshift/release-tests")
            branch: Branch name (default: "z-stream")
            configstore_factory: Factory function for ConfigStore instances (default: ConfigStore).
                               Used by MCP server to inject cached instances.

        Raises:
            ReleaseDiscoveryException: If GitHub token is missing
        """
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ReleaseDiscoveryException("GitHub token not found. Set GITHUB_TOKEN environment variable.")

        self.repo_name = repo_name or self.DEFAULT_REPO
        self.branch = branch or self.DEFAULT_BRANCH
        self._configstore_factory = configstore_factory or ConfigStore

        auth = Auth.Token(token)
        self._github = Github(auth=auth)
        self.repo = self._github.get_repo(self.repo_name)

    def get_supported_ystreams(self) -> List[str]:
        """
        Get all supported y-streams by discovering directories in _releases/.

        Returns:
            List of y-stream versions sorted (e.g., ["4.12", "4.13", ..., "4.21"])

        Raises:
            ReleaseDiscoveryException: If GitHub API fails or unexpected error occurs
        """
        try:
            # Get _releases directory contents
            contents = self.repo.get_contents(self.RELEASES_PATH, ref=self.branch)

            # Extract y-stream versions from directory names
            y_streams = []
            pattern = re.compile(r'^4\.\d{1,2}$')

            for item in contents:
                if item.type == "dir" and pattern.match(item.name):
                    y_streams.append(item.name)

            # Sort by version number
            y_streams.sort(key=lambda v: tuple(map(int, v.split('.'))))

            logger.debug(f"Discovered {len(y_streams)} y-streams: {y_streams}")
            return y_streams

        except GithubException as e:
            raise ReleaseDiscoveryException(f"GitHub API error discovering y-streams: {str(e)}") from e
        except Exception as e:
            raise ReleaseDiscoveryException(
                f"Unexpected error discovering y-streams: {type(e).__name__} {str(e)}"
            ) from e

    def get_latest_release_for_ystream(self, y_stream: str) -> Optional[str]:
        """
        Get latest z-stream release for a given y-stream.

        Args:
            y_stream: Y-stream version (e.g., "4.20")

        Returns:
            Latest release version (e.g., "4.20.17") or None if tracking file not found

        Raises:
            ReleaseDiscoveryException: If GitHub API fails, YAML parsing fails, or unexpected error occurs
        """
        tracking_path = f"{self.RELEASES_PATH}/{y_stream}/{y_stream}.z.yaml"

        try:
            # Get tracking file from GitHub
            try:
                file_content = self.repo.get_contents(tracking_path, ref=self.branch)
            except UnknownObjectException:
                logger.debug(f"Tracking file not found for y-stream {y_stream}")
                return None

            # Parse YAML content
            decoded_content = file_content.decoded_content.decode('utf-8')
            tracking_data = yaml.safe_load(decoded_content)

            # Get all releases
            releases = tracking_data.get("releases", {}).keys()

            if not releases:
                logger.debug(f"No releases found for y-stream {y_stream}")
                return None

            # Find latest release
            latest = max(releases, key=lambda v: tuple(map(int, v.split('.'))))

            logger.debug(f"Latest release for {y_stream}: {latest}")
            return latest

        except yaml.YAMLError as e:
            raise ReleaseDiscoveryException(f"Failed to parse tracking file for {y_stream}: {str(e)}") from e
        except GithubException as e:
            raise ReleaseDiscoveryException(f"GitHub API error for {y_stream}: {str(e)}") from e
        except Exception as e:
            raise ReleaseDiscoveryException(
                f"Unexpected error for {y_stream}: {type(e).__name__} {str(e)}"
            ) from e

    def get_active_releases(
        self,
        keep_days_after_release: int = 1
    ) -> List[str]:
        """
        Discover active z-stream releases based on release_date filtering.

        Only the latest release per y-stream is checked.

        Args:
            keep_days_after_release: Number of days after release_date to include (default: 1)

        Returns:
            List of active release versions (e.g., ["4.14.63", "4.18.36", "4.20.17"])

        Raises:
            ReleaseDiscoveryException: If y-stream discovery or release filtering fails
        """
        active_releases = []

        y_streams = self.get_supported_ystreams()

        for y_stream in y_streams:
            latest_release = self.get_latest_release_for_ystream(y_stream)
            if not latest_release:
                continue

            if self._is_release_active(latest_release, keep_days_after_release):
                active_releases.append(latest_release)

        logger.info(f"Discovered {len(active_releases)} active releases: {active_releases}")
        return active_releases

    def _is_release_active(
        self,
        release: str,
        keep_days: int
    ) -> bool:
        """
        Check if release is within date window (release_date + keep_days).

        Args:
            release: Release version (e.g., "4.20.17")
            keep_days: Number of days after release_date to keep visible

        Returns:
            True if release is active, False otherwise
        """
        try:
            # Use factory to create ConfigStore (cached or new instance)
            cs = self._configstore_factory(release)
            release_date_str = cs.get_release_date()

            # Parse date in format: 2026-Mar-25
            release_date = datetime.strptime(release_date_str, "%Y-%b-%d").date()
            today = datetime.now().date()

            is_active = today <= release_date + timedelta(days=keep_days)
            logger.debug(f"Release {release} {'active' if is_active else 'past visibility window'} (release_date: {release_date_str})")
            return is_active

        except ConfigStoreException as e:
            # ConfigStore not ready for this release (build data not available yet)
            logger.debug(f"ConfigStore not available for {release}: {e}")
            return False
