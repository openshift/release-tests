import json
import unittest
import logging
import random
import string
from job.selector import AutoReleaseJobs, TestJobRegistryUpdater

logging.basicConfig(
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)


class TestSelector(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_not_supported_release(self):
        with self.assertRaises(FileNotFoundError):
            AutoReleaseJobs("4.13").get_jobs()

    def test_get_auto_release_jobs(self):
        for release in ["4.15", "4.16"]:
            jobs = AutoReleaseJobs(release).get_jobs()
            self.assertTrue(len(jobs) > 0)
            for job in jobs:
                logger.info(job)
                self.assertRegex(job, "automated-release")

    def test_update_job_registry(self):
        job_list = {
            "nightly": [
                {"prowJob": f"periodic-ci-openshift-openshift-tests-private-release-4.x-automated-release-aws-ipi-private-dummy-test-{''.join(random.choices(string.ascii_lowercase, k=5))}-f360"}
            ],
            "stable": []
        }
        TestJobRegistryUpdater("4.x").update(json.dumps(job_list, indent=2))
