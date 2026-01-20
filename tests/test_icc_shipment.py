import os
import unittest
from unittest.mock import patch, MagicMock

from oar.image_consistency_check.shipment import Shipment, ShipmentComponent


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
    def test_get_components_empty_shipment_data(self, mock_gitlab):
        """Test that empty shipment data returns empty list of shipment components."""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.changes.return_value = {'changes': []}
        mock_project.mergerequests.get.return_value = mock_mr
        mock_gitlab.return_value.projects.get.return_value = mock_project

        shipment = Shipment(123)
        shipment_components = shipment.get_components()

        self.assertEqual(shipment_components, [])

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_components_with_components(self, mock_gitlab):
        """Test that components are correctly extracted from shipment data."""
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
        shipment_components = shipment.get_components()

        self.assertEqual(len(shipment_components), 3)
        self.assertEqual(shipment_components[0].name, 'component1')
        self.assertEqual(shipment_components[0].pullspec, 'quay.io/openshift/image1@sha256:abc123')
        self.assertEqual(shipment_components[1].name, 'component2')
        self.assertEqual(shipment_components[1].pullspec, 'quay.io/openshift/image2@sha256:def456')
        self.assertEqual(shipment_components[2].name, 'component3')
        self.assertEqual(shipment_components[2].pullspec, 'quay.io/openshift/image3@sha256:ghi789')

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_components_skips_non_yaml_files(self, mock_gitlab):
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
        shipment_components = shipment.get_components()

        self.assertEqual(len(shipment_components), 1)
        mock_project.files.get.assert_called_once()

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_components_no_components(self, mock_gitlab):
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
        shipment_components = shipment.get_components()

        self.assertEqual(shipment_components, [])

    @patch.dict('os.environ', {'GITLAB_TOKEN': 'test-token'})
    @patch('oar.image_consistency_check.shipment.Gitlab')
    def test_get_components_multiple_yaml_files(self, mock_gitlab):
        """Test that components are collected from multiple YAML files."""
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
        shipment_components = shipment.get_components()

        self.assertEqual(len(shipment_components), 2)
        self.assertEqual(shipment_components[0].name, 'component1')
        self.assertEqual(shipment_components[0].pullspec, 'quay.io/openshift/image1@sha256:abc123')
        self.assertEqual(shipment_components[1].name, 'component2')
        self.assertEqual(shipment_components[1].pullspec, 'quay.io/openshift/image2@sha256:def456')

    @unittest.skipUnless(os.getenv('GITLAB_TOKEN'), "GITLAB_TOKEN not set - skipping real GitLab test")
    def test_get_components_real(self):
        """Test get_components with a real MR from GitLab."""
        shipment = Shipment(311)
        shipment_components = shipment.get_components()

        self.assertEqual(len(shipment_components), 274)
        for component in shipment_components:
            self.assertIsInstance(component, ShipmentComponent)
            self.assertIsInstance(component.name, str)
            self.assertRegex(component.pullspec, r"^quay.io/redhat-user-workloads/ocp-art-tenant/.*@sha256:[a-f0-9]{64}$")
