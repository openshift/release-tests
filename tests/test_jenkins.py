import unittest

from oar.core.configstore import ConfigStore
from oar.core.jenkins import JenkinsHelper


class TestJenkinsHelper(unittest.TestCase):
    def setUp(self):
        self.cs = ConfigStore("4.18.17")
        self.jh = JenkinsHelper(self.cs)

    def test_init(self):
        pass

    def test_call_stage_job(self):
        result = self.jh.call_stage_job()
        self.assertIsNotNone(result)
        self.assertIn("Stage-Pipeline", result)

    def test_call_image_consistency_job(self):
        result = self.jh.call_image_consistency_job(self.jh.pull_spec)
        self.assertIsNotNone(result)
        self.assertIn("image-consistency-check", result)
