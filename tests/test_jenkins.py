import unittest
from oar.core.jenkins import JenkinsHelper
from oar.core.configstore import ConfigStore


class TestJenkinsHelper(unittest.TestCase):
    def setUp(self):
        self.cs = ConfigStore("4.12.11")
        self.jh = JenkinsHelper(self.cs)

    def test_init(self):
        pass

    def test_call_stage_job(self):
        res = self.jt.call_stage_job(self.jh.url,"wewang", self.cs.get_jenkins_token(),self.jh.version,self.jh.metadata_ad, self.jh.pull_spec)
