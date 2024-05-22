from ast import List
import logging
import requests
import yaml
from .controller import GithubUtil
from github.GithubException import UnknownObjectException
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


class AutoReleaseJobs():

    def __init__(self, release) -> None:
        if not release:
            raise ValueError("param <release> is mandatory")
        self._release = release

        # env var GITHUB_TOKEN is required
        self.release_master = GithubUtil("openshift/release")

    def get_jobs(self) -> list[str]:
        # get automated release jobs from github repo openshift/release by different releases
        # currently only release 4.15,4.16 are supported.
        auto_release_jobs = []
        # check whether job file exists for the requested release
        file_path = f"ci-operator/jobs/openshift/openshift-tests-private/openshift-openshift-tests-private-release-{self._release}-periodics.yaml"
        if not self.release_master.file_exists(file_path):
            raise FileNotFoundError(
                f"automate release job file cannot be found for release {self._release}")

        # because the file size is too big, the raw content won't be sent back via api call
        # we need to download the raw file content separately
        raw_data_url = self.release_master.get_files(file_path).download_url
        resp = requests.get(raw_data_url)
        resp.raise_for_status()

        file_content = resp.text
        if file_content:
            # parse yaml file to get all the jobs with key word automated-release
            yaml_file = yaml.safe_load(file_content)
            for job_obj in yaml_file.get("periodics"):
                # TODO:currently we just need the job name, if the selection policy needs more job info
                # we can put job object to the list in the future
                job_name = job_obj.get("name")
                if "automated-release" in job_name:
                    auto_release_jobs.append(job_name)

        return auto_release_jobs
