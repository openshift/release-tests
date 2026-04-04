"""
Tests for release_discovery module
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from oar.core.exceptions import ReleaseDiscoveryException
from oar.core.release_discovery import ReleaseDiscovery


# Common test data for GraphQL mocking
MOCK_GRAPHQL_RESPONSE = {
    "data": {
        "repository": {
            "object": {
                "entries": [
                    {
                        "name": "4.20",
                        "type": "tree",
                        "object": {
                            "entries": [
                                {
                                    "name": "4.20.z.yaml",
                                    "type": "blob",
                                    "object": {
                                        "text": "releases:\n  4.20.15: {}\n  4.20.17: {}\n  4.20.16: {}\n"
                                    }
                                }
                            ]
                        }
                    },
                    {
                        "name": "4.21",
                        "type": "tree",
                        "object": {
                            "entries": [
                                {
                                    "name": "4.21.z.yaml",
                                    "type": "blob",
                                    "object": {
                                        "text": "releases:\n  4.21.8: {}\n"
                                    }
                                }
                            ]
                        }
                    },
                    {
                        "name": "4.19",
                        "type": "tree",
                        "object": {
                            "entries": [
                                {
                                    "name": "4.19.z.yaml",
                                    "type": "blob",
                                    "object": {
                                        "text": "releases:\n  4.19.10: {}\n"
                                    }
                                }
                            ]
                        }
                    },
                    {
                        "name": "test.txt",
                        "type": "blob"
                    }
                ]
            }
        }
    }
}


def setup_graphql_mock(mock_github_instance):
    """
    Helper to setup GraphQL mock response.

    Args:
        mock_github_instance: Mocked Github instance

    Returns:
        Tuple of (mock_repo, mock_requester)
    """
    mock_repo = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo

    mock_requester = MagicMock()
    mock_github_instance._Github__requester = mock_requester
    mock_requester.requestJsonAndCheck.return_value = ({}, MOCK_GRAPHQL_RESPONSE)

    return mock_repo, mock_requester


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
        """Test getting supported y-streams using GraphQL"""
        # Setup GraphQL mock using common test data
        setup_graphql_mock(mock_github.return_value)

        discovery = ReleaseDiscovery()
        y_streams = discovery.get_supported_ystreams()

        # Should return sorted directory names matching pattern
        self.assertEqual(y_streams, ["4.19", "4.20", "4.21"])

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    def test_get_latest_release_for_ystream(self, mock_github):
        """Test getting latest release for y-stream using GraphQL"""
        # Setup GraphQL mock using common test data
        setup_graphql_mock(mock_github.return_value)

        discovery = ReleaseDiscovery()
        latest = discovery.get_latest_release_for_ystream("4.20")

        # Should return the highest version (4.20.17 > 4.20.16 > 4.20.15)
        self.assertEqual(latest, "4.20.17")

    @patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'})
    @patch('oar.core.release_discovery.Github')
    def test_get_active_releases(self, mock_github):
        """Test getting active releases using GraphQL"""
        # Setup GraphQL mock for tracking files
        mock_github_instance = mock_github.return_value
        setup_graphql_mock(mock_github_instance)

        # Mock StateBox GraphQL responses
        mock_requester = mock_github_instance._Github__requester

        # First call: tracking files (already mocked)
        # Second call: StateBox files
        tomorrow = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%b-%d")
        past = (datetime.now().date() - timedelta(days=5)).strftime("%Y-%b-%d")

        statebox_response = {
            "data": {
                "repository": {
                    "release_0": {
                        "text": f"metadata:\n  release_date: {past}\n"  # 4.19.10 - past window
                    },
                    "release_1": {
                        "text": f"metadata:\n  release_date: {tomorrow}\n"  # 4.20.17 - active
                    },
                    "release_2": {
                        "text": f"metadata:\n  release_date: {past}\n"  # 4.21.8 - past window
                    }
                }
            }
        }

        # Mock requestJsonAndCheck to return tracking files first, then StateBox files
        mock_requester.requestJsonAndCheck.side_effect = [
            ({}, MOCK_GRAPHQL_RESPONSE),  # First call: tracking files
            ({}, statebox_response)       # Second call: StateBox files
        ]

        discovery = ReleaseDiscovery()
        active_releases = discovery.get_active_releases()

        # Only 4.20.17 should be active (tomorrow's date)
        self.assertEqual(active_releases, ["4.20.17"])


if __name__ == '__main__':
    unittest.main()
