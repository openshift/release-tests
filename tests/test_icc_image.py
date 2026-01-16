import json
import unittest
from unittest.mock import patch, MagicMock

from oar.image_consistency_check.image import ImageMetadata


class TestImageMetadata(unittest.TestCase):

    def _mock_subprocess_result(self, metadata_dict):
        """Helper to create a mock subprocess result with the given metadata."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(metadata_dict)
        return mock_result

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_identifier_empty_identifiers(self, mock_run):
        """Test that empty identifiers return False."""
        empty_metadata = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'vcs-ref': ''}}}
        }
        mock_run.return_value = self._mock_subprocess_result(empty_metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertFalse(image1.has_same_identifier(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_identifier_same_listdigest(self, mock_run):
        """Test that same listDigest returns True."""
        metadata = {
            'digest': '',
            'listDigest': 'sha256:abc123',
            'config': {'config': {'Labels': {'vcs-ref': ''}}}
        }
        mock_run.return_value = self._mock_subprocess_result(metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertTrue(image1.has_same_identifier(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_identifier_same_digest(self, mock_run):
        """Test that same digest returns True."""
        metadata = {
            'digest': 'sha256:def456',
            'listDigest': '',
            'config': {'config': {'Labels': {'vcs-ref': ''}}}
        }
        mock_run.return_value = self._mock_subprocess_result(metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertTrue(image1.has_same_identifier(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_identifier_same_vcs_ref(self, mock_run):
        """Test that same vcs-ref returns True."""
        metadata = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'vcs-ref': 'commit-abc123'}}}
        }
        mock_run.return_value = self._mock_subprocess_result(metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertTrue(image1.has_same_identifier(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_identifier_different_identifiers(self, mock_run):
        """Test that different identifiers return False."""
        metadata1 = {
            'digest': 'sha256:abc123',
            'listDigest': 'sha256:list1',
            'config': {'config': {'Labels': {'vcs-ref': 'commit1'}}}
        }
        metadata2 = {
            'digest': 'sha256:def456',
            'listDigest': 'sha256:list2',
            'config': {'config': {'Labels': {'vcs-ref': 'commit2'}}}
        }

        mock_run.side_effect = [
            self._mock_subprocess_result(metadata1),
            self._mock_subprocess_result(metadata2)
        ]

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertFalse(image1.has_same_identifier(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_name_empty_names(self, mock_run):
        """Test that empty names return False."""
        metadata = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'name': ''}}}
        }
        mock_run.return_value = self._mock_subprocess_result(metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertFalse(image1.has_same_name(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_name_same_name(self, mock_run):
        """Test that same names return True."""
        metadata = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'name': 'openshift/ose-cli'}}}
        }
        mock_run.return_value = self._mock_subprocess_result(metadata)

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertTrue(image1.has_same_name(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_has_same_name_different_names(self, mock_run):
        """Test that different names return False."""
        metadata1 = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'name': 'openshift/ose-cli'}}}
        }
        metadata2 = {
            'digest': '',
            'listDigest': '',
            'config': {'config': {'Labels': {'name': 'openshift/ose-installer'}}}
        }

        mock_run.side_effect = [
            self._mock_subprocess_result(metadata1),
            self._mock_subprocess_result(metadata2)
        ]

        image1 = ImageMetadata("quay.io/test/image1:latest")
        image2 = ImageMetadata("quay.io/test/image2:latest")

        self.assertFalse(image1.has_same_name(image2))

    @patch('oar.image_consistency_check.image.subprocess.run')
    def test_all_attributes_populated(self, mock_run):
        """Test that all attributes are correctly populated from metadata."""
        full_metadata = {
            'digest': 'sha256:abcdef123456',
            'listDigest': 'sha256:listdigest789',
            'config': {
                'config': {
                    'Labels': {
                        'io.openshift.build.commit.id': 'commit-id-abc123',
                        'vcs-ref': 'vcs-ref-def456',
                        'name': 'openshift/ose-cli',
                        'version': 'v4.16.0',
                        'release': '202401151200.p0'
                    }
                }
            }
        }
        mock_run.return_value = self._mock_subprocess_result(full_metadata)

        image = ImageMetadata("quay.io/openshift-release-dev/ocp-v4.0-art-dev:ose-cli")

        self.assertEqual(image.pull_spec, "quay.io/openshift-release-dev/ocp-v4.0-art-dev:ose-cli")
        self.assertEqual(image.digest, "sha256:abcdef123456")
        self.assertEqual(image.listdigest, "sha256:listdigest789")
        self.assertEqual(image.build_commit_id, "commit-id-abc123")
        self.assertEqual(image.vcs_ref, "vcs-ref-def456")
        self.assertEqual(image.name, "openshift/ose-cli")
        self.assertEqual(image.version, "v4.16.0")
        self.assertEqual(image.release, "202401151200.p0")
        self.assertEqual(image.tag, "v4.16.0-202401151200.p0")
        self.assertEqual(image.labels, full_metadata['config']['config']['Labels'])

    def test_image_metadata_real(self):
        """Test ImageMetadata with a real component image from quay.io."""
        image = ImageMetadata("quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:da81b9e0cd2c901842ae4cca4ba57e21822ba5fcf1905464525180777bac3f12")

        self.assertEqual(image.digest, "sha256:da81b9e0cd2c901842ae4cca4ba57e21822ba5fcf1905464525180777bac3f12")
        self.assertEqual(image.listdigest, "")
        self.assertEqual(image.name, "openshift/ose-agent-installer-api-server-rhel9")
        self.assertEqual(image.version, "v4.16.0")
        self.assertEqual(image.release, "202512191314.p2.g5c16119.assembly.stream.el9")
        self.assertEqual(image.vcs_ref, "bfa326dbead1fbab80b2ece9f795bc4caec4b4a9")
        self.assertEqual(image.build_commit_id, "5c16119aeedc4c30e960a59ca91bbfe704879ad8")
        self.assertEqual(image.tag, "v4.16.0-202512191314.p2.g5c16119.assembly.stream.el9")
