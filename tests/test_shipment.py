import unittest
import gitlab
import os
from unittest.mock import MagicMock, patch
from oar.core.shipment import GitLabMergeRequest, ShipmentData, GitLabServer
from oar.core.exceptions import (
    GitLabServerException,
    ShipmentDataException,
    GitLabMergeRequestException
)


class TestGitLabServer(unittest.TestCase):
    @patch('os.getenv', return_value="test-token")
    @patch('oar.core.shipment.Gitlab')
    def setUp(self, mock_gitlab, mock_getenv):
        self.mock_gl = MagicMock()
        mock_gitlab.return_value = self.mock_gl
        self.server = GitLabServer(
            "https://gitlab.cee.redhat.com", "test-token")

    def test_get_username_by_email_success(self):
        # Setup mock user response
        mock_user = MagicMock()
        mock_user.email = "test@example.com"
        mock_user.username = "testuser"
        self.mock_gl.users.list.return_value = [mock_user]

        # Test valid email
        username = self.server.get_username_by_email("test@example.com")
        self.assertEqual(username, "testuser")
        self.mock_gl.users.list.assert_called_once_with(
            search="test@example.com")

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
        self.mock_gl.users.list.side_effect = gitlab.exceptions.GitlabError(
            "API error")

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
    @patch('oar.core.shipment.Gitlab')
    def setUp(self, mock_gitlab, mock_getenv):
        self.mock_gl = MagicMock()
        self.mock_project = MagicMock()
        self.mock_mr = MagicMock()
        self.mock_file = MagicMock()
        # Mock decode() to return string
        self.mock_file.decode.return_value = "test content"

        # Mock the Gitlab class and its instance
        mock_gitlab.return_value = self.mock_gl
        self.mock_gl.auth = MagicMock(return_value=None)
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
        self.assertEqual(self.client.gitlab_url,
                         "https://gitlab.cee.redhat.com")
        self.assertEqual(self.client.project_name,
                         "hybrid-platforms/art/ocp-shipment-data")
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
                self.skipTest(
                    "Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to get file content from real MR: {str(e)}")

    def test_get_all_files(self):
        """Test getting all files from merge request"""
        # Setup mock changes response to match GitLab API
        mock_changes_response = {
            'changes': [
                {'new_path': 'file1.txt'},
                {'new_path': 'file2.yaml'},
                {'new_path': 'file3.py'}
            ]
        }
        self.mock_mr.changes.return_value = mock_changes_response

        # Test without filter
        files = self.client.get_all_files()
        # default file extension is yaml, so only 1 file matched
        self.assertEqual(len(files), 1)
        self.assertIn('file2.yaml', files)

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
            self.assertIn(
                'shipment/ocp/openshift-4.18/openshift-4-18/prod/4.18.3-image.20250414000000.yaml', files)
            print(f"\nFiles in MR 15:\n{files}")
        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest(
                    "Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to get files from real MR: {str(e)}")

    def test_approve_success(self):
        """Test successful approval of merge request"""
        # Setup mock MR state and approvals
        self.mock_mr.state = 'opened'
        self.mock_gl.user = MagicMock()
        self.mock_gl.user.username = 'testuser'

        # Setup mock approvals
        mock_approvals = MagicMock()
        mock_approvals.approved_by = []
        self.mock_mr.approvals.get.return_value = mock_approvals

        # Setup logger mock
        with patch('oar.core.shipment.logger') as mock_logger:
            # Test approval
            self.client.approve()

            # Verify calls
            self.mock_mr.approve.assert_called_once()
            self.mock_mr.approvals.get.assert_called_once()
            mock_logger.info.assert_called_with(
                f"Successfully approved MR {self.client.merge_request_id}"
            )

    def test_approve_already_approved(self):
        """Test approval when already approved"""
        # Setup mock MR state and approvals
        self.mock_mr.state = 'opened'
        self.mock_gl.user = MagicMock()
        self.mock_gl.user.username = 'testuser'

        # Setup mock approvals showing already approved
        mock_approvals = MagicMock()
        mock_approvals.approved_by = [{'user': {'username': 'testuser'}}]
        self.mock_mr.approvals.get.return_value = mock_approvals

        # Setup logger mock
        with patch('oar.core.shipment.logger') as mock_logger:
            # Test approval
            self.client.approve()

            # Verify approve() was NOT called
            self.mock_mr.approve.assert_not_called()
            mock_logger.info.assert_called_with(
                f"User {self.mock_gl.user.username} has already approved MR {self.client.merge_request_id}"
            )

    def test_approve_invalid_state(self):
        """Test approval when MR is not in opened state"""
        # Setup mock MR state
        self.mock_mr.state = 'merged'

        # Test approval
        with self.assertRaises(GitLabMergeRequestException) as context:
            self.client.approve()
        self.assertIn("Cannot approve MR in state", str(context.exception))
        self.mock_mr.approve.assert_not_called()

    def test_approve_user_not_found(self):
        """Test approval when current user cannot be identified"""
        # Setup mock MR state
        self.mock_mr.state = 'opened'
        self.mock_gl.user = None

        # Setup logger mock
        with patch('oar.core.shipment.logger') as mock_logger:
            # Test approval
            with self.assertRaises(GitLabMergeRequestException) as context:
                self.client.approve()
            self.assertIn("Could not identify current user",
                          str(context.exception))
            self.mock_mr.approve.assert_not_called()

    def test_approve_api_error(self):
        """Test approval when GitLab API fails"""
        # Setup mock MR state
        self.mock_mr.state = 'opened'
        self.mock_gl.user = MagicMock()
        self.mock_gl.user.username = 'testuser'

        # Setup mock approvals to raise error
        self.mock_mr.approvals.get.side_effect = gitlab.exceptions.GitlabError(
            "API error")

        # Setup logger mock
        with patch('oar.core.shipment.logger') as mock_logger:
            # Test approval
            with self.assertRaises(GitLabMergeRequestException) as context:
                self.client.approve()
            self.assertIn("Failed to approve merge request",
                          str(context.exception))
            self.mock_mr.approve.assert_not_called()
            mock_logger.error.assert_called_with(
                f"Failed to approve MR {self.client.merge_request_id}: GitLab API error"
            )

    def test_approve_real_mr(self):
        """Test approval with real MR (requires GITLAB_TOKEN env var)"""
        if not os.getenv('GITLAB_TOKEN'):
            self.skipTest("GITLAB_TOKEN not set - skipping real API test")

        try:
            client = GitLabMergeRequest(
                "https://gitlab.cee.redhat.com",
                "hybrid-platforms/art/ocp-shipment-data",
                15
            )
            client.approve()
            print(f"\nSuccessfully approved MR 15")
        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest(
                    "Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to approve real MR: {str(e)}")

    def test_add_suggestion_real_mr(self):
        """Test adding suggestion with real MR (requires GITLAB_TOKEN env var)"""
        if not os.getenv('GITLAB_TOKEN'):
            self.skipTest("GITLAB_TOKEN not set - skipping real API test")

        try:
            mr_id = 15
            client = GitLabMergeRequest(
                "https://gitlab.cee.redhat.com",
                "hybrid-platforms/art/ocp-shipment-data",
                mr_id
            )
            suggestion = "drop this bug"
            client.add_suggestion(
                file_path="shipment/ocp/openshift-4.18/openshift-4-18/prod/4.18.3-image.20250414000000.yaml",
                old_line=None,
                new_line=23,
                relative_lines="-0+1",
                suggestion=""
            )
            print(f"\nSuccessfully added suggestion to MR {mr_id}")
        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest(
                    f"Merge request {mr_id} not found - skipping real API test")
            else:
                self.fail(f"Failed to add suggestion to real MR: {str(e)}")


class TestShipmentData(unittest.TestCase):
    @patch('oar.core.configstore.ConfigStore')
    def setUp(self, mock_config):
        self.mock_config = mock_config
        self.mock_config.get_gitlab_url.return_value = "https://gitlab.cee.redhat.com"
        self.mock_config.get_shipment_mrs.return_value = [
            "https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/15"]
        self.mock_config.get_gitlab_token.return_value = None
        self.shipment = ShipmentData(self.mock_config)

    def test_get_jira_issues_with_real_mr(self):
        issues = self.shipment.get_jira_issues()
        self.assertEqual(issues, ["OCPBUGS-12345", "OCPBUGS-67890"])

    def test_get_nvrs_with_real_mr(self):
        nvrs = self.shipment.get_nvrs()
        self.assertEqual(
            nvrs, ["microshift-bootc-v4.18.0-202503121435.p0.gc0eec47.assembly.4.18.2.el9"])

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
        mock_server.get_username_by_email.assert_called_once_with(
            "test@example.com")
        mock_mr.add_comment.assert_called_once_with(
            "QE Release Lead is @testuser")

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

    def test_add_qe_release_lead_comment_invalid_email(self):
        # Test invalid email formats
        with self.assertRaises(ShipmentDataException) as context:
            self.shipment.add_qe_release_lead_comment("")
        self.assertIn("Email must be a non-empty string",
                      str(context.exception))

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

    @patch('oar.core.shipment.GitLabMergeRequest')
    def test_add_qe_approval_success(self, mock_mr_class):
        """Test successful approval of all MRs"""
        # Setup mock MRs
        mock_mr1 = MagicMock()
        mock_mr2 = MagicMock()
        self.shipment._mrs = [mock_mr1, mock_mr2]

        # Test the method
        self.shipment.add_qe_approval()

        # Verify each MR was approved
        mock_mr1.approve.assert_called_once()
        mock_mr2.approve.assert_called_once()

    @patch('oar.core.shipment.GitLabMergeRequest')
    def test_add_qe_approval_partial_failure(self, mock_mr_class):
        """Test approval when some MRs fail"""
        # Setup mock MRs - one succeeds, one fails
        mock_mr1 = MagicMock()
        mock_mr2 = MagicMock()
        expected_exception = GitLabMergeRequestException("Failed to approve")
        mock_mr2.approve.side_effect = expected_exception
        self.shipment._mrs = [mock_mr1, mock_mr2]

        # Test the method - should raise exception for partial failure
        with self.assertRaises(GitLabMergeRequestException):
            self.shipment.add_qe_approval()

        # Verify each MR was attempted
        mock_mr1.approve.assert_called_once()
        mock_mr2.approve.assert_called_once()

    def test_get_jira_issue_line_numbers_real_mr(self):
        """Test finding Jira issue line numbers in real MR (requires GITLAB_TOKEN env var)"""
        if not os.getenv('GITLAB_TOKEN'):
            self.skipTest("GITLAB_TOKEN not set - skipping real API test")

        try:
            # Use MR 15 which has known files with Jira issues
            client = GitLabMergeRequest(
                "https://gitlab.cee.redhat.com",
                "hybrid-platforms/art/ocp-shipment-data",
                15
            )

            # Test file that should contain Jira issues
            test_file = "shipment/ocp/openshift-4.18/openshift-4-18/prod/4.18.3-image.20250414000000.yaml"

            # Get the file content to find actual Jira issues
            content = client.get_file_content(test_file)
            lines = content.splitlines()

            # Find first Jira issue key in file
            jira_num = None
            for i, line in enumerate(lines, 1):
                if "OCPBUGS-" in line:
                    jira_num = line.split("OCPBUGS-")[1].split()[0]
                    jira_num = f"OCPBUGS-{jira_num}"
                    expected_line = i
                    break

            if not jira_num:
                self.skipTest(
                    f"No Jira issues found in {test_file} - skipping test")

            # Test the method
            found_line = client.get_jira_issue_line_number(jira_num, test_file)

            # Verify results
            self.assertEqual(found_line, expected_line)
            print(
                f"\nFound Jira issue {jira_num} at line {found_line} in {test_file}")

            # Test with non-existent key
            not_found_line = client.get_jira_issue_line_number(
                "OCPBUGS-999999", test_file)
            self.assertIsNone(not_found_line)

        except Exception as e:
            if "Merge request 15 not found" in str(e):
                self.skipTest(
                    "Merge request 15 not found - skipping real API test")
            else:
                self.fail(f"Failed to test Jira issue line numbers: {str(e)}")


if __name__ == '__main__':
    unittest.main()
