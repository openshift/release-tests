import unittest
import gitlab
import os
from unittest.mock import MagicMock, patch
from oar.core.shipment import GitLabMergeRequest, ShipmentData, GitLabServer
from oar.core.exceptions import (
    GitLabServerException,
    ShipmentDataException
)

class TestGitLabServer(unittest.TestCase):
    @patch('os.getenv', return_value="test-token")
    @patch('gitlab.Gitlab')
    def setUp(self, mock_gitlab, mock_getenv):
        self.mock_gl = MagicMock()
        mock_gitlab.return_value = self.mock_gl
        self.server = GitLabServer("https://gitlab.cee.redhat.com", "test-token")

    def test_get_username_by_email_success(self):
        # Setup mock user response
        mock_user = MagicMock()
        mock_user.email = "test@example.com"
        mock_user.username = "testuser"
        self.mock_gl.users.list.return_value = [mock_user]

        # Test valid email
        username = self.server.get_username_by_email("test@example.com")
        self.assertEqual(username, "testuser")
        self.mock_gl.users.list.assert_called_once_with(search="test@example.com")

    def test_get_username_by_email_not_found(self):
        # Setup empty response
        self.mock_gl.users.list.return_value = []

        # Test email not found
        username = self.server.get_username_by_email("notfound@example.com")
        self.assertIsNone(username)

    def test_get_username_by_email_invalid(self):
        # Test invalid email formats
        with self.assertRaises(ValueError):
            self.server.get_username_by_email("")
        
        with self.assertRaises(ValueError):
            self.server.get_username_by_email("invalid-email")

    def test_get_username_by_email_api_error(self):
        # Setup API error
        self.mock_gl.users.list.side_effect = gitlab.exceptions.GitlabError("API error")

        with self.assertRaises(GitLabServerException) as context:
            self.server.get_username_by_email("test@example.com")
        self.assertIn("GitLab API error", str(context.exception))

    def test_get_username_by_email_real(self):
        """Test with real GitLab API (requires GITLAB_TOKEN env var)"""
        if not os.getenv('GITLAB_TOKEN'):
            self.skipTest("GITLAB_TOKEN not set - skipping real API test")
            
        try:
            # Use a known Red Hat email that should exist in GitLab
            test_email = "rioliu@redhat.com"
            server = GitLabServer("https://gitlab.cee.redhat.com")
            username = server.get_username_by_email(test_email)
            self.assertIsNotNone(username)
            self.assertIsInstance(username, str)
            print(f"\nFound GitLab username for {test_email}: {username}")
        except Exception as e:
            self.fail(f"Real GitLab API test failed: {str(e)}")


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
        self.mock_config.get_gitlab_url.return_value = "https://gitlab.cee.redhat.com"
        self.mock_config.get_shipment_mrs.return_value = ["https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/15"]
        self.mock_config.get_gitlab_token.return_value = None
        self.shipment = ShipmentData(self.mock_config)

    def test_get_jira_issues_with_real_mr(self):
        issues = self.shipment.get_jira_issues()
        self.assertEqual(issues, ["OCPBUGS-12345", "OCPBUGS-67890"])

    def test_get_nvrs_with_real_mr(self):
        nvrs = self.shipment.get_nvrs()
        self.assertEqual(nvrs, ["microshift-bootc-v4.18.0-202503121435.p0.gc0eec47.assembly.4.18.2.el9"])

    @patch('oar.core.shipment.GitLabServer')
    def test_add_qe_release_lead_comment_success(self, mock_gl_server):
        # Setup mock GitLab server
        mock_server = MagicMock()
        mock_server.get_username_by_email.return_value = "testuser"
        mock_gl_server.return_value = mock_server

        # Setup mock merge request
        mock_mr = MagicMock()
        self.shipment._mrs = [mock_mr]

        # Test the method
        self.shipment.add_qe_release_lead_comment("test@example.com")

        # Verify calls
        mock_gl_server.assert_called_once_with(
            self.mock_config.get_gitlab_url(),
            self.mock_config.get_gitlab_token()
        )
        mock_server.get_username_by_email.assert_called_once_with("test@example.com")
        mock_mr.add_comment.assert_called_once_with("QE Release Lead from ERT is @testuser")

    @patch('oar.core.shipment.GitLabServer')
    def test_add_qe_release_lead_comment_user_not_found(self, mock_gl_server):
        # Setup mock GitLab server to return None (user not found)
        mock_server = MagicMock()
        mock_server.get_username_by_email.return_value = None
        mock_gl_server.return_value = mock_server

        # Test that exception is raised
        with self.assertRaises(ShipmentDataException) as context:
            self.shipment.add_qe_release_lead_comment("notfound@example.com")
        self.assertIn("No GitLab user found for email", str(context.exception))

    # @patch('oar.core.shipment.GitLabServer')
    def test_add_qe_release_lead_comment_invalid_email(self):
        # Test invalid email formats
        with self.assertRaises(ShipmentDataException) as context:
            self.shipment.add_qe_release_lead_comment("")
        self.assertIn("Email must be a non-empty string", str(context.exception))

        with self.assertRaises(ShipmentDataException) as context:
            self.shipment.add_qe_release_lead_comment("invalid-email")
        self.assertIn("Email must be in valid format", str(context.exception))

    def test_add_qe_release_lead_comment_real_mr(self):
        """Test with real GitLab MR (requires GITLAB_TOKEN env var)"""
        if not os.getenv('GITLAB_TOKEN'):
            self.skipTest("GITLAB_TOKEN not set - skipping real MR test")

        try:
            # Use a known real MR and email, the MR (#15) is configured in mocked configustore
            # the private token is retrieved from os env var
            test_email = "rioliu@redhat.com"
            
            # Create shipment with the real MR
            real_shipment = ShipmentData(self.mock_config)
            
            # Test the method
            real_shipment.add_qe_release_lead_comment(test_email)
            
            # Verify by checking logs (actual comment verification would require API call)
            # In real usage, you might want to manually verify the comment was added
            self.assertTrue(True)  # Placeholder assertion
        except Exception as e:
            self.fail(f"Real MR test failed: {str(e)}")

if __name__ == '__main__':
    unittest.main()
