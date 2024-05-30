import logging
import requests
import yaml
import tempfile
import os
from .controller import GithubUtil
from .controller import Architectures
from pathlib import Path
from github import Auth, Github, GithubIntegration
from github.Installation import Installation
from github.Repository import Repository
from git import Repo, Actor
from datetime import datetime

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
        self.release_master = GithubUtil("openshift/release")

    def get_jobs(self) -> list[str]:
        # get automated release jobs from github repo openshift/release by different releases
        # currently only release 4.15,4.16 are supported.
        auto_release_jobs = []
        # check whether config file exists for the requested release
        config_file_path = f"{self.CONFIG_FILE_DIR}/openshift-openshift-tests-private-release-{self._release}__automated-release.yaml"
        if not self.release_master.file_exists(config_file_path):
            raise FileNotFoundError(
                f"automate release job file cannot be found for release {self._release}")

        # because the file size is big, the raw content won't be sent back via api call
        # we need to download the raw file content separately
        job_file_path = f"{self.JOB_FILE_DIR}/openshift-openshift-tests-private-release-{self._release}-periodics.yaml"
        raw_data_url = self.release_master.get_files(
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


class GithubApp():

    def __init__(self, app_private_key_path, app_id, app_owner, app_repo):
        self.app_id = app_id
        self.app_owner = app_owner
        self.app_repo = app_repo
        app_private_key_file = Path(app_private_key_path)
        if app_private_key_file.exists():
            app_private_key = app_private_key_file.expanduser().read_text()
            app_auth = Auth.AppAuth(app_id, app_private_key)
            github_integ = GithubIntegration(auth=app_auth)
            github_install = github_integ.get_repo_installation(
                app_owner, app_repo)
            self._github_api = github_install.get_github_for_installation()
            self._repo = self._github_api.get_repo(f"{app_owner}/{app_repo}")
        else:
            raise FileNotFoundError(
                f"app private key file not found: {app_private_key_path}")

    def create_pull_request_and_approve(self, title, body, base, head):
        pr = self._repo.create_pull(
            title, body, base, head, maintainer_can_modify=False)
        pr.add_to_labels("lgtm", "approved")

    def get_repo_url(self):
        return f"https://x-access-token:{self._github_api._Github__requester.auth.token}@github.com/{self.app_owner}/{self.app_repo}.git"

    def get_email(self):
        return f"{self.app_id}+{self.app_repo}-github-app-{self.app_owner}[bot]@users.noreply.github.com"


class LocalGitRepo():

    def __init__(self, repo_url):
        self._default_branch = "master"
        self._repo_name = repo_url.split()[-1].replace(".git", "")
        self._repo_local_dir = tempfile.NamedTemporaryFile(
            dir="/tmp", prefix="release-tests-").name
        # repo initialization
        self._repo = Repo.clone_from(repo_url, self._repo_local_dir)

    def add_remote(self, name, url):
        self._repo.create_remote(name, url)

    def commit_file_change(self, relative_file_path, file_content, actor_name, actor_email):
        if not file_content:
            raise ValueError("file content is empty, cannot apply this change")

        local_file = f"{self._repo_local_dir}/{relative_file_path}"
        # if not Path(local_file).exists():
        #     raise FileNotFoundError(
        #         f"file {relative_file_path} not found in repo {self._repo_name}")

        # fetch all remotes
        for remote in self._repo.remotes:
            remote.fetch()
            if remote.name.lower() == "upstream":
                self._repo.git.merge(f"{remote.name}/{self._default_branch}")

        # set push config
        self._repo.config_writer().set_value("push", "default", "current")
        # create new branch with datetime suffix
        self.branch_name = "-".join(["autobranch",
                                     datetime.now().strftime("%y%m%d%H%M%S")])
        branch = self._repo.create_head(self.branch_name)
        branch.checkout()
        # make file change and commit
        with open(local_file, "w") as f:
            f.write(file_content)
        # add changed file and commit
        self._repo.index.add(relative_file_path)
        commit_actor = Actor(name=actor_name, email=actor_email)
        self._repo.index.commit(message=f"Changes for file {relative_file_path}",
                                author=commit_actor, committer=commit_actor)
        # push local change to remote
        self._repo.remote().push()


class TestJobRegistryUpdater():

    def __init__(self, release, arch=Architectures.AMD64):
        app_private_key = os.environ.get("APP_PRIVATE_KEY")
        if not app_private_key:
            raise ValueError("env variable APP_PRIVATE_KEY is mandatory")
        app_id = 897744
        app_local_account = "rioliu-rh"
        app_upstream_account = "openshift"
        app_repo = "release-tests"
        self._app_of_forked_repo = GithubApp(
            app_private_key, app_id, app_local_account, app_repo)
        self._app_of_upstream_repo = GithubApp(
            app_private_key, app_id, app_upstream_account, app_repo)
        self._local_git_repo = LocalGitRepo(
            self._app_of_forked_repo.get_repo_url())
        self._release = release
        self._arch = arch
        self._file_path = f"_releases/ocp-{self._release}-test-jobs-{self._arch}.json"

    def update(self, file_content):
        if not file_content:
            raise ValueError("file content is mandatory")

        self._local_git_repo.add_remote(
            "upstream", self._app_of_upstream_repo.get_repo_url())
        self._local_git_repo.commit_file_change(
            self._file_path, file_content, "QE Github App", self._app_of_forked_repo.get_email())

        self._app_of_upstream_repo.create_pull_request_and_approve(
            f"Update test job registry for {self._release}-{self._arch} - {datetime.now().strftime('%y%m%d%H%M')}",
            "Update job registry with rotated job list", "master", f"{self._app_of_forked_repo.app_owner}:{self._local_git_repo.branch_name}")
