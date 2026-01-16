import os
import unittest
from unittest.mock import patch, MagicMock

from oar.image_consistency_check.shipment import Shipment


class TestImageConsistencyCheckShipment(unittest.TestCase):

    @patch.dict('os.environ', {'GITLAB_TOKEN': ''}, clear=True)
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_gitlab_token_missing(self, mock_gitlab):
        """Test that missing GITLAB_TOKEN raises ValueError."""
        with self.assertRaises(ValueError) as context:
            Shipment(123)
        self.assertIn("GITLAB_TOKEN", str(context.exception))

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_gitlab_token_present(self, mock_gitlab):
        """Test that GITLAB_TOKEN is correctly retrieved."""
        shipment = Shipment(123)
        self.assertEqual(shipment._get_gitlab_token(), 'test-token')

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_image_pullspecs_empty_shipment_data(self, mock_gitlab):
        """Test that empty shipment data returns empty list."""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.changes.return_value = {'changes': []}
        mock_project.mergerequests.get.return_value = mock_mr
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(pullspecs, [])

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_image_pullspecs_with_components(self, mock_gitlab):
        """Test that pullspecs are correctly extracted from shipment components."""
        mock_file = MagicMock()
        mock_file.decode.return_value.decode.return_value = """
shipment:
  snapshot:
    spec:
      components:
        - name: component1
          containerImage: quay.io/openshift/image1@sha256:abc123
        - name: component2
          containerImage: quay.io/openshift/image2@sha256:def456
        - name: component3
          containerImage: quay.io/openshift/image3@sha256:ghi789
"""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.source_branch = 'feature-branch'
        mock_mr.changes.return_value = {
            'changes': [{'new_path': 'shipments/4.16/shipment.yaml'}]
        }
        mock_project.mergerequests.get.return_value = mock_mr
        mock_project.files.get.return_value = mock_file
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(len(pullspecs), 3)
        self.assertEqual(pullspecs[0], 'quay.io/openshift/image1@sha256:abc123')
        self.assertEqual(pullspecs[1], 'quay.io/openshift/image2@sha256:def456')
        self.assertEqual(pullspecs[2], 'quay.io/openshift/image3@sha256:ghi789')

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_image_pullspecs_skips_non_yaml_files(self, mock_gitlab):
        """Test that non-YAML files are skipped."""
        mock_file = MagicMock()
        mock_file.decode.return_value.decode.return_value = """
shipment:
  snapshot:
    spec:
      components:
        - name: component1
          containerImage: quay.io/openshift/image1@sha256:abc123
"""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.source_branch = 'feature-branch'
        mock_mr.changes.return_value = {
            'changes': [
                {'new_path': 'README.md'},
                {'new_path': 'shipments/4.16/shipment.yaml'}
            ]
        }
        mock_project.mergerequests.get.return_value = mock_mr
        mock_project.files.get.return_value = mock_file
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(len(pullspecs), 1)
        mock_project.files.get.assert_called_once()

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_image_pullspecs_no_components(self, mock_gitlab):
        """Test that shipment with no components returns empty list."""
        mock_file = MagicMock()
        mock_file.decode.return_value.decode.return_value = """
shipment:
  snapshot:
    spec:
      components: []
"""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.source_branch = 'feature-branch'
        mock_mr.changes.return_value = {
            'changes': [{'new_path': 'shipments/4.16/shipment.yaml'}]
        }
        mock_project.mergerequests.get.return_value = mock_mr
        mock_project.files.get.return_value = mock_file
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(pullspecs, [])

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_image_pullspecs_multiple_yaml_files(self, mock_gitlab):
        """Test that pullspecs are collected from multiple YAML files."""
        mock_file1 = MagicMock()
        mock_file1.decode.return_value.decode.return_value = """
shipment:
  snapshot:
    spec:
      components:
        - name: component1
          containerImage: quay.io/openshift/image1@sha256:abc123
"""
        mock_file2 = MagicMock()
        mock_file2.decode.return_value.decode.return_value = """
shipment:
  snapshot:
    spec:
      components:
        - name: component2
          containerImage: quay.io/openshift/image2@sha256:def456
"""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.source_branch = 'feature-branch'
        mock_mr.changes.return_value = {
            'changes': [
                {'new_path': 'shipments/4.16/shipment1.yaml'},
                {'new_path': 'shipments/4.16/shipment2.yaml'}
            ]
        }
        mock_project.mergerequests.get.return_value = mock_mr
        mock_project.files.get.side_effect = [mock_file1, mock_file2]
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(len(pullspecs), 2)
        self.assertEqual(pullspecs[0], 'quay.io/openshift/image1@sha256:abc123')
        self.assertEqual(pullspecs[1], 'quay.io/openshift/image2@sha256:def456')

    @unittest.skipUnless(os.getenv('GITLAB_TOKEN'), "GITLAB_TOKEN not set - skipping real GitLab test")
    def test_get_image_pullspecs_real(self):
        """Test get_image_pullspecs with a real MR from GitLab."""
        shipment = Shipment(311)
        pullspecs = shipment.get_image_pullspecs()

        self.assertEqual(len(pullspecs), 274)
        for ps in pullspecs:
            self.assertRegex(ps, r"^quay.io/redhat-user-workloads/ocp-art-tenant/.*@sha256:[a-f0-9]{64}$")
