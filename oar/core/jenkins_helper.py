import re
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

    def call_stage_job(self):
        try:
            server = jenkins.Jenkins(
                self.zstream_url,
                username=self._cs.get_jenkins_username(),
                password=self._cs.get_jenkins_token(),
            )
            server.build_job(
                "Stage-Pipeline",
                parameters={
                    "VERSION": self.version,
                    "METADATA_AD": self.metadata_ad,
                    "PULL_SPEC": self.pull_spec,
                },
            )
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException("call stage pipeline job failed") from ej
        last_build_number = server.get_job_info("Stage-Pipeline")["lastBuild"]["number"]
        if not last_build_number:
            raise JenkinsHelperException(
                "Trigger stage pipeline job failed: cannot get latest build number"
            )
        return self.zstream_url + "job/Stage-Pipeline/" + str(last_build_number)

    def call_image_consistency_job(self):
        try:
            server = jenkins.Jenkins(
                self._cs.get_jenkins_server(),
                username=self._cs.get_jenkins_username(),
                password=self._cs.get_jenkins_token(),
            )
            server.build_job(
                "image-consistency-check",
                parameters={
                    "VERSION": self.vversion,
                    "ERRATA_NUMBERS": self.errata_numbers,
                    "PAYLOAD_URL": self.pull_spec,
                },
            )
        except jenkins.JenkinsException as ej:
            raise JenkinsHelperException(
                "call image-consistency-check pipeline job failed"
            ) from ej
        last_build_number = server.get_job_info("image-consistency-check")["lastBuild"][
            "number"
        ]
        if not last_build_number:
            raise JenkinsHelperException(
                "Trigger image check job failed: cannot get latest build number"
            )
        return (
            self._cs.get_jenkins_server()
            + "/job/image-consistency-check/"
            + str(last_build_number)
        )

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
