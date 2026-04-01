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
from typing import List, Optional

import yaml
from github import Auth, Github
from semver import VersionInfo

from oar.core.exceptions import ReleaseDiscoveryException

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
        branch: Optional[str] = None
    ):
        """
        Initialize ReleaseDiscovery with authenticated GitHub API.

        Args:
            github_token: GitHub personal access token (default: from GITHUB_TOKEN env)
            repo_name: GitHub repository name (default: "openshift/release-tests")
            branch: Branch name (default: "z-stream")

        Raises:
            ReleaseDiscoveryException: If GitHub token is missing
        """
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ReleaseDiscoveryException("GitHub token not found. Set GITHUB_TOKEN environment variable.")

        self.repo_name = repo_name or self.DEFAULT_REPO
        self.branch = branch or self.DEFAULT_BRANCH

        # Split repo_name into owner and repository for GraphQL queries
        self.git_repo_owner, self.git_repo_name = self.repo_name.split('/', 1)

        auth = Auth.Token(token)
        self._github = Github(auth=auth)
        self.repo = self._github.get_repo(self.repo_name)

        # Tracking files data (fetched via GraphQL)
        self._tracking_data: Optional[dict] = None
        # StateBox files data (fetched via GraphQL)
        self._statebox_data: Optional[dict] = None

    def get_supported_ystreams(self) -> List[str]:
        """
        Get all supported y-streams by discovering directories in _releases/.

        Uses GraphQL batch fetching (single API call) instead of multiple REST API calls.

        Returns:
            List of y-stream versions sorted (e.g., ["4.12", "4.13", ..., "4.21"])

        Raises:
            ReleaseDiscoveryException: If GraphQL query fails, YAML parsing fails, or unexpected error occurs
        """
        try:
            # Fetch all tracking files via GraphQL
            tracking_data = self._fetch_tracking_files_graphql()

            # Extract y-stream versions from tracking data
            y_streams = list(tracking_data.keys())

            # Sort by version number
            y_streams.sort(key=lambda v: tuple(map(int, v.split('.'))))

            logger.debug(f"Discovered {len(y_streams)} y-streams: {y_streams}")
            return y_streams

        except ReleaseDiscoveryException:
            raise
        except Exception as e:
            raise ReleaseDiscoveryException(
                f"Unexpected error discovering y-streams: {type(e).__name__} {str(e)}"
            ) from e

    def get_latest_release_for_ystream(self, y_stream: str) -> Optional[str]:
        """
        Get latest z-stream release for a given y-stream.

        Uses GraphQL batch-fetched data instead of individual REST API calls.

        Args:
            y_stream: Y-stream version (e.g., "4.20")

        Returns:
            Latest release version (e.g., "4.20.17") or None if tracking file not found

        Raises:
            ReleaseDiscoveryException: If GraphQL query fails, YAML parsing fails, or unexpected error occurs
        """
        try:
            # Fetch all tracking files via GraphQL
            tracking_data_all = self._fetch_tracking_files_graphql()

            # Get tracking data for this y-stream
            tracking_data = tracking_data_all.get(y_stream)

            if not tracking_data:
                logger.debug(f"Tracking file not found for y-stream {y_stream}")
                return None

            # Get all releases
            releases = tracking_data.get("releases", {}).keys()

            if not releases:
                logger.debug(f"No releases found for y-stream {y_stream}")
                return None

            # Find latest release using semver (handles pre-release tags like rc, ec)
            latest = max(releases, key=lambda v: VersionInfo.parse(v))

            logger.debug(f"Latest release for {y_stream}: {latest}")
            return latest

        except ReleaseDiscoveryException:
            raise
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
            ReleaseDiscoveryException: If GraphQL query fails or YAML parsing fails
        """
        # Get all y-streams and their latest releases
        y_streams = self.get_supported_ystreams()

        latest_releases = []
        for y_stream in y_streams:
            latest_release = self.get_latest_release_for_ystream(y_stream)
            if latest_release:
                latest_releases.append(latest_release)

        if not latest_releases:
            logger.info("No latest releases found")
            return []

        # Fetch StateBox files for all latest releases in one GraphQL call
        statebox_data = self._fetch_statebox_files_graphql(latest_releases)

        # Filter releases by date window
        active_releases = []
        for release in latest_releases:
            if self._is_release_active(release, keep_days_after_release, statebox_data.get(release)):
                active_releases.append(release)

        logger.info(f"Discovered {len(active_releases)} active releases: {active_releases}")
        return active_releases

    def _fetch_tracking_files_graphql(self) -> dict:
        """
        Fetch all tracking files using GraphQL in a single API call.

        Uses PyGithub's native GraphQL support to batch-fetch all {y-stream}.z.yaml files.
        Results are stored in self._tracking_data for reuse.

        Query fetches this structure:
            _releases/          # Tree (directory on z-stream branch)
            ├── 4.20/           # Tree (y-stream directory)
            │   └── 4.20.z.yaml # Blob (tracking file with YAML content)
            └── 4.21/           # Tree
                └── 4.21.z.yaml # Blob

        Returns:
            dict: Mapping of y-stream to tracking file YAML content
                  e.g., {"4.20": {"releases": {"4.20.17": {}}}, ...}

        Raises:
            ReleaseDiscoveryException: If fetching or parsing tracking files fails
        """
        # Return data if already fetched
        if self._tracking_data is not None:
            logger.debug("Using already fetched tracking files data")
            return self._tracking_data

        logger.info("Fetching tracking files via GraphQL (batch operation)")

        # GraphQL query to fetch all y-stream directories and their tracking files
        query = """
        query {
          repository(owner: "%s", name: "%s") {
            object(expression: "%s:%s") {
              ... on Tree {
                entries {
                  name
                  type
                  object {
                    ... on Tree {
                      entries {
                        name
                        type
                        object {
                          ... on Blob {
                            text
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """ % (self.git_repo_owner, self.git_repo_name, self.branch, self.RELEASES_PATH)

        try:
            # Use PyGithub's native GraphQL support
            headers, data = self._github._Github__requester.requestJsonAndCheck(
                "POST",
                "/graphql",
                input={"query": query}
            )

            # Parse GraphQL response - extract tracking files from each y-stream directory
            tracking_data = {}
            pattern = re.compile(r'^\d+\.\d{1,2}$')  # Match y-stream format (e.g., "4.20", "4.21", "5.1", etc.)

            # Navigate to repository object in GraphQL response
            repo_object = data.get("data", {}).get("repository", {}).get("object", {})
            if not repo_object:
                raise ReleaseDiscoveryException("GraphQL query returned empty repository object")

            # Process each y-stream directory
            for y_stream_entry in repo_object.get("entries", []):
                y_stream = y_stream_entry.get("name")

                # Skip non-directory entries and invalid y-stream names
                if y_stream_entry.get("type") != "tree" or not pattern.match(y_stream):
                    continue

                # Find and parse the tracking file: {y-stream}.z.yaml
                tracking_file_name = f"{y_stream}.z.yaml"
                for file_entry in y_stream_entry.get("object", {}).get("entries", []):
                    if file_entry.get("name") == tracking_file_name and file_entry.get("type") == "blob":
                        # Parse YAML content
                        yaml_text = file_entry.get("object", {}).get("text", "")
                        if yaml_text:
                            try:
                                tracking_data[y_stream] = yaml.safe_load(yaml_text)
                                logger.debug(f"Parsed tracking file for y-stream {y_stream}")
                            except yaml.YAMLError as e:
                                raise ReleaseDiscoveryException(
                                    f"Failed to parse tracking file for {y_stream}: {e}"
                                ) from e
                        break

            # Store the result for reuse
            self._tracking_data = tracking_data
            logger.info(f"Fetched tracking files for {len(tracking_data)} y-streams via GraphQL")

            return self._tracking_data

        except ReleaseDiscoveryException:
            raise
        except Exception as e:
            raise ReleaseDiscoveryException(f"GraphQL query failed: {type(e).__name__} {str(e)}") from e

    def _fetch_statebox_files_graphql(self, releases: List[str]) -> dict:
        """
        Fetch specific StateBox files using GraphQL in a single API call.

        Uses PyGithub's native GraphQL support to batch-fetch StateBox YAML files.
        Query uses aliases to fetch multiple specific files in one request.

        Query fetches this structure:
            _releases/                # Tree (directory on z-stream branch)
            ├── 4.20/                 # Tree (y-stream directory)
            │   └── statebox/         # Tree (statebox directory)
            │       └── 4.20.17.yaml  # Blob (statebox file with YAML content)
            └── 4.21/                 # Tree
                └── statebox/         # Tree
                    └── 4.21.7.yaml   # Blob

        Args:
            releases: List of release versions (e.g., ["4.20.17", "4.21.7"])

        Returns:
            dict: Mapping of release version to StateBox YAML content
                  e.g., {"4.20.17": {"metadata": {"release_date": "2026-Mar-25"}}, ...}

        Raises:
            ReleaseDiscoveryException: If GraphQL query fails or YAML parsing fails
        """
        # Return data if already fetched
        if self._statebox_data is not None:
            logger.debug("Using already fetched StateBox files data")
            return self._statebox_data

        if not releases:
            self._statebox_data = {}
            return self._statebox_data

        logger.info(f"Fetching StateBox files for {len(releases)} releases via GraphQL")

        # Build GraphQL query fragments for each release
        query_fragments = []
        for i, release in enumerate(releases):
            y_stream = '.'.join(release.split('.')[:2])  # Extract y-stream (e.g., "4.20" from "4.20.17")
            statebox_path = "%s/%s/statebox/%s.yaml" % (self.RELEASES_PATH, y_stream, release)

            # Each fragment queries a specific file using alias to avoid conflicts
            query_fragments.append("""
                release_%d: object(expression: "%s:%s") {
                    ... on Blob {
                        text
                    }
                }
            """ % (i, self.branch, statebox_path))

        # Combine all fragments into single query
        query = """
        query {
          repository(owner: "%s", name: "%s") {
            %s
          }
        }
        """ % (self.git_repo_owner, self.git_repo_name, '\n'.join(query_fragments))

        try:
            # Use PyGithub's native GraphQL support
            headers, data = self._github._Github__requester.requestJsonAndCheck(
                "POST",
                "/graphql",
                input={"query": query}
            )

            # Parse GraphQL response - extract StateBox YAML content
            statebox_data = {}
            repo_object = data.get("data", {}).get("repository", {})

            if not repo_object:
                raise ReleaseDiscoveryException("GraphQL query returned empty repository object")

            # Map each alias back to release version and parse YAML
            for i, release in enumerate(releases):
                alias_key = f"release_{i}"
                blob_object = repo_object.get(alias_key)

                if blob_object and blob_object.get("text"):
                    yaml_text = blob_object.get("text")
                    try:
                        statebox_data[release] = yaml.safe_load(yaml_text)
                        logger.debug(f"Parsed StateBox file for release {release}")
                    except yaml.YAMLError as e:
                        raise ReleaseDiscoveryException(
                            f"Failed to parse StateBox file for {release}: {e}"
                        ) from e
                else:
                    logger.debug(f"StateBox file not found for release {release}")

            # Store the result for reuse
            self._statebox_data = statebox_data
            logger.info(f"Fetched StateBox files for {len(statebox_data)} releases via GraphQL")

            return self._statebox_data

        except ReleaseDiscoveryException:
            raise
        except Exception as e:
            raise ReleaseDiscoveryException(f"GraphQL query failed: {type(e).__name__} {str(e)}") from e

    def _is_release_active(
        self,
        release: str,
        keep_days: int,
        release_data: Optional[dict]
    ) -> bool:
        """
        Check if release is within date window (release_date + keep_days).

        Args:
            release: Release version (e.g., "4.20.17")
            keep_days: Number of days after release_date to keep visible
            release_data: StateBox YAML data for this specific release

        Returns:
            True if release is active, False otherwise
        """
        if not release_data:
            logger.debug(f"StateBox data not available for {release}")
            return False

        try:
            # Extract release_date from StateBox metadata
            release_date_str = release_data.get("metadata", {}).get("release_date")
            if not release_date_str:
                logger.debug(f"release_date not found in StateBox for {release}")
                return False

            # Parse date in format: 2026-Mar-25
            release_date = datetime.strptime(release_date_str, "%Y-%b-%d").date()
            today = datetime.now().date()

            is_active = today <= release_date + timedelta(days=keep_days)
            logger.debug(f"Release {release} {'active' if is_active else 'past visibility window'} (release_date: {release_date_str})")
            return is_active

        except (ValueError, KeyError) as e:
            logger.debug(f"Failed to parse release_date for {release}: {e}")
            return False
