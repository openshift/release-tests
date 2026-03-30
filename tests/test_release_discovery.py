"""
Tests for release_discovery module
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from oar.core.exceptions import ReleaseDiscoveryException
from oar.core.release_discovery import ReleaseDiscovery


class TestReleaseDiscovery(unittest.TestCase):
    """Test ReleaseDiscovery class"""

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    def test_init_with_token(self, mock_github):
        """Test initialization with GitHub token"""
        # Mocks
        mock_github_instance = mock_github.return_value
        mock_repo = MagicMock()
        mock_github_instance.get_repo.return_value = mock_repo

        # Create class Instance
        discovery = ReleaseDiscovery()

        # Assertions
        self.assertIsNotNone(discovery)
        mock_github.assert_called_once()
        mock_github_instance.get_repo.assert_called_once_with("openshift/release-tests")
        self.assertEqual(discovery.repo, mock_repo)

    @patch.dict('os.environ', {}, clear=True)
    def test_init_without_token_raises_exception(self):
        """Test initialization without token raises exception"""
        with self.assertRaises(ReleaseDiscoveryException) as context:
            ReleaseDiscovery()
        self.assertIn("GitHub token not found", str(context.exception))

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    def test_get_supported_ystreams(self, mock_github):
        """Test getting supported y-streams"""
        # Mock GitHub API response
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        # Mock directory contents with proper string attributes
        mock_item1 = MagicMock()
        mock_item1.type = "dir"
        mock_item1.name = "4.20"

        mock_item2 = MagicMock()
        mock_item2.type = "dir"
        mock_item2.name = "4.21"

        mock_item3 = MagicMock()
        mock_item3.type = "dir"
        mock_item3.name = "4.19"

        mock_item4 = MagicMock()
        mock_item4.type = "file"
        mock_item4.name = "test.txt"

        mock_repo.get_contents.return_value = [mock_item1, mock_item2, mock_item3, mock_item4]

        discovery = ReleaseDiscovery()
        y_streams = discovery.get_supported_ystreams()

        # Should return sorted directory names matching pattern
        self.assertEqual(y_streams, ["4.19", "4.20", "4.21"])

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    @patch('oar.core.release_discovery.yaml')
    def test_get_latest_release_for_ystream(self, mock_yaml, mock_github):
        """Test getting latest release for y-stream"""
        # Mock GitHub API response
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        # Mock GitHub file object (yaml.safe_load is mocked, so content doesn't matter)
        mock_file = MagicMock()
        mock_repo.get_contents.return_value = mock_file

        # Mock YAML parsing
        mock_yaml.safe_load.return_value = {
            "releases": {
                "4.20.15": {},
                "4.20.17": {},
                "4.20.16": {}
            }
        }

        discovery = ReleaseDiscovery()
        latest = discovery.get_latest_release_for_ystream("4.20")

        # Should return the highest version
        self.assertEqual(latest, "4.20.17")

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    @patch('oar.core.release_discovery.yaml')
    def test_get_active_releases(self, mock_yaml, mock_github):
        """Test getting active releases"""
        # Mock GitHub API
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        # Mock y-streams discovery
        mock_item1 = MagicMock()
        mock_item1.type = "dir"
        mock_item1.name = "4.20"

        mock_item2 = MagicMock()
        mock_item2.type = "dir"
        mock_item2.name = "4.21"

        # Mock get_contents to handle two types of GitHub API calls:
        # 1. get_contents("_releases", ref="z-stream") -> returns list of directories (y-streams)
        # 2. get_contents("_releases/4.20/4.20.z.yaml", ref="z-stream") -> returns file object
        def mock_get_contents(path, ref):
            # Determine return value based on path only
            if path == "_releases":
                # Return list of y-stream directories
                return [mock_item1, mock_item2]
            else:
                # Return tracking file object (yaml.safe_load is mocked, so content doesn't matter)
                return MagicMock()

        mock_repo.get_contents.side_effect = mock_get_contents

        # Mock YAML parsing - return different releases for each y-stream
        mock_yaml.safe_load.side_effect = [
            {"releases": {"4.20.17": {}}},  # First call: 4.20.z.yaml
            {"releases": {"4.21.8": {}}}     # Second call: 4.21.z.yaml
        ]

        # Mock ConfigStore factory - one release is active, one is past active window
        def mock_configstore_factory(release):
            cs_mock = MagicMock()
            if release == "4.20.17":
                # Release date: tomorrow (active)
                tomorrow = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%b-%d")
                cs_mock.get_release_date.return_value = tomorrow
            else:
                # Release date: 5 days ago (past window)
                past = (datetime.now().date() - timedelta(days=5)).strftime("%Y-%b-%d")
                cs_mock.get_release_date.return_value = past
            return cs_mock

        # Create ReleaseDiscovery with mock factory
        discovery = ReleaseDiscovery(configstore_factory=mock_configstore_factory)
        active_releases = discovery.get_active_releases(keep_days_after_release=1)

        # Only 4.20.17 should be active (tomorrow's date)
        self.assertEqual(active_releases, ["4.20.17"])


if __name__ == '__main__':
    unittest.main()
