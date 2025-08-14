import unittest
from unittest.mock import patch
from oar.core.util import is_payload_metadata_url_accessible

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

if __name__ == '__main__':
    unittest.main()
