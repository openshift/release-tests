import json
import unittest
from unittest.mock import MagicMock, patch

from oar.image_consistency_check.payload import Payload, PayloadImage


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

    def test_extract_images(self):
        """Test that images are extracted and images that match the skipped images regex are filtered out."""
        images = self.payload._extract_images(self.test_payload_data)
        self.assertEqual(len(images), 3)
        self.assertEqual(images[0].name, "aaa")
        self.assertEqual(images[0].pullspec, "from-name-aaa")
        self.assertEqual(images[1].name, "bbb")
        self.assertEqual(images[1].pullspec, "from-name-bbb")
        self.assertEqual(images[2].name, "ccc")
        self.assertEqual(images[2].pullspec, "from-name-ccc")

    @patch('oar.image_consistency_check.payload.subprocess.run')
    def test_get_images(self, mock_run):
        """Test that get_images fetches and extracts images correctly."""
        mock_run.return_value = MagicMock(stdout=json.dumps(self.test_payload_data))
        images = self.payload.get_images()
        self.assertEqual(len(images), 3)
        self.assertEqual(images[0].name, "aaa")
        self.assertEqual(images[0].pullspec, "from-name-aaa")
        self.assertEqual(images[1].name, "bbb")
        self.assertEqual(images[1].pullspec, "from-name-bbb")
        self.assertEqual(images[2].name, "ccc")
        self.assertEqual(images[2].pullspec, "from-name-ccc")
        self.assertEqual(mock_run.call_count, 1)

    def test_get_images_real(self):
        """Test get_images with a real payload from quay.io."""
        images = self.payload.get_images()
        self.assertEqual(len(images), 188)
        for image in images:
            self.assertIsInstance(image, PayloadImage)
            self.assertIsInstance(image.name, str)
            self.assertRegex(image.pullspec, r"^quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:[a-f0-9]{64}$")

    def test_is_skipped_image(self):
        """Test that _is_skipped_image correctly identifies images to skip."""
        # Images that should be skipped
        skipped_images = [
            "machine-os-content",
            "rhel-coreos",
            "rhel-coreos-8",
            "rhel-coreos-9",
            "rhel-coreos-extensions",
            "rhel-coreos-8-extensions",
            "rhel-coreos-9-extensions",
        ]
        for image in skipped_images:
            with self.subTest(image=image):
                self.assertTrue(self.payload._is_skipped_image(image), f"{image} should be skipped")

        # Images that should NOT be skipped
        not_skipped_images = [
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
        for image in not_skipped_images:
            with self.subTest(image=image):
                self.assertFalse(self.payload._is_skipped_image(image), f"{image} should NOT be skipped")
