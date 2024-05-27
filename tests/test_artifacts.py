import unittest
import logging
import os
import json
import yaml
from job.artifacts import Artifacts
from job.sippy import Sippy

logging.basicConfig(
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)


class TestArtifacts(unittest.TestCase):

    def setUp(self):
        self.artifacts = Artifacts(os.environ.get(
            "GCS_CRED_FILE"), "periodic-ci-openshift-openshift-tests-private-release-4.16-automated-release-aws-ipi-private-shared-vpc-phz-sts-f360", "1793149826221740032")
        # self.sippy = Sippy("sippy.dptools.openshift.org")

    def test_get_junit_files(self):
        junit_files = self.artifacts.get_junit_files()
        self.assertTrue(
            len(junit_files) > 0, "Cannot get junit files")

        logger.info(f"found {len(junit_files)} junit files")
        for jf in junit_files:
            logger.info(f"{jf.name}")

    def test_get_qe_test_report(self):
        test_report = self.artifacts.get_qe_test_report()
        self.assertTrue(len(test_report) > 0)
        logger.info(json.dumps(yaml.safe_load(test_report), indent=2))

    def test_generate_job_summary(self):
        test_failures_summary = self.artifacts.generate_test_failures_summary()
        logger.info(json.dumps(json.loads(test_failures_summary), indent=2))
        # resp = self.sippy.query_risk_analysis(test_failures_summary)
        # logger.info(resp)
