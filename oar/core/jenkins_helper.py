import re
import time
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
        self.vversion = "v" + self.version
        self.metadata_ad = self._cs.get_advisories()["metadata"]
        # get string errata_numbers like: 115076 115075 115077 115074 115078
        self.errata_numbers = " ".join(
            [str(i) for i in [val for val in self._cs.get_advisories().values()]]
        )
        self.pull_spec = (
            "quay.io/openshift-release-dev/ocp-release:" + self._cs.release + "-x86_64"
        )
        self.zstream_url = self._cs.get_jenkins_server() + "/job/zstreams/"
        self.server = self.init_jenkins_server()
    def call_stage_job(self):
        try:
            build_url = self.call_build_job("Stage-Pipeline")
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException("call stage pipeline job failed") from ej
        return build_url
    
    def call_image_consistency_job(self):
        try:
            build_url = self.call_build_job("image-consistency-check")
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException(
                "call image-consistency-check pipeline job failed"
            ) from ej
        return  build_url

    def get_job_status(self, url, job_name, build_number):
        """
        get job status via build_number
        """
        job_status = ""
        try:
            server = jenkins.Jenkins(
                url,
                username=self._cs.get_jenkins_username(),
                password=self._cs.get_jenkins_token(),
            )
            server.assert_job_exists
            try:
                build_info = server.get_build_info(job_name, build_number)
            except jenkins.JenkinsException as je:
                raise JenkinsHelperException(
                    f"job {job_name}/{build_number} not found"
                ) from je

            pattern = "4.\d+.\d*"
            if (
                build_info["actions"][0]["_class"]
                == "hudson.model.ParametersAction"
            ):
                if job_name == "Stage-Pipeline":
                    payload = build_info["actions"][0]["parameters"][3]["value"]
                else:
                    payload = build_info["actions"][0]["parameters"][2]["value"]
            else:
                if job_name == "Stage-Pipeline":
                    payload = build_info["actions"][1]["parameters"][3]["value"]
                else:
                    payload = build_info["actions"][1]["parameters"][2]["value"]

            match = re.search(pattern, payload)
            if match:
                zstream_version = match.group()
            if zstream_version.find(self._cs.release) != -1:
                # the job is in progress or already finished
                if build_info["building"]:
                    logger.info(
                        f"{job_name} job: {build_number} status is: In Progress"
                    )
                    job_status = "In Progress"
                else:
                    status = server.get_build_info(job_name, build_number)["result"]
                    job_status = status
                    logger.info(f"{job_name} job: {build_number} status is: {status}")
                return job_status
            else:
                logger.error(
                    f"release version in job {job_name}/{build_number} is not [{self._cs.release}], please check job id"
                )
        except JenkinsHelperException:
            raise
        except Exception as e:
            raise JenkinsHelperException(
                f"get job{job_name}:{build_number} status failed"
            ) from e

    def pre_check_build_queue(self,job_name):
        """
        check the job if it's in queue
        """
        try:
            queue_info = self.server.get_queue_info()
            for item in queue_info:
			            if 'name' in item['task'] and item['task']['name'] == job_name:
                                        return True
            return False
        except Exception as e:
            raise JenkinsHelperException(
                f"check build status failed"
            ) from e

    def call_build_job(self,job_name):
        """
        trigger build job and return build url
        """  
        try: 
            if(job_name == "image-consistency-check"):
                parameters_value = {
                    "VERSION": self.vversion,
                    "ERRATA_NUMBERS": self.errata_numbers,
                    "PAYLOAD_URL": self.pull_spec,
                }
            elif(job_name == "Stage-Pipeline"):
                parameters_value = {
                    "VERSION": self.version,
                    "METADATA_AD": self.metadata_ad,
                    "PULL_SPEC": self.pull_spec,
                }
                job_name = "zstreams/" +job_name
            else:
                logger.info("please provide correct job name")
            res = self.server.build_job(
                job_name,
                parameters=parameters_value,
            )
            queue_item_info = self.server.get_queue_item(res)
            queue_item_link = self._cs.get_jenkins_server() +"/queue/item/"+ str(res) +"/api/json?depth=0"
            if(queue_item_info['blocked']):
                return f"a new job triggered by you is pending, you can check queue item link: {queue_item_link}"
            else:
                try: 
                    max_count = 3
                    internval = 30
                    for x in range(max_count):
                        queue_item_info = self.server.get_queue_item(res)
                        if ('executable' in queue_item_info):
                            return queue_item_info['executable']['url']
                            break
                        else:
                            time.sleep(internval)
                except:
                    raise JenkinsHelperException(f"visit {queue_item_link} failed")
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException(
                f"call {job_name} job failed"
            ) from ej
    
    def init_jenkins_server(self):
        try: 
            return jenkins.Jenkins(
                self._cs.get_jenkins_server(),
                username=self._cs.get_jenkins_username(),
                password=self._cs.get_jenkins_token(),
            ) 
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException(
                "failed to init jenkins server"
            ) from ej
