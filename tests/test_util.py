import unittest
import os
import logging
import time
from unittest.mock import patch
from oar.core.util import is_payload_metadata_url_accessible, get_elliott_env


def setup_utc_logging(level=logging.DEBUG):
    """
    Configure logging to use UTC timestamps for test execution.

    Args:
        level: Logging level (default: logging.DEBUG)
    """
    # Force logging to use UTC time
    logging.Formatter.converter = time.gmtime

    logging.basicConfig(
        format="%(asctime)s: %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        level=level
    )

class TestPayloadMetadataUrlAccessible(unittest.TestCase):

    def test_happy_path(self):
        """Test successful case with Y-stream release version"""
        self.assertFalse(is_payload_metadata_url_accessible("4.19"))
        self.assertTrue(is_payload_metadata_url_accessible("4.18"))

    @patch('oar.core.util.requests.get')
    def test_fail_get_pullspec(self, mock_requests):
        """Test failure to get pullspec from release stream"""
        mock_requests.return_value.ok = False
        mock_requests.return_value.status_code = 404

        self.assertFalse(is_payload_metadata_url_accessible("4.19"))

    @patch('oar.core.util.requests.get')
    @patch('oar.core.util.subprocess.run')
    def test_fail_oc_not_installed(self, mock_subprocess, mock_requests):
        """Test failure when oc client is not installed"""
        mock_requests.return_value.ok = True
        mock_requests.return_value.json.return_value = {'pullSpec': 'test-pullspec'}
        mock_subprocess.side_effect = FileNotFoundError()

        self.assertFalse(is_payload_metadata_url_accessible("4.19"))


class TestGetElliottEnv(unittest.TestCase):

    @patch.dict(os.environ, {'JIRA_USERNAME': 'test_user', 'OTHER_VAR': 'value'}, clear=True)
    def test_happy_path(self):
        """Test successful case when JIRA_USERNAME is set"""
        env = get_elliott_env()

        # Should set JIRA_EMAIL to JIRA_USERNAME
        self.assertEqual(env['JIRA_EMAIL'], 'test_user')
        # Should preserve existing environment variables
        self.assertEqual(env['JIRA_USERNAME'], 'test_user')
        self.assertEqual(env['OTHER_VAR'], 'value')

    @patch.dict(os.environ, {'OTHER_VAR': 'value'}, clear=True)
    def test_missing_jira_username(self):
        """Test failure when JIRA_USERNAME is not set"""
        with self.assertRaises(RuntimeError) as context:
            get_elliott_env()

        self.assertIn('JIRA_USERNAME', str(context.exception))

    @patch.dict(os.environ, {'JIRA_USERNAME': 'user@example.com', 'JIRA_EMAIL': 'old@example.com'}, clear=True)
    def test_preserve_existing_jira_email(self):
        """Test that existing JIRA_EMAIL is preserved and not overwritten"""
        env = get_elliott_env()

        # Should preserve existing JIRA_EMAIL and not overwrite with JIRA_USERNAME
        self.assertEqual(env['JIRA_EMAIL'], 'old@example.com')
        self.assertEqual(env['JIRA_USERNAME'], 'user@example.com')


if __name__ == '__main__':
    unittest.main()
