import json
import unittest
from unittest.mock import MagicMock, patch

from oar.image_consistency_check.payload import Payload


class TestPayload(unittest.TestCase):
    def setUp(self):
        self.payload = Payload("quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64")
        self.test_payload_data = {
            "references": {
                "spec": {
                    "tags": [
                        {
                            "name": "aaa",
                            "from": {"name": "from-name-aaa"}
                        },
                        {
                            "name": "bbb",
                            "from": {"name": "from-name-bbb"}
                        },
                        {
                            "name": "ccc",
                            "from": {"name": "from-name-ccc"}
                        },
                        {
                            "name": "machine-os-content",
                            "from": {"name": "from-name-machine-os-content"}
                        },
                        {
                            "name": "rhel-coreos",
                            "from": {"name": "from-name-rhel-coreos"}
                        },
                        {
                            "name": "rhel-coreos-extensions",
                            "from": {"name": "from-name-rhel-coreos-extensions"}
                        }
                    ]
                }
            }
        }

    @patch('oar.image_consistency_check.payload.subprocess.run')
    def test_fetch_payload_data(self, mock_run):
        """Test that payload data is fetched correctly from oc command."""
        mock_run.return_value = MagicMock(stdout=json.dumps(self.test_payload_data))
        payload_data = self.payload._fetch_payload_data()
        self.assertEqual(payload_data, self.test_payload_data)
        self.assertEqual(mock_run.call_count, 1)

    def test_extract_image_pullspecs(self):
        """Test that image pullspecs are extracted and RHCOS images are filtered out."""
        pullspecs = self.payload._extract_image_pullspecs(self.test_payload_data)
        self.assertEqual(len(pullspecs), 3)
        self.assertEqual(pullspecs[0], "from-name-aaa")
        self.assertEqual(pullspecs[1], "from-name-bbb")
        self.assertEqual(pullspecs[2], "from-name-ccc")

    @patch('oar.image_consistency_check.payload.subprocess.run')
    def test_get_image_pullspecs(self, mock_run):
        """Test that get_image_pullspecs fetches and extracts pullspecs correctly."""
        mock_run.return_value = MagicMock(stdout=json.dumps(self.test_payload_data))
        pullspecs = self.payload.get_image_pullspecs()
        self.assertEqual(len(pullspecs), 3)
        self.assertEqual(pullspecs[0], "from-name-aaa")
        self.assertEqual(pullspecs[1], "from-name-bbb")
        self.assertEqual(pullspecs[2], "from-name-ccc")
        self.assertEqual(mock_run.call_count, 1)

    def test_get_image_pullspecs_real(self):
        """Test get_image_pullspecs with a real payload from quay.io."""
        pullspecs = self.payload.get_image_pullspecs()
        self.assertEqual(len(pullspecs), 188)
        for ps in pullspecs:
            self.assertRegex(ps, r"^quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:[a-f0-9]{64}$")

    def test_is_skipped_tag(self):
        """Test that _is_skipped_tag correctly identifies tags to skip."""
        # Tags that should be skipped
        skipped_tags = [
            "machine-os-content",
            "rhel-coreos",
            "rhel-coreos-8",
            "rhel-coreos-9",
            "rhel-coreos-extensions",
            "rhel-coreos-8-extensions",
            "rhel-coreos-9-extensions",
        ]
        for tag in skipped_tags:
            with self.subTest(tag=tag):
                self.assertTrue(self.payload._is_skipped_tag(tag), f"{tag} should be skipped")

        # Tags that should NOT be skipped
        not_skipped_tags = [
            "aaa",
            "bbb",
            "cluster-version-operator",
            "machine-os",  # partial match, not full
            "machine-os-content-extra",  # extra suffix
            "rhel-coreos-abc",  # non-numeric suffix
            "rhel-coreos-",  # trailing dash only
            "my-rhel-coreos",  # prefix before pattern
            "rhel-coreos-extensions-extra",  # extra suffix
        ]
        for tag in not_skipped_tags:
            with self.subTest(tag=tag):
                self.assertFalse(self.payload._is_skipped_tag(tag), f"{tag} should NOT be skipped")
