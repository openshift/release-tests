import unittest
from prow.job.job import Jobs


class TestJobValidation(unittest.TestCase):
    """Test validation functions in Jobs class"""

    def setUp(self):
        """Set up test fixtures"""
        self.jobs = Jobs()

    def test_valid_payload_url(self):
        """Test validation of valid payload URLs"""
        valid_urls = [
            "quay.io/openshift-release-dev/ocp-release:4.19.1-x86_64",
            "quay.io/openshift-release-dev/ocp-release:4.18.25-x86_64",
            "quay.io/openshift-release-dev/ocp-release:4.20.0-x86_64",
            "quay.io/openshift-release-dev/ocp-release:4.19.1-rc.0-x86_64",
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                self.assertTrue(
                    self.jobs._is_valid_payload_url(url),
                    f"Expected {url} to be valid"
                )

    def test_invalid_payload_url(self):
        """Test validation of invalid payload URLs"""
        invalid_urls = [
            # Wrong architecture
            "quay.io/openshift-release-dev/ocp-release:4.19.1-aarch64",
            "quay.io/openshift-release-dev/ocp-release:4.19.1-ppc64le",
            # Wrong registry
            "docker.io/openshift-release-dev/ocp-release:4.19.1-x86_64",
            # Missing architecture
            "quay.io/openshift-release-dev/ocp-release:4.19.1",
            # Invalid version format
            "quay.io/openshift-release-dev/ocp-release:4.19-x86_64",
            "quay.io/openshift-release-dev/ocp-release:invalid-x86_64",
            # Empty or malformed
            "",
            "not-a-url",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(
                    self.jobs._is_valid_payload_url(url),
                    f"Expected {url} to be invalid"
                )

    def test_valid_mr_id(self):
        """Test validation of valid merge request IDs"""
        valid_ids = [1, 100, 999999, 12345]
        for mr_id in valid_ids:
            with self.subTest(mr_id=mr_id):
                self.assertTrue(
                    self.jobs._is_valid_mr_id(mr_id),
                    f"Expected {mr_id} to be valid"
                )

    def test_invalid_mr_id(self):
        """Test validation of invalid merge request IDs"""
        invalid_ids = [0, -1, -100]
        for mr_id in invalid_ids:
            with self.subTest(mr_id=mr_id):
                self.assertFalse(
                    self.jobs._is_valid_mr_id(mr_id),
                    f"Expected {mr_id} to be invalid"
                )

    def test_run_image_consistency_check_invalid_payload(self):
        """Test that run_image_consistency_check raises exception for invalid payload URL"""
        with self.assertRaises(Exception) as context:
            self.jobs.run_image_consistency_check(
                payload_url="invalid-url",
                mr_id=12345
            )
        self.assertIn("Invalid payload URL", str(context.exception))

    def test_run_image_consistency_check_invalid_mr_id(self):
        """Test that run_image_consistency_check raises exception for invalid MR ID"""
        with self.assertRaises(Exception) as context:
            self.jobs.run_image_consistency_check(
                payload_url="quay.io/openshift-release-dev/ocp-release:4.19.1-x86_64",
                mr_id=-1
            )
        self.assertIn("Invalid merge request ID", str(context.exception))

    def test_run_stage_testing_invalid_payload(self):
        """Test that run_stage_testing raises exception for invalid payload URL"""
        with self.assertRaises(Exception) as context:
            self.jobs.run_stage_testing(
                payload_url="invalid-url"
            )
        self.assertIn("Invalid payload URL", str(context.exception))

    def test_get_minor_release_from_payload_url(self):
        """Test extraction of minor release from payload URL"""
        test_cases = [
            ("quay.io/openshift-release-dev/ocp-release:4.19.1-x86_64", "4.19"),
            ("quay.io/openshift-release-dev/ocp-release:4.18.25-x86_64", "4.18"),
            ("quay.io/openshift-release-dev/ocp-release:4.20.0-rc.1-x86_64", "4.20"),
        ]
        for payload_url, expected_minor in test_cases:
            with self.subTest(payload_url=payload_url):
                result = self.jobs._get_minor_release_from_payload_url(payload_url)
                self.assertEqual(result, expected_minor)
