import json
import unittest
from unittest.mock import MagicMock, patch

from oar.image_consistency_check.payload import Payload, PayloadImage


class TestPayload(unittest.TestCase):
    def setUp(self):
        self.payload_url = "quay.io/test/ocp-release:1.2.3-x86_64"
        self.test_payload_data = {
            "metadata": {
                "version": "1.2.3"
            },
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
        payload = Payload(self.payload_url)
        self.assertEqual(payload._payload_data, self.test_payload_data)
        self.assertEqual(payload.version, "1.2.3")
        self.assertEqual(mock_run.call_count, 1)
    
    @patch('oar.image_consistency_check.payload.subprocess.run')
    def test_get_images(self, mock_run):
        """Test that get_images fetches and extracts images correctly."""
        mock_run.return_value = MagicMock(stdout=json.dumps(self.test_payload_data))
        images = Payload(self.payload_url).get_images()
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
        images = Payload("quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64").get_images()
        self.assertEqual(len(images), 188)
        for image in images:
            self.assertIsInstance(image, PayloadImage)
            self.assertIsInstance(image.name, str)
            self.assertRegex(image.pullspec, r"^quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:[a-f0-9]{64}$")

    @patch('oar.image_consistency_check.payload.subprocess.run')
    def test_is_skipped_image(self, mock_run):
        """Test that _is_skipped_image correctly identifies images to skip."""
        mock_run.return_value = MagicMock(stdout=json.dumps(self.test_payload_data))
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
                self.assertTrue(Payload(self.payload_url)._is_skipped_image(image), f"{image} should be skipped")

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
                self.assertFalse(Payload(self.payload_url)._is_skipped_image(image), f"{image} should NOT be skipped")
    
    def test_payload_version(self):
        """Test that the payload version is extracted correctly."""
        payload = Payload("quay.io/openshift-release-dev/ocp-release:4.16.55-x86_64")
        self.assertEqual(payload.version, "4.16.55")

        ec_payload = Payload("quay.io/openshift-release-dev/ocp-release:4.22.0-ec.1-x86_64")
        self.assertEqual(ec_payload.version, "4.22.0-ec.1")

        rc_payload = Payload("quay.io/openshift-release-dev/ocp-release:4.21.0-rc.1-x86_64")
        self.assertEqual(rc_payload.version, "4.21.0-rc.1")

        with self.assertRaises(Exception):
            Payload("quay.io/openshift-release-dev/ocp-release:invalid-x86_64")
