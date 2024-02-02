#!/usr/bin/env python3

import requests
import json
import logging
import os
import click
from .job import Jobs
from github import *
from requests.exceptions import RequestException
from github.GithubException import UnknownObjectException

logger = logging.getLogger(__name__)

class JobController:

    VALID_RELEASES = ["4.11", "4.12", "4.13", "4.14", "4.15", "4.16"]

    def __init__(self, release, nightly=True, trigger_prow_job=True):
        self._release = release[:-2] if len(release.split("."))==3 else release
        self._nightly = nightly
        self._trigger_prow_job = trigger_prow_job
        self._build_type = 'nightly' if self._nightly else 'stable'
        self._build_file_for_nightly = f"_releases/ocp-latest-{self._release}-nightly.json"
        self._build_file_for_stable = f"_releases/ocp-latest-{self._release}-stable.json"
        self._build_file = self._build_file_for_nightly if self._nightly else self._build_file_for_stable
        self._job_file = f"_releases/ocp-{self._release}-test-jobs.json"
        self.validate_required_info()
        self.jobs = Jobs()
        self.release_test_record = GithubUtil("openshift/release-tests", "record")
        self.release_test_master = GithubUtil("openshift/release-tests")
        
    def get_latest_build(self):

        try:
            if self._nightly:
                url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{self._release}.0-0.nightly/latest"
            else:
                url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/latest?prefix={self._release}"
                if requests.get(url).status_code == 404: # if latest stable build is valid and not found, i.e. 4.16, we check releasestream 4-dev-preview instead
                    url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-dev-preview/latest"

            logger.info(f"Getting latest {self._build_type} build for {self._release} ...")
            resp = requests.get(url)
            resp.raise_for_status()
        except RequestException as re: 
            logger.error(f"Get latest  {self._build_type} build error {re}")
            raise

        if resp.text:
            logger.info(f"Latest  {self._build_type} build of {self._release} is:\n{resp.text}")
            # if record file does not exist, create it on github repo
            if not self.release_test_record.file_exists(self._build_file):
                self.release_test_record.push_file(data=resp.text, path=self._build_file)
            
        return Build(resp.text)
    
    def get_current_build(self):
        data = self.release_test_record.get_file_content(self._build_file)
        return Build(data)
    
    def update_current_build(self, build):
        if build.raw_data:
            self.release_test_record.push_file(build.raw_data, self._build_file)

        logger.info(f"current build info is updated on repo")

    def trigger_prow_jobs(self):

        jobs = self.get_test_jobs()
        if len(jobs):
            for job in jobs:
                if job.disabled:
                    continue
                current = self.get_current_build()
                if job.upgrade:
                    self.jobs.run_job(job_name=job.prow_job, upgrade_to=current.pull_spec)
                else:
                    self.jobs.run_job(job_name=job.prow_job, payload=current.pull_spec)
                
                logger.info(f"Triggered prow job {job.prow_job} with build {current.name}")

    def aggregate_test_results(self):
        pass

    def validate_required_info(self):
        if os.environ.get("APITOKEN") is None:
            raise SystemExit("Cannot find environment variable APITOKEN")
        if os.environ.get("GITHUB_TOKEN") is None:
            raise SystemExit("Cannot find environment variable GITHUB_TOKEN")
        if self._release not in self.VALID_RELEASES:
            raise SystemExit(f"{self._release} is not supported")
        
    def get_test_jobs(self):

        test_jobs = []
        if self.release_test_master.file_exists(self._job_file):
            file_content = self.release_test_master.get_file_content(path=self._job_file)
            if file_content:
                json_data = json.loads(file_content)
                jobs = json_data[self._build_type]
                for job in jobs:
                    test_jobs.append(TestJob(job))

        return test_jobs
        
    def start(self):
        # get latest build info
        latest = self.get_latest_build()
        current = self.get_current_build()
        # compare whether current = latest, if latest is newer than current trigger prow jobs
        if latest.equals(current):
            logger.info(f"Current build is same as latest build {latest.name}, no diff found")
        else:
            logger.info(f"Found new build {latest.name}")
            self.update_current_build(latest)
            if self._trigger_prow_job:
                self.trigger_prow_jobs()
            else:
                logger.warning("Won't trigger prow jobs since control flag [--trigger-prow-job] is false")


class Build():

    def __init__(self, data):
        self._raw_data = data
        self._json_data = json.loads(data)

    @property
    def name(self):
        return self._json_data["name"]
    
    @property
    def phase(self):
        return self._json_data["phase"]

    @property
    def pull_spec(self):
        return self._json_data["pullSpec"]
    
    @property
    def download_url(self):
        return self._json_data["downloadURL"]
    
    @property
    def raw_data(self):
        return self._raw_data
    
    def equals(self, build):
        if isinstance(build, Build):
            return self.name == build.name
        
        return False
    
class TestJob():

    def __init__(self, data):
        self._raw_data = data
        self._json_data = json.loads(data)

    @property
    def prow_job(self):
        return self._json_data["prowJob"]
    
    @property
    def disabled(self):
        # default value is false
        return bool(self._json_data["disabled"]) if "disabled" in self._json_data else False
    
    @property
    def upgrade(self):
        # default value is false
        return bool(self._json_data["upgrade"]) if "upgrade" in self._json_data else False
    
    @property
    def optional(self):
        # default value is false
        return bool(self._json_data["optional"]) if "optional" in self._json_data else False
    

class GithubUtil:

    def __init__(self, repo, branch="master"):
        token = os.environ.get("GITHUB_TOKEN")
        auth = Auth.Token(token)
        self._client = Github(auth=auth)
        self._repo = self._client.get_repo(repo)
        self._branch = branch

    def push_file(self, data, path):
        if self.file_exists(path):
            content = self._repo.get_contents(path=path, ref=self._branch)
            logger.info(f"Updating file {content.path}")
            self._repo.update_file(path=content.path,
                                   message="update file content",
                                   content=data,
                                   branch=self._branch,
                                   sha=content.sha)
            logger.info("File is updated successfully")
        else:
            logger.info(f"Creating file {path}")
            self._repo.create_file(path=path,
                                   message="create new file",
                                   content=data,
                                   branch=self._branch)
            logger.info("File is created successfully")
            
    def get_file_content(self, path):
        content = self._repo.get_contents(path=path, ref=self._branch)
        logger.debug(f"file content of {content.path} is:\n{content.decoded_content.decode('utf-8')}")
        return content.decoded_content.decode("utf-8")
        
    def file_exists(self, path):
        try:
            self._repo.get_contents(path=path, ref=self._branch)
            logger.info(f"File {path} can be found")
        except UnknownObjectException:
            logger.info(f"File {path} not found")
            return False
        
        return True
    
    def delete_file(self, path):
        if self.file_exists(path):
            content = self._repo.get_contents(path=path, ref=self._branch)
            logger.info(f"Deleting file {path}")
            self._repo.delete_file(path=content.path,
                                   message="delete file",
                                   sha=content.sha,
                                   branch=self._branch)
            logger.info("File is deleted successfully")
        else:
            logger.info(f"File {path} not found")

@click.group()
@click.option("--debug/--no-debug", help="enable debug logging")
def cli(debug):
    logging.basicConfig(
        format="%(asctime)s: %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        level=logging.DEBUG if debug else logging.INFO,
    )

@click.command
@click.option("-r", "--release", help="y-stream release number e.g. 4.15", required=True)
@click.option("--nightly/--no-nightly", help="run controller for nightly or stable build, default is nightly", default=True)
@click.option("--trigger-prow-job", help="trigger prow job if new build is found", default=True)
def start_controller(release, nightly, trigger_prow_job):
    JobController(release, nightly, trigger_prow_job).start()

cli.add_command(start_controller)


    

