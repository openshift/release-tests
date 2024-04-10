import unittest
import logging
import os
import json
from job.artifacts import Artifacts
from job.sippy import Sippy

logging.basicConfig(
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TestArtifacts(unittest.TestCase):

    def setUp(self):
        self.artifacts = Artifacts(os.environ.get(
            "GCS_CRED_FILE"), "periodic-ci-openshift-openshift-tests-private-release-4.15-automated-release-aws-ipi-fips-f1", "1775675266119503872")
        self.sippy = Sippy("sippy.dptools.openshift.org")

    def test_get_junit_files(self):
        junit_files = self.artifacts.get_junit_files()
        self.assertTrue(
            len(junit_files) > 0, "Cannot get junit files")

        logger.info(f"found {len(junit_files)} junit files")
        for jf in junit_files:
            logger.info(f"{jf.name}")

    def test_generate_job_summary(self):
        job_data = self.artifacts.generate_job_summary()
        logger.info(json.dumps(json.loads(job_data), indent=2))
        resp = self.sippy.query_risk_analysis(job_data)
        logger.info(resp)
