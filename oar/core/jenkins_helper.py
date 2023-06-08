import jenkins
import logging
from oar.core.config_store import ConfigStore
import oar.core.util as util
from oar.core.exceptions import JenkinsHelperException

logger = logging.getLogger(__name__)
class JenkinsHelper:
    def __init__(self, cs: ConfigStore):
        self._cs = cs
        self.version = util.get_y_release(self._cs.release)
        self.metadata_ad = self._cs.get_advisories()["metadata"]
        self.pull_spec = "quay.io/openshift-release-dev/ocp-release:" +self._cs.release+ "-x86_64"
        self.url = self._cs.get_jenkins_server()+ "/job/zstreams/"
        self.username=self._cs.get_jenkins_username()
        self.token=self._cs.get_jenkins_token()
    def call_stage_job(self, url, username, token, version, metadata_ad, pull_spec): 
        try:
            server = jenkins.Jenkins(url, username=username, password=token)
            server.build_job("Stage-Pipeline",parameters={'VERSION': version,'METADATA_AD':metadata_ad,'PULL_SPEC':pull_spec})
        except jenkins.JenkinsException as ej:   
            raise JenkinsHelperException("call stage pipeline job failed") from ej
        last_build_number = server.get_job_info("Stage-Pipeline")['lastBuild']['number']
        if not last_build_number:
            raise JenkinsHelperException("Trigger stage pipeline job failed: cannot get latest build number")
        return url+ "job/Stage-Pipeline/" +str(last_build_number)
