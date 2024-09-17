import re
import time
import jenkins
import logging
import oar.core.util as util
from jenkins import JenkinsException
from oar.core.exceptions import JenkinsHelperException
from oar.core.configstore import ConfigStore
from oar.core.const import *

logger = logging.getLogger(__name__)


class JenkinsHelper:

    def __init__(self, cs: ConfigStore):
        self._cs = cs
        self.version = util.get_y_release(self._cs.release)
        self.metadata_ad = self._cs.get_advisories().get("metadata")
        # get string errata_numbers like: 115076 115075 115077 115074 115078
        self.errata_numbers = " ".join(
            [str(i) for i in [val for val in self._cs.get_advisories().values()]]
        )
        self.pull_spec = (
            "quay.io/openshift-release-dev/ocp-release:" + self._cs.release + "-x86_64"
        )
        self.server = self.init_jenkins_server()

    def call_stage_job(self):
        try:
            if not self.metadata_ad:
                raise JenkinsException("metadata advisory not found")

            build_url = self.call_build_job(
                JENKINS_JOB_STAGE_PIPELINE, self.pull_spec)
        except JenkinsException as ej:
            raise JenkinsHelperException(
                "call stage pipeline job failed") from ej
        return build_url

    def call_image_consistency_job(self, pull_spec):
        try:
            logger.info(f"triggered a job with {pull_spec}")
            build_url = self.call_build_job(
                "image-consistency-check", pull_spec)
        except JenkinsException as ej:
            raise JenkinsHelperException(
                "call image-consistency-check pipeline job failed"
            ) from ej
        return build_url

    def get_build_status(self, job_name, build_number):
        """
        get job status via build_number
        """

        # job name validation should be done by upstream call in cli interface
        job_status = ""
        try:

            build_info = self.server.get_build_info(job_name, build_number)

            # get payload pull spec from job parameters, compare it with z-stream release version in config store
            # make sure the provided build_number is triggered for current z-stream release

            # loop actions in build info to find job parameters
            params_action = None
            for action in build_info["actions"]:
                if JENKINS_ATTR_CLASS in action and action[JENKINS_ATTR_CLASS] == JENKINS_CLASS_PARAMS:
                    params_action = action
                    break

            if not params_action:
                raise JenkinsHelperException(
                    f"cannot find parameter action for build {job_name}/{build_number}")

            # find param value of payload url
            payload_url = ""
            for param in params_action[JENKINS_ATTR_PARAMS]:
                if param[JENKINS_ATTR_CLASS] == JENKINS_CLASS_STRING and param[JENKINS_ATTR_NAME] in [JENKINS_PARAM_PAYLOAD_URL, JENKINS_PARAM_PULL_SPEC]:
                    payload_url = param[JENKINS_ATTR_VALUE]
                    break

            if not payload_url:
                raise JenkinsHelperException(
                    f"cannot find payload url value in parameters of {job_name}/{build_number}")

            stable_version = self._cs.release
            candidate_version = self._cs.get_candidate_builds().get(
                "x86_64") if self._cs.get_candidate_builds() else "n/a"
            # both stable and candidate build cannot be found in payload url, i.e. this job is not triggered for current z-stream release
            # raise the exception
            if not stable_version in payload_url and not candidate_version in payload_url:
                raise JenkinsHelperException(
                    f"please make sure this build {job_name}/{build_number} is triggered for {stable_version}, cannot find {stable_version} or {candidate_version} in payload url {payload_url}")

            # start to check build status and return
            # check if the jobs is in progress
            if build_info[JENKINS_ATTR_IS_IN_PROGRESS]:
                job_status = JENKINS_JOB_STATUS_IN_PROGRESS
            else:
                job_status = build_info[JENKINS_ATTR_RESULT]

            logger.info(
                f"build status of {job_name}/{build_number} is {job_status}")

        except Exception as e:
            raise JenkinsHelperException(
                f"get job {job_name}/{build_number} status failed"
            ) from e

        return job_status

    def is_job_enqueue(self, job_name):
        """
        check the job if it's in queue
        """
        try:
            queue_info = self.server.get_queue_info()
            for item in queue_info:
                if 'name' in item['task'] and item['task']['name'] == job_name:
                    return True
        except Exception as e:
            raise JenkinsHelperException(
                f"check job queue failed"
            ) from e

        return False

    def call_build_job(self, job_name, pull_spec):
        """
        trigger build job and return build url
        """

        build_info = ""
        try:
            if (job_name == JENKINS_JOB_IMAGE_CONSISTENCY_CHECK):
                parameters_value = {
                    "VERSION": "v" + self.version,
                    "ERRATA_NUMBERS": self.errata_numbers,
                    "PAYLOAD_URL": pull_spec,
                }
            elif (job_name == JENKINS_JOB_STAGE_PIPELINE):
                parameters_value = {
                    "VERSION": self.version,
                    "METADATA_AD": self.metadata_ad,
                    "PULL_SPEC": pull_spec,
                }
            else:
                logger.info(f"{job_name} is not supported")

            # trigger build and get queue item in resp payload
            res = self.server.build_job(job_name, parameters=parameters_value)

            # polling queue item to find our executable url
            queue_item_info = self.server.get_queue_item(res)
            queue_item_link = "%s/queue/item/%s/api/json" % (
                self._cs.get_jenkins_server(), str(res))
            if (queue_item_info[JENKINS_QUEUE_ITEM_ATTR_BLOCKED]):
                build_info = f"a new job triggered by you is pending, you can check queue item link: {queue_item_link}"
            else:
                try:
                    max_count = 3
                    interval = 30
                    for x in range(max_count):
                        queue_item_info = self.server.get_queue_item(res)
                        if (JENKINS_QUEUE_ITEM_ATTR_EXECUTABLE in queue_item_info):
                            build_info = queue_item_info[JENKINS_QUEUE_ITEM_ATTR_EXECUTABLE][JENKINS_QUEUE_ITEM_ATTR_URL]
                            break
                        else:
                            time.sleep(interval)
                except:
                    raise JenkinsHelperException(
                        f"visit {queue_item_link} failed")

                if not build_info:
                    build_info = f"polling queue item {queue_item_link} timeout, please check build url in this item manually"

        except JenkinsException as ej:
            raise JenkinsHelperException(
                f"call {job_name} job failed"
            ) from ej

        return build_info

    def init_jenkins_server(self):
        try:
            return jenkins.Jenkins(
                self._cs.get_jenkins_server(),
                username=self._cs.get_jenkins_username(),
                password=self._cs.get_jenkins_token(),
            )
        except JenkinsException as ej:
            raise JenkinsHelperException(
                "failed to init jenkins server"
            ) from ej
