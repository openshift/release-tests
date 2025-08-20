import os
import tempfile
import unittest
import logging
import time
import datetime
from unittest.mock import patch

from oar.core.git import GitHelper
from oar.core.shipment import GitLabServer
from oar.core.configstore import ConfigStore
from oar.core.exceptions import ConfigStoreException, GitException

logger = logging.getLogger(__name__)

class TestGitHelper(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.cs = ConfigStore("4.19.9")
        cls.gh = GitHelper()
        cls.gl = GitLabServer(cls.cs.get_gitlab_url(), cls.cs.get_gitlab_token())

    def setUp(self):
        self.test_repo_url = "https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data.git"
        self.test_branch = "prepare-shipment-4.19.9-20250814082103"
        self.test_dir = None

    def tearDown(self):
        if self.test_dir and os.path.exists(self.test_dir):
            self.gh.cleanup()

    def test_checkout_repo_success(self):
        self.logger.info("Testing checkout_repo with valid URL and branch")
        repo_path = self.gh.checkout_repo(self.test_repo_url, self.test_branch)
        
    def test_checkout_repo_custom_temp_dir(self):
        self.logger.info("Testing checkout_repo with custom temp directory")
        custom_temp_dir = "/tmp/custom"
        os.makedirs(custom_temp_dir, exist_ok=True)
        repo_path = self.gh.checkout_repo(self.test_repo_url, self.test_branch, temp_parent_dir=custom_temp_dir)
        self.assertTrue(repo_path.startswith(custom_temp_dir))
        self.test_dir = repo_path
        logger.info(f"Git repo path: {repo_path}")
        self.assertTrue(os.path.exists(repo_path))
        self.assertTrue(os.path.isdir(os.path.join(repo_path, ".git")))
        self.test_dir = repo_path
        

    def test_checkout_repo_invalid_url(self):
        logger.info("Testing checkout_repo with invalid URL")
        with self.assertRaises(GitException):
            self.gh.checkout_repo("invalid_url", self.test_branch)

    def test_checkout_repo_invalid_branch(self):
        logger.info("Testing checkout_repo with invalid branch")
        with self.assertRaises(GitException):
            self.gh.checkout_repo(self.test_repo_url, "invalid_branch")

    def test_create_branch_success(self):
        logger.info("Testing create_branch with valid branch name")
        self.gh.checkout_repo(self.test_repo_url, self.test_branch)
        new_branch = f"test-branch-{int(time.time())}"
        self.gh.create_branch(new_branch)
        self.assertEqual(self.gh._repo.active_branch.name, new_branch)
        self.test_dir = self.gh._temp_dir

    def test_create_branch_no_repo(self):
        logger.info("Testing create_branch without checking out repo first")
        with self.assertRaises(GitException):
            self.gh.create_branch(f"test-branch-{int(time.time())}")

    def test_commit_changes_success(self):
        logger.info("Testing commit_changes with valid changes")
        self.gh.checkout_repo(self.test_repo_url, self.test_branch)
        test_file = os.path.join(self.gh._temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")
        
        self.gh.commit_changes("Test commit", [test_file])
        commits = list(self.gh._repo.iter_commits())
        self.assertEqual(commits[0].message, "Test commit")
        self.test_dir = self.gh._temp_dir

    @patch('git.Repo.git.push')
    def test_push_changes_success(self, mock_push):
        logger.info("Testing push_changes with mock")
        # First checkout repo to initialize _repo
        self.gh.checkout_repo(self.test_repo_url, self.test_branch)
        self.test_dir = self.gh._temp_dir
        
        # Now test push
        self.gh.push_changes()
        mock_push.assert_called_once()

    def test_create_merge_request_success(self):
        logger.info("Testing create_merge_request with mock Gitlab")
        repo_dir = self.gh.checkout_repo(branch="prepare-shipment-4.19.9-20250814082103")
        self.gh.configure_remotes("ert-release-bot", f"https://group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self.cs.get_gitlab_token()}@gitlab.cee.redhat.com/rioliu/ocp-shipment-data.git")
        self.gh.configure_remotes("origin", f"https://group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self.cs.get_gitlab_token()}@gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data.git")
        test_branch = f"test-branch-{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}"
        self.gh.create_branch(test_branch)
        file = os.path.join(repo_dir, "test.txt")
        with open(file, "w") as f:
            f.write("test content")
        logger.info(self.gh.show_status())
        self.gh.commit_changes("add test file")
        logger.info(self.gh.show_status())
        self.gh.push_changes("ert-release-bot")
        new_mr = self.gl.create_merge_request("rioliu/ocp-shipment-data", test_branch, "prepare-shipment-4.19.9-20250814082103", "Add test file", target_project="hybrid-platforms/art/ocp-shipment-data")
        logger.info(new_mr.get_web_url())

    def test_commit_changes_with_existing_mr(self):
        logger.info("Test commit new change with exist MR")
        mr = self.gl.get_mr_by_title("Add test file", "hybrid-platforms/art/ocp-shipment-data")
        self.assertIsNotNone(mr)
        source_project = self.gl.gl.projects.get(mr.mr.source_project_id)
        source_repo_url = source_project.http_url_to_repo
        repo_dir = self.gh.checkout_repo(source_repo_url, mr.get_source_branch())
        url_strs = source_repo_url.split("//")
        source_remote = f"{url_strs[0]}//group_143087_bot_e4ed5153eb7e7dfa7eb3d7901a95a6a7:{self.cs.get_gitlab_token()}@{url_strs[1]}"
        self.gh.configure_remotes("origin", source_remote)
        file = os.path.join(repo_dir, "new_config.txt")
        with open(file, "w") as f:
            f.write("new config")
        logger.info(self.gh.show_status())
        self.gh.commit_changes("add new config file")
        self.gh.push_changes()
        

    def test_cleanup_success(self):
        logger.info("Testing cleanup with temporary directory")
        temp_dir = tempfile.mkdtemp(prefix="test-git-", dir="/tmp")
        self.gh._temp_dir = temp_dir
        self.gh.cleanup()
        self.assertFalse(os.path.exists(temp_dir))

    @patch('shutil.rmtree')
    def test_cleanup_failure(self, mock_rmtree):
        logger.info("Testing cleanup failure scenario with mock")
        mock_rmtree.side_effect = Exception("Cleanup failed")
        temp_dir = tempfile.mkdtemp(prefix="test-git-", dir="/tmp")
        self.gh._temp_dir = temp_dir
        self.gh.cleanup()  # Should not raise exception
        self.assertTrue(os.path.exists(temp_dir))  # Cleanup failed
        os.rmdir(temp_dir)  # Actual cleanup for test

    def test_show_status_success(self):
        logger.info("Testing show_status with valid repository")
        self.gh.checkout_repo(self.test_repo_url, self.test_branch)
        status_output = self.gh.show_status()
        logger.info(status_output)
        self.assertIsInstance(status_output, str)
        self.assertIn("On branch", status_output)
        self.test_dir = self.gh._temp_dir

    def test_show_status_no_repo(self):
        logger.info("Testing show_status without checking out repo first")
        with self.assertRaises(GitException):
            self.gh.show_status()

if __name__ == '__main__':
    unittest.main()
