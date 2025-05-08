import unittest
import gitlab
from unittest.mock import MagicMock, patch
import os
from oar.core.shipment import GitLabMergeRequest, ShipmentData

class TestGitLabMergeRequest(unittest.TestCase):
    @patch('os.getenv', return_value="test-token")
    @patch('gitlab.Gitlab')
    def setUp(self, mock_gitlab, mock_getenv):
        self.mock_gl = MagicMock()
        self.mock_project = MagicMock()
        self.mock_mr = MagicMock()
        self.mock_file = MagicMock()
        self.mock_file.decode.return_value = "test content"  # Mock decode() to return string
        
        mock_gitlab.return_value = self.mock_gl
        self.mock_gl.projects.get.return_value = self.mock_project
        
        # Setup both direct get and list fallback scenarios
        self.mock_project.mergerequests.get.side_effect = [
            self.mock_mr,  # First call succeeds
            gitlab.exceptions.GitlabGetError("Not found")  # Second call fails
        ]
        self.mock_project.mergerequests.list.return_value = [self.mock_mr]
        self.mock_mr.files.get.return_value = self.mock_file
        
        self.client = GitLabMergeRequest(
            "https://gitlab.cee.redhat.com",
            "hybrid-platforms/art/ocp-shipment-data", 
            123,
            "test-token"
        )

    def test_init(self):
        self.assertEqual(self.client.gitlab_url, "https://gitlab.cee.redhat.com")
        self.assertEqual(self.client.project_name, "hybrid-platforms/art/ocp-shipment-data")
        self.assertEqual(self.client.private_token, "test-token")
        self.assertEqual(self.client.merge_request_id, 123)

    def test_get_file_content_success(self):
        # Setup mock project files to return string content directly
        self.mock_project.files.get.return_value = "test content"
        self.mock_mr.source_branch = "test-branch"
        
        # Test with mock file path
        file_path = "test.txt"
        content = self.client.get_file_content(file_path)
        self.assertEqual(content, "test content")
        self.mock_project.files.get.assert_called_once_with(
            file_path=file_path,
            ref="test-branch"
        )

    def test_get_file_content_real_mr(self):
        """Test with real MR ID 15 and print content"""
        try:
            client = GitLabMergeRequest(
                "https://gitlab.cee.redhat.com",
                "hybrid-platforms/art/ocp-shipment-data",
                15
            )
            # Test with actual file path
            file_path = "shipment/ocp/openshift-4.18/openshift-4-18/prod/4.18.3-image.20250414000000.yaml"
            content = client.get_file_content(file_path)
            print(f"\nFile content from MR 15:\n{content}")
            self.assertIsInstance(content, str)
        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest("Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to get file content from real MR: {str(e)}")

    def test_get_all_files(self):
        """Test getting all files from merge request"""
        # Setup mock changes data
        mock_changes = {
            'changes': [
                {'new_path': 'file1.txt'},
                {'new_path': 'file2.yaml'}, 
                {'new_path': 'file3.py'}
            ]
        }
        self.mock_mr.changes.return_value = mock_changes
        
        # Test without filter
        files = self.client.get_all_files()
        self.assertEqual(len(files), 3)
        self.assertIn('file1.txt', files)
        
        # Test with filter
        yaml_files = self.client.get_all_files('yaml')
        self.assertEqual(len(yaml_files), 1)
        self.assertEqual(yaml_files[0], 'file2.yaml')
        
        # Verify API calls
        self.mock_gl.projects.get.assert_called_with(self.client.project_name)
        self.mock_mr.changes.assert_called()

    def test_get_all_files_real_mr(self):
        """Test getting files from real MR 15"""
        try:
            client = GitLabMergeRequest(
                "https://gitlab.cee.redhat.com",
                "hybrid-platforms/art/ocp-shipment-data",
                15
            )
            files = client.get_all_files()
            self.assertIsInstance(files, list)
            self.assertIn('shipment/ocp/openshift-4.18/openshift-4-18/prod/4.18.3-image.20250414000000.yaml', files)
            print(f"\nFiles in MR 15:\n{files}")
        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest("Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to get files from real MR: {str(e)}")

    # Other test methods...

class TestShipmentData(unittest.TestCase):
    @patch('oar.core.configstore.ConfigStore')
    def setUp(self, mock_config):
        self.mock_config = mock_config
        self.mock_config.get_gitlab_base_url.return_value = "https://gitlab.cee.redhat.com"
        self.mock_config.get_shipment_mrs.return_value = ["https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/15"]
        self.mock_config.get_gitlab_token.return_value = None
        self.shipment = ShipmentData(self.mock_config)

    def test_get_jira_issues_with_real_mr(self):
        issues = self.shipment.get_jira_issues()
        self.assertEqual(issues, ["OCPBUGS-12345", "OCPBUGS-67890"])

    def test_get_nvrs_with_real_mr(self):
        nvrs = self.shipment.get_nvrs()
        self.assertEqual(nvrs, ["microshift-bootc-v4.18.0-202503121435.p0.gc0eec47.assembly.4.18.2.el9"])

if __name__ == '__main__':
    unittest.main()
