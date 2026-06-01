"""
Tests for release_discovery module
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from oar.core.const import ENV_VAR_GITHUB_APP_WRITER_ID, ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY
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

WRITER_ENV = {
    ENV_VAR_GITHUB_APP_WRITER_ID: '123',
    ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY: '/fake/writer.pem',
}


def setup_graphql_mock(mock_github_instance):
    """
    Helper to setup GraphQL mock response.

    Args:
        mock_github_instance: Mocked Github instance

    Returns:
        Tuple of (mock_requester)
    """
    mock_requester = MagicMock()
    mock_github_instance._Github__requester = mock_requester
    mock_requester.requestJsonAndCheck.return_value = ({}, MOCK_GRAPHQL_RESPONSE)

    return mock_requester


class TestReleaseDiscovery(unittest.TestCase):
    """Test ReleaseDiscovery class"""

    @patch.dict('os.environ', WRITER_ENV)
    @patch('oar.core.release_discovery.GitHubApp')
    def test_init_with_writer_app(self, mock_github_app):
        """Test initialization with GitHub App Writer credentials"""
        mock_github = MagicMock()
        mock_github_app.return_value.client_for_repo.return_value = mock_github

        discovery = ReleaseDiscovery()

        self.assertIsNotNone(discovery)
        mock_github_app.return_value.client_for_repo.assert_called_once_with(
            "openshift", "release-tests"
        )
        self.assertEqual(discovery._github, mock_github)

    @patch.dict('os.environ', {}, clear=True)
    def test_init_without_credentials_raises_exception(self):
        """Test initialization without credentials raises exception"""
        with self.assertRaises(ReleaseDiscoveryException) as context:
            ReleaseDiscovery()
        self.assertIn("must be set", str(context.exception))

    @patch.dict('os.environ', WRITER_ENV)
    @patch('oar.core.release_discovery.GitHubApp')
    def test_get_supported_ystreams(self, mock_github_app):
        """Test getting supported y-streams using GraphQL"""
        mock_github = MagicMock()
        mock_github_app.return_value.client_for_repo.return_value = mock_github
        setup_graphql_mock(mock_github)

        discovery = ReleaseDiscovery()
        y_streams = discovery.get_supported_ystreams()

        self.assertEqual(y_streams, ["4.19", "4.20", "4.21"])

    @patch.dict('os.environ', WRITER_ENV)
    @patch('oar.core.release_discovery.GitHubApp')
    def test_get_latest_release_for_ystream(self, mock_github_app):
        """Test getting latest release for y-stream using GraphQL"""
        mock_github = MagicMock()
        mock_github_app.return_value.client_for_repo.return_value = mock_github
        setup_graphql_mock(mock_github)

        discovery = ReleaseDiscovery()
        latest = discovery.get_latest_release_for_ystream("4.20")

        self.assertEqual(latest, "4.20.17")

    @patch.dict('os.environ', WRITER_ENV)
    @patch('oar.core.release_discovery.GitHubApp')
    def test_get_active_releases(self, mock_github_app):
        """Test getting active releases using GraphQL"""
        mock_github = MagicMock()
        mock_github_app.return_value.client_for_repo.return_value = mock_github
        mock_requester = setup_graphql_mock(mock_github)

        tomorrow = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%b-%d")
        past = (datetime.now().date() - timedelta(days=5)).strftime("%Y-%b-%d")

        statebox_response = {
            "data": {
                "repository": {
                    "release_0": {
                        "text": f"metadata:\n  release_date: {past}\n"
                    },
                    "release_1": {
                        "text": f"metadata:\n  release_date: {tomorrow}\n"
                    },
                    "release_2": {
                        "text": f"metadata:\n  release_date: {past}\n"
                    }
                }
            }
        }

        mock_requester.requestJsonAndCheck.side_effect = [
            ({}, MOCK_GRAPHQL_RESPONSE),
            ({}, statebox_response),
        ]

        discovery = ReleaseDiscovery()
        active_releases = discovery.get_active_releases()

        self.assertEqual(active_releases, ["4.20.17"])


if __name__ == '__main__':
    unittest.main()
