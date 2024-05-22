import unittest
import logging
from job.selector import AutoReleaseJobs

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
        self.assertRaises(FileNotFoundError, AutoReleaseJobs, "4.13")
        self.assertRaises(FileNotFoundError, AutoReleaseJobs, "4.14")

    def test_get_auto_release_jobs(self):
        for release in ["4.15", "4.16"]:
            jobs = AutoReleaseJobs(release).get_jobs()
            self.assertTrue(len(jobs) > 0)
            for job in jobs:
                logger.info(job)
                self.assertRegex(job, "automated-release")
