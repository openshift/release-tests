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

    def __init__(self, release):
        self._release = release
        self._build_file_for_nightly = f"_releases/latest_{self._release}_nightly.json"
        self.validate_required_info()
        self.jobs = Jobs()
        self.github = GithubUtil("openshift/release-tests", "record")
        
    def get_latest_build(self):

        try:
            url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{self._release}.0-0.nightly/latest"
            logger.info(f"Getting latest nightly build from url {url}")
            resp = requests.get(url)
            resp.raise_for_status()
        except RequestException as re:
            logger.error(f"get latest nightly build error {re}")
            raise

        if resp.text:
            logger.info(f"latest nightly build info of {self._release} is:\n{resp.text}")
            # if build file on github does not exist, create it
            if not self.github.file_exists(self._build_file_for_nightly):
                self.github.push_file(data=resp.text, path=self._build_file_for_nightly)
            
        return Build(resp.text)
    
    def get_current_build(self):
        data = self.github.get_file_content(self._build_file_for_nightly)
        return Build(data)

    def trigger_prow_jobs(self):
        pass

    def aggregate_test_results(self):
        pass

    def validate_required_info(self):
        if os.environ.get("APITOKEN") is None:
            raise SystemExit("Cannot find environment variable APITOKEN")
        if os.environ.get("GITHUB_TOKEN") is None:
            raise SystemExit("Cannot find environment variable GITHUB_TOKEN")
        if self._release not in self.VALID_RELEASES:
            raise SystemExit(f"{self._release} is not supported")
        
    def start(self):
        # get latest build info
        latest = self.get_latest_build()
        current = self.get_current_build()
        # compare whether current = latest, if latest is newer than current trigger prow jobs
        if latest.equals(current):
            logger.info(f"current build is same as latest build {latest.name}, no diff found")
        else:
            logger.info(f"found new build {latest.name}, will trigger required test jobs")
        


class Build(object):

    def __init__(self, data):
        obj = json.loads(data)
        self._name = obj["name"]
        self._phase = obj["phase"]
        self._pull_spec = obj["pullSpec"]
        self._download_url = obj["downloadURL"]

    @property
    def name(self):
        return self._name
    
    @property
    def phase(self):
        return self._phase
    
    @property
    def pull_spec(self):
        return self._pull_spec
    
    @property
    def download_url(self):
        return self.download_url
    
    def equals(self, build):
        if isinstance(build, Build):
            return self.name == build.name
        
        return False
    

class GithubUtil:

    def __init__(self, repo, branch="master"):
        token = os.environ.get("GITHUB_TOKEN")
        auth = Auth.Token(token)
        self._client = Github(auth=auth)
        self._repo = self._client.get_repo(repo)
        self._branch = branch

    def push_file(self, data, path):
        if self.file_exists(path):
            content = self.get_file_content(path)
            logger.info(f"updating file {content.path}")
            self._repo.update_file(path=content.path,
                                   message="update file content",
                                   content=data,
                                   branch=self._branch,
                                   sha=content.sha)
        else:
            logger.info(f"creating file {path}")
            self._repo.create_file(path=path,
                                   message="create new file",
                                   content=data,
                                   branch=self._branch)
            
    def get_file_content(self, path):
        content = self._repo.get_contents(path=path, ref=self._branch)
        logger.debug(f"file content of {content.path} is:\n{content.decoded_content.decode('utf-8')}")
        return content.decoded_content.decode("utf-8")
        
    def file_exists(self, path):
        try:
            self._repo.get_contents(path=path, ref=self._branch)
            logger.info(f"file {path} can be found")
        except UnknownObjectException:
            logger.info(f"file {path} not found")
            return False
        
        return True

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
def start_controller(release):
    JobController(release).start()

cli.add_command(start_controller)


    

