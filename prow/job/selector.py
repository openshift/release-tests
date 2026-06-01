import logging
import tempfile
from datetime import datetime

import requests
import yaml
from git import Actor, Repo

from .controller import Architectures, GithubUtil
from .github_auth import (
    REPO_OPENSHIFT_RELEASE,
    create_release_tests_pr_with_approval,
    release_tests_bot_email,
    release_tests_clone_url,
)

logger = logging.getLogger(__name__)


class AutoReleaseJobs():

    JOB_FILE_DIR = "ci-operator/jobs/openshift/openshift-tests-private"
    CONFIG_FILE_DIR = "ci-operator/config/openshift/openshift-tests-private"

    # TODO: currently we only have automated release jobs for amd64
    # need to support getting jobs for other arches
    def __init__(self, release) -> None:
        if not release:
            raise ValueError("param <release> is mandatory")
        self._release = release
        self.release_main = GithubUtil(REPO_OPENSHIFT_RELEASE)

    def get_jobs(self) -> list[str]:
        # get automated release jobs from github repo openshift/release by different releases
        # currently only release 4.15,4.16 are supported.
        auto_release_jobs = []
        # check whether config file exists for the requested release
        config_file_path = f"{self.CONFIG_FILE_DIR}/openshift-openshift-tests-private-release-{self._release}__automated-release.yaml"
        if not self.release_main.file_exists(config_file_path):
            raise FileNotFoundError(
                f"automate release job file cannot be found for release {self._release}")

        # because the file size is big, the raw content won't be sent back via api call
        # we need to download the raw file content separately
        job_file_path = f"{self.JOB_FILE_DIR}/openshift-openshift-tests-private-release-{self._release}-periodics.yaml"
        raw_data_url = self.release_main.get_files(
            job_file_path).download_url
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


class LocalGitRepo():

    def __init__(self, repo_url, default_branch="main"):
        self._default_branch = default_branch
        self._repo_name = repo_url.split("/")[-1].replace(".git", "")
        self._repo_local_dir = tempfile.NamedTemporaryFile(
            dir="/tmp", prefix="release-tests-").name
        self._repo = Repo.clone_from(repo_url, self._repo_local_dir)

    def commit_file_change(self, relative_file_path, file_content, actor_name, actor_email):
        if not file_content:
            raise ValueError("file content is empty, cannot apply this change")

        local_file = f"{self._repo_local_dir}/{relative_file_path}"

        for remote in self._repo.remotes:
            remote.fetch()
        self._repo.git.merge(f"origin/{self._default_branch}")

        self._repo.config_writer().set_value("push", "default", "current")
        self.branch_name = "-".join(["autobranch",
                                     datetime.now().strftime("%y%m%d%H%M%S")])
        branch = self._repo.create_head(self.branch_name)
        branch.checkout()
        with open(local_file, "w") as f:
            f.write(file_content)
        self._repo.index.add(relative_file_path)
        commit_actor = Actor(name=actor_name, email=actor_email)
        self._repo.index.commit(message=f"Changes for file {relative_file_path}",
                                author=commit_actor, committer=commit_actor)
        self._repo.remote().push()


class TestJobRegistryUpdater():

    def __init__(self, release, arch=Architectures.AMD64):
        self._local_git_repo = LocalGitRepo(release_tests_clone_url())
        self._release = release
        self._arch = arch
        self._file_path = f"_releases/ocp-{self._release}-test-jobs-{self._arch}.json"

    def update(self, file_content):
        if not file_content:
            raise ValueError("file content is mandatory")

        self._local_git_repo.commit_file_change(
            self._file_path,
            file_content,
            "ERT Writer App",
            release_tests_bot_email(),
        )

        create_release_tests_pr_with_approval(
            f"Update test job registry for {self._release}-{self._arch} - "
            f"{datetime.now().strftime('%y%m%d%H%M')}",
            "Update job registry with rotated job list",
            self._local_git_repo.branch_name,
        )
