import os
import unittest
import logging
from datetime import datetime

from oar.core.statebox import StateBox, SCHEMA_VERSION, DEFAULT_TASK_STATUS, VALID_TASK_STATUSES
from oar.core.exceptions import StateBoxException

logger = logging.getLogger(__name__)


class TestStateBox(unittest.TestCase):
    """
    Integration tests for StateBox GitHub-backed state management.

    These tests perform real GitHub operations against the z-stream branch.
    Requires GITHUB_TOKEN environment variable to be set.

    Uses a dummy release version for testing and cleans up after each test.
    """

    @classmethod
    def setUpClass(cls):
        """Validate environment and skip tests if GITHUB_TOKEN not found"""
        cls.github_token = os.environ.get("GITHUB_TOKEN")

        if not cls.github_token:
            raise unittest.SkipTest("GITHUB_TOKEN not found in environment. Skipping StateBox integration tests.")

        # Test configuration
        cls.test_release = "4.99.99"  # Dummy release for testing (4.y.z format)
        cls.repo_name = "openshift/release-tests"
        cls.branch = "z-stream"

        logger.info(f"StateBox integration tests will use release: {cls.test_release}")

    def setUp(self):
        """Set up StateBox instance before each test"""
        self.statebox = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )

    def tearDown(self):
        """Clean up - delete test file from GitHub after each test"""
        try:
            if self.statebox.exists():
                # Load to get current SHA
                state = self.statebox.load(force_refresh=True)

                # Delete file
                content = self.statebox._repo.get_contents(
                    path=self.statebox.file_path,
                    ref=self.branch
                )
                self.statebox._repo.delete_file(
                    path=self.statebox.file_path,
                    message=f"[TEST CLEANUP] Delete test file for {self.test_release}",
                    sha=content.sha,
                    branch=self.branch
                )
                logger.info(f"Cleaned up test file: {self.statebox.file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up test file: {str(e)}")

    def test_init_and_default_state(self):
        """Test StateBox initialization and default state structure"""
        self.assertEqual(self.statebox.release, self.test_release)
        self.assertEqual(self.statebox.repo_name, self.repo_name)
        self.assertEqual(self.statebox.branch, self.branch)
        # Verify file path structure: _releases/{y-stream}/statebox/{release}.yaml
        self.assertEqual(self.statebox.file_path, f"_releases/4.99/statebox/{self.test_release}.yaml")

        # Get default state
        default_state = self.statebox._get_default_state()

        # Verify schema
        self.assertEqual(default_state["schema_version"], SCHEMA_VERSION)
        self.assertEqual(default_state["release"], self.test_release)
        self.assertIn("created_at", default_state)
        self.assertIn("updated_at", default_state)

        # Verify metadata structure
        metadata = default_state["metadata"]
        self.assertIsNone(metadata["qe_owner"])
        self.assertIsNone(metadata["jira_ticket"])
        self.assertEqual(metadata["advisory_ids"], {})
        self.assertIsNone(metadata["release_date"])
        self.assertEqual(metadata["candidate_builds"], {})
        self.assertIsNone(metadata["shipment_mr"])

        # Verify tasks and issues are initialized
        self.assertEqual(default_state["tasks"], [])
        self.assertEqual(default_state["issues"], [])

    def test_exists_file_not_found(self):
        """Test exists() returns False when file doesn't exist"""
        # Use a different dummy release that doesn't exist
        dummy_statebox = StateBox(
            release="4.98.98",  # Different dummy release
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )
        self.assertFalse(dummy_statebox.exists())

    def test_load_file_not_exists(self):
        """Test load() returns default state when file doesn't exist"""
        # Use a different dummy release that doesn't exist
        dummy_statebox = StateBox(
            release="4.97.97",  # Different dummy release
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )

        state = dummy_statebox.load()

        # Should return default state
        self.assertEqual(state["release"], "4.97.97")
        self.assertEqual(state["schema_version"], SCHEMA_VERSION)
        self.assertEqual(len(state["tasks"]), 0)
        self.assertEqual(len(state["issues"]), 0)

    def test_save_create_new_file(self):
        """Test save() creates new file in GitHub"""
        # Create initial state
        state = self.statebox._get_default_state()
        state["metadata"]["qe_owner"] = "test@redhat.com"

        # Save to GitHub
        self.statebox.save(state, message="Test: Create new state file")

        # Verify file exists
        self.assertTrue(self.statebox.exists())

        # Load and verify
        loaded_state = self.statebox.load(force_refresh=True)
        self.assertEqual(loaded_state["metadata"]["qe_owner"], "test@redhat.com")

    def test_save_update_existing_file(self):
        """Test save() updates existing file in GitHub"""
        # Create initial state
        state = self.statebox._get_default_state()
        state["metadata"]["qe_owner"] = "initial@redhat.com"
        self.statebox.save(state, message="Test: Initial save")

        # Update state
        state["metadata"]["qe_owner"] = "updated@redhat.com"
        state["metadata"]["jira_ticket"] = "ART-999"
        self.statebox.save(state, message="Test: Update state")

        # Load and verify
        loaded_state = self.statebox.load(force_refresh=True)
        self.assertEqual(loaded_state["metadata"]["qe_owner"], "updated@redhat.com")
        self.assertEqual(loaded_state["metadata"]["jira_ticket"], "ART-999")

    def test_load_with_cache(self):
        """Test load() uses cache on subsequent calls"""
        # Create and save state
        state = self.statebox._get_default_state()
        state["metadata"]["qe_owner"] = "cache-test@redhat.com"
        self.statebox.save(state, message="Test: Cache test")

        # First load
        state1 = self.statebox.load()

        # Second load should use cache (no force_refresh)
        state2 = self.statebox.load()

        # Should be same object reference (from cache)
        self.assertIs(state1, state2)

        # Force refresh should fetch new instance
        state3 = self.statebox.load(force_refresh=True)
        self.assertIsNot(state1, state3)
        self.assertEqual(state1["metadata"]["qe_owner"], state3["metadata"]["qe_owner"])

    def test_update_task_create_new(self):
        """Test update_task() creates new task"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state for task test")

        # Update task (should create new)
        updated_state = self.statebox.update_task(
            "image-consistency-check",
            status="In Progress",
            result="Task started"
        )

        # Verify task created
        self.assertEqual(len(updated_state["tasks"]), 1)
        task = updated_state["tasks"][0]
        self.assertEqual(task["name"], "image-consistency-check")
        self.assertEqual(task["status"], "In Progress")
        self.assertEqual(task["result"], "Task started")
        self.assertIsNotNone(task["started_at"])
        self.assertIsNone(task["completed_at"])

        # Verify saved to GitHub
        loaded_state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(loaded_state["tasks"]), 1)

    def test_update_task_update_existing(self):
        """Test update_task() updates existing task"""
        # Create state with initial task
        self.statebox.update_task("image-consistency-check", status="In Progress", result="Started")

        # Update to Pass
        self.statebox.update_task("image-consistency-check", status="Pass", result="Completed successfully")

        # Verify update
        state = self.statebox.load(force_refresh=True)
        task = state["tasks"][0]
        self.assertEqual(task["status"], "Pass")
        self.assertEqual(task["result"], "Completed successfully")
        self.assertIsNotNone(task["started_at"])
        self.assertIsNotNone(task["completed_at"])

    def test_update_task_invalid_status(self):
        """Test update_task() rejects invalid status"""
        with self.assertRaises(StateBoxException) as context:
            self.statebox.update_task("take-ownership", status="InvalidStatus")
        self.assertIn("Invalid task status", str(context.exception))

    def test_update_task_unsupported_task_name(self):
        """Test update_task() rejects unsupported task names"""
        with self.assertRaises(StateBoxException) as context:
            self.statebox.update_task("unsupported-task", status="In Progress")
        self.assertIn("Unsupported task name", str(context.exception))
        self.assertIn("unsupported-task", str(context.exception))

    def test_update_task_auto_save_disabled(self):
        """Test update_task() with auto_save=False doesn't save to GitHub"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Update without auto-save
        self.statebox.update_task("test-task", status="In Progress", auto_save=False)

        # Verify not saved to GitHub (force refresh from GitHub)
        loaded_state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(loaded_state["tasks"]), 0)

    def test_update_metadata(self):
        """Test update_metadata() updates metadata fields"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Update metadata
        updates = {
            "qe_owner": "owner@redhat.com",
            "jira_ticket": "ART-123",
            "release_date": "2025-02-01"
        }
        self.statebox.update_metadata(updates)

        # Verify updates
        state = self.statebox.load(force_refresh=True)
        self.assertEqual(state["metadata"]["qe_owner"], "owner@redhat.com")
        self.assertEqual(state["metadata"]["jira_ticket"], "ART-123")
        self.assertEqual(state["metadata"]["release_date"], "2025-02-01")

    def test_update_metadata_nested_dict_merge(self):
        """Test update_metadata() merges nested dicts (advisory_ids, candidate_builds)"""
        # Create initial state with some advisory IDs
        state = self.statebox._get_default_state()
        state["metadata"]["advisory_ids"] = {"rpm": 111}
        state["metadata"]["candidate_builds"] = {"x86_64": "build-1"}
        self.statebox.save(state, message="Test: Initial metadata")

        # Update with additional advisory IDs and builds
        updates = {
            "advisory_ids": {"rhcos": 222, "microshift": 333},
            "candidate_builds": {"aarch64": "build-2"}
        }
        self.statebox.update_metadata(updates)

        # Verify merge (should have all keys)
        state = self.statebox.load(force_refresh=True)
        self.assertEqual(state["metadata"]["advisory_ids"]["rpm"], 111)
        self.assertEqual(state["metadata"]["advisory_ids"]["rhcos"], 222)
        self.assertEqual(state["metadata"]["advisory_ids"]["microshift"], 333)
        self.assertEqual(state["metadata"]["candidate_builds"]["x86_64"], "build-1")
        self.assertEqual(state["metadata"]["candidate_builds"]["aarch64"], "build-2")

    def test_add_issue_success(self):
        """Test add_issue() adds new issue"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add blocking issue
        issue_entry = self.statebox.add_issue(
            "Critical bug found in deployment",
            blocker=True,
            related_tasks=["deploy-task"]
        )

        # Verify issue added
        self.assertEqual(issue_entry["issue"], "Critical bug found in deployment")
        self.assertTrue(issue_entry["blocker"])
        self.assertEqual(issue_entry["related_tasks"], ["deploy-task"])
        self.assertFalse(issue_entry["resolved"])
        self.assertIsNotNone(issue_entry["reported_at"])

        # Verify saved to GitHub
        state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(state["issues"]), 1)

    def test_add_issue_deduplication(self):
        """Test add_issue() prevents duplicate issues"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add issue
        self.statebox.add_issue("Duplicate bug", blocker=True)

        # Try to add duplicate (case-insensitive)
        issue_entry = self.statebox.add_issue("duplicate bug", blocker=True)

        # Verify only one issue exists
        state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(state["issues"]), 1)

    def test_add_issue_multiple_blockers_per_task_rejected(self):
        """Test add_issue() rejects multiple unresolved blockers for same task"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add first blocker for task1
        self.statebox.add_issue("First blocker", blocker=True, related_tasks=["task1"])

        # Try to add second blocker for task1
        with self.assertRaises(StateBoxException) as context:
            self.statebox.add_issue("Second blocker", blocker=True, related_tasks=["task1"])
        self.assertIn("already has unresolved blocker", str(context.exception))

    def test_add_issue_general_blocker(self):
        """Test add_issue() with empty related_tasks creates general blocker"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add general blocker
        issue_entry = self.statebox.add_issue(
            "ART pipeline is down",
            blocker=True,
            related_tasks=[]
        )

        # Verify general blocker
        self.assertEqual(issue_entry["related_tasks"], [])
        self.assertTrue(issue_entry["blocker"])

        # Should allow another general blocker (different description)
        issue_entry2 = self.statebox.add_issue(
            "Network outage",
            blocker=True,
            related_tasks=[]
        )

        # Verify both exist
        state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(state["issues"]), 2)

    def test_resolve_issue_exact_match(self):
        """Test resolve_issue() with exact match"""
        # Create state with issue
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")
        self.statebox.add_issue("Test bug", blocker=True)

        # Resolve issue
        resolved = self.statebox.resolve_issue("Test bug", "Fixed in PR #123")

        # Verify resolved
        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["resolution"], "Fixed in PR #123")
        self.assertIn("resolved_at", resolved)

        # Verify saved to GitHub
        state = self.statebox.load(force_refresh=True)
        self.assertTrue(state["issues"][0]["resolved"])

    def test_resolve_issue_partial_match(self):
        """Test resolve_issue() with partial match"""
        # Create state with issue
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")
        self.statebox.add_issue("Long description of a critical bug in deployment", blocker=True)

        # Resolve with partial match
        resolved = self.statebox.resolve_issue("critical bug", "Fixed")

        # Verify resolved
        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["issue"], "Long description of a critical bug in deployment")

    def test_resolve_issue_not_found(self):
        """Test resolve_issue() when issue not found"""
        # Create empty state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Try to resolve non-existent issue
        with self.assertRaises(StateBoxException) as context:
            self.statebox.resolve_issue("Non-existent bug", "Fixed")
        self.assertIn("Issue not found", str(context.exception))

    def test_get_task_blocker(self):
        """Test get_task_blocker() finds blocker for task"""
        # Create state with task blocker
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")
        self.statebox.add_issue("Blocker for task1", blocker=True, related_tasks=["task1"])

        # Get blocker
        blocker = self.statebox.get_task_blocker("task1")

        # Verify found
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker["issue"], "Blocker for task1")

        # Verify task2 has no blocker
        blocker2 = self.statebox.get_task_blocker("task2")
        self.assertIsNone(blocker2)

    def test_get_issues_filters(self):
        """Test get_issues() with various filters"""
        # Create state with multiple issues
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add various issues
        self.statebox.add_issue("Unresolved blocker 1", blocker=True, related_tasks=["task1"])
        self.statebox.add_issue("Unresolved non-blocker", blocker=False, related_tasks=["task2"])
        self.statebox.add_issue("Resolved blocker", blocker=True, related_tasks=["task3"])
        self.statebox.resolve_issue("Resolved blocker", "Fixed")

        # Test unresolved_only filter
        unresolved = self.statebox.get_issues(unresolved_only=True)
        self.assertEqual(len(unresolved), 2)

        # Test blockers_only filter
        blockers = self.statebox.get_issues(blockers_only=True)
        self.assertEqual(len(blockers), 2)

        # Test task_name filter
        task1_issues = self.statebox.get_issues(task_name="task1")
        self.assertEqual(len(task1_issues), 1)

        # Test combined filters
        unresolved_blockers = self.statebox.get_issues(unresolved_only=True, blockers_only=True)
        self.assertEqual(len(unresolved_blockers), 1)

    def test_get_general_blockers(self):
        """Test get_general_blockers() returns only general blockers"""
        # Create state with mixed issues
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state")

        # Add issues
        self.statebox.add_issue("General blocker 1", blocker=True, related_tasks=[])
        self.statebox.add_issue("Task blocker", blocker=True, related_tasks=["task1"])
        self.statebox.add_issue("General blocker 2", blocker=True, related_tasks=[])

        # Get general blockers
        blockers = self.statebox.get_general_blockers()

        # Verify only general blockers
        self.assertEqual(len(blockers), 2)
        self.assertTrue(all(len(b["related_tasks"]) == 0 for b in blockers))

    def test_get_task_status(self):
        """Test get_task_status() returns task status"""
        # Create state with task
        self.statebox.update_task("test-task", status="In Progress")

        # Get status
        status = self.statebox.get_task_status("test-task")
        self.assertEqual(status, "In Progress")

        # Non-existent task
        status2 = self.statebox.get_task_status("non-existent")
        self.assertIsNone(status2)

    def test_get_task(self):
        """Test get_task() returns complete task info"""
        # Create task
        self.statebox.update_task("test-task", status="Pass", result="Success")

        # Get task
        task = self.statebox.get_task("test-task")

        # Verify
        self.assertIsNotNone(task)
        self.assertEqual(task["name"], "test-task")
        self.assertEqual(task["status"], "Pass")
        self.assertEqual(task["result"], "Success")

    def test_get_metadata(self):
        """Test get_metadata() returns metadata"""
        # Create state with metadata
        state = self.statebox._get_default_state()
        state["metadata"]["qe_owner"] = "owner@redhat.com"
        state["metadata"]["jira_ticket"] = "ART-123"
        self.statebox.save(state, message="Test: Metadata test")

        # Get all metadata
        metadata = self.statebox.get_metadata()
        self.assertEqual(metadata["qe_owner"], "owner@redhat.com")
        self.assertEqual(metadata["jira_ticket"], "ART-123")

        # Get specific key
        owner = self.statebox.get_metadata("qe_owner")
        self.assertEqual(owner, "owner@redhat.com")

    def test_context_manager(self):
        """Test StateBox as context manager"""
        with StateBox(
            release=self.test_release,
            github_token=self.github_token
        ) as statebox:
            self.assertIsNotNone(statebox)
            self.assertEqual(statebox.release, self.test_release)

    def test_concurrent_writes_with_merge(self):
        """Test concurrent writes from multiple StateBox instances with merge"""
        # Create initial state
        state = self.statebox._get_default_state()
        state["metadata"]["qe_owner"] = "initial@redhat.com"
        self.statebox.save(state, message="Test: Initial state for concurrent test")

        # Create two separate StateBox instances (simulating concurrent processes)
        statebox1 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )
        statebox2 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )

        # Both load the same initial state
        state1 = statebox1.load()
        state2 = statebox2.load()

        # Verify both loaded same state
        self.assertEqual(state1["metadata"]["qe_owner"], "initial@redhat.com")
        self.assertEqual(state2["metadata"]["qe_owner"], "initial@redhat.com")

        # Instance 1 updates metadata
        state1["metadata"]["jira_ticket"] = "ART-111"
        statebox1.save(state1, message="Test: Update from instance 1")

        # Instance 2 updates different metadata (this should trigger merge)
        state2["metadata"]["qe_owner"] = "updated@redhat.com"
        statebox2.save(state2, message="Test: Update from instance 2")

        # Load final state and verify both updates are present (merge succeeded)
        final_state = self.statebox.load(force_refresh=True)
        self.assertEqual(final_state["metadata"]["qe_owner"], "updated@redhat.com")
        self.assertEqual(final_state["metadata"]["jira_ticket"], "ART-111")

    def test_concurrent_task_updates_with_merge(self):
        """Test concurrent task updates from multiple StateBox instances"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state for concurrent task test")

        # Create two separate StateBox instances
        statebox1 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )
        statebox2 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )

        # Instance 1 updates task1
        statebox1.update_task("task1", status="In Progress", result="Task 1 started")

        # Instance 2 updates task2 (should trigger merge)
        statebox2.update_task("task2", status="Pass", result="Task 2 completed")

        # Load final state and verify both tasks exist
        final_state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(final_state["tasks"]), 2)

        task1 = next(t for t in final_state["tasks"] if t["name"] == "task1")
        task2 = next(t for t in final_state["tasks"] if t["name"] == "task2")

        self.assertEqual(task1["status"], "In Progress")
        self.assertEqual(task1["result"], "Task 1 started")
        self.assertEqual(task2["status"], "Pass")
        self.assertEqual(task2["result"], "Task 2 completed")

    def test_concurrent_issue_updates_with_merge(self):
        """Test concurrent issue additions from multiple StateBox instances"""
        # Create initial state
        state = self.statebox._get_default_state()
        self.statebox.save(state, message="Test: Initial state for concurrent issue test")

        # Create two separate StateBox instances
        statebox1 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )
        statebox2 = StateBox(
            release=self.test_release,
            repo_name=self.repo_name,
            branch=self.branch,
            github_token=self.github_token
        )

        # Instance 1 adds issue1
        statebox1.add_issue("Issue from instance 1", blocker=True, related_tasks=["task1"])

        # Instance 2 adds issue2 (should trigger merge)
        statebox2.add_issue("Issue from instance 2", blocker=True, related_tasks=["task2"])

        # Load final state and verify both issues exist
        final_state = self.statebox.load(force_refresh=True)
        self.assertEqual(len(final_state["issues"]), 2)

        issue_texts = [issue["issue"] for issue in final_state["issues"]]
        self.assertIn("Issue from instance 1", issue_texts)
        self.assertIn("Issue from instance 2", issue_texts)


if __name__ == '__main__':
    unittest.main()