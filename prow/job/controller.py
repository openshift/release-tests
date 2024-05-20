#!/usr/bin/env python3

import requests
import json
import logging
import os
import re
import click
import subprocess
import shlex
from .job import Jobs
from github import Auth, Github
from github.GithubException import UnknownObjectException
from requests.exceptions import RequestException
from subprocess import CalledProcessError

logger = logging.getLogger(__name__)

# declare global constants
JOB_TYPE_NIGHTLY = "nightly"
JOB_TYPE_STABLE = "stable"
REPO_RELEASE_TESTS = "openshift/release-tests"
BRANCH_RECORD = "record"
DIR_RELEASE = "_releases"
SYS_ENV_VAR_GITHUB_TOKEN = "GITHUB_TOKEN"
SYS_ENV_VAR_API_TOKEN = "APITOKEN"
VALID_RELEASES = ["4.11", "4.12", "4.13", "4.14", "4.15", "4.16"]


class Architectures():

    AMD64 = "amd64"
    ARM64 = "arm64"
    MULTI = "multi"
    PPC64LE = "ppc64le"
    S390X = "s390x"
    VALID_ARCHS = [AMD64, ARM64, MULTI, PPC64LE, S390X]

    @staticmethod
    def fromString(arch):
        if arch and arch in Architectures.VALID_ARCHS:
            return arch
        raise ValueError(f"invalid architecture {arch}")

    @staticmethod
    def fromBuild(build):
        for arch in Architectures.VALID_ARCHS:
            if arch in build:
                return arch

        return Architectures.AMD64


class ReleaseStreamURLResolver():

    def __init__(self, release, nightly=True, arch=Architectures.AMD64):
        self._arch = Architectures.fromString(arch)
        self._nightly = nightly
        self._release = release

    def get_url_for_latest(self):
        base_url = f"https://{self._arch}.ocp.releases.ci.openshift.org/api/v1/releasestream"
        suffix = "" if self._arch == Architectures.AMD64 else f"-{self._arch}"
        releasestream = (
            f"{self._release}.0-0.nightly" if self._nightly else f"4-stable") + suffix

        if self._nightly:
            url = f"{base_url}/{releasestream}/latest"
        else:
            url = f"{base_url}/{releasestream}/latest?prefix={self._release}"
            # if stable build is not available for latest release, use dev preview releasestream instead
            if requests.get(url).status_code == 404:
                releasestream = "4-dev-preview" + suffix
                url = f"{base_url}/{releasestream}/latest"

        return url

    @staticmethod
    def get_url_for_build(build, arch):
        # the arch can be found in build string of nightly
        # but it does not work for stable build, so param arch is needed here.
        url_resolver = ReleaseStreamURLResolver(
            build[:4], "nightly" in build, arch)

        return url_resolver.get_url_for_latest().replace("latest", f"release/{build}")


class Build():

    def __init__(self, data):
        self._raw_data = data
        self._json_data = data if isinstance(data, dict) else json.loads(data)

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

    def __str__(self):
        return self.name

    def to_dict(self):
        return self._json_data


class TestJob():

    def __init__(self, data):
        self._json_data = data if isinstance(data, dict) else json.loads(data)

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

    @property
    def retries(self):
        # value should be odd numbers e.g. 3,5,7
        # default value is 3, if the attribute is not present
        retries = 0
        if "retries" not in self._json_data:
            retries = 3
        else:
            num = self._json_data.get("retries")
            if num and str(num).isdigit():
                num = int(num)
                retries = num if num % 2 != 0 else num+1
            else:
                retries = 3

        return retries


class JobController:

    def __init__(self, release, nightly=True, trigger_prow_job=True, arch=Architectures.AMD64):
        self._release = release[:-
                                2] if len(release.split(".")) == 3 else release
        validate_required_info(release)
        self._nightly = nightly
        self._trigger_prow_job = trigger_prow_job
        self._arch = Architectures.fromString(arch)
        self._build_type = 'nightly' if self._nightly else 'stable'
        self._build_file_for_nightly = f"{DIR_RELEASE}/ocp-latest-{self._release}-nightly-{self._arch}.json"
        self._build_file_for_stable = f"{DIR_RELEASE}/ocp-latest-{self._release}-stable-{self._arch}.json"
        self._build_file = self._build_file_for_nightly if self._nightly else self._build_file_for_stable
        self.job_api = Jobs()
        self.job_registry = TestJobRegistry(self._arch)
        self.url_resolver = ReleaseStreamURLResolver(
            self._release, self._nightly, self._arch)
        self.release_test_record = GithubUtil(
            REPO_RELEASE_TESTS, BRANCH_RECORD)
        self.release_test_master = GithubUtil(REPO_RELEASE_TESTS)

    def get_latest_build(self):

        try:
            logger.info(
                f"Getting latest {self._build_type} build for {self._release} ...")
            resp = requests.get(self.url_resolver.get_url_for_latest())
            resp.raise_for_status()
        except RequestException as re:
            logger.error(f"Get latest {self._build_type} build error {re}")
            raise

        if resp.text:
            logger.info(
                f"Latest {self._build_type} build of {self._release} is:\n{resp.text}")
            # if record file does not exist, create it on github repo
            if not self.release_test_record.file_exists(self._build_file):
                self.release_test_record.push_file(
                    data=resp.text, path=self._build_file)

        return Build(resp.text)

    def get_current_build(self):
        data = self.release_test_record.get_file_content(self._build_file)
        return Build(data)

    def update_current_build(self, build):
        if build.raw_data:
            self.release_test_record.push_file(
                build.raw_data, self._build_file)

        logger.info(f"current build info is updated on repo")

    def trigger_prow_jobs(self, build: Build):

        test_jobs = self.job_registry.get_test_jobs(
            self._release, self._nightly)
        test_result = []
        if len(test_jobs):
            for test_job in test_jobs:
                if test_job.disabled:
                    logger.info(
                        f"Won't trigger prow job {test_job}, it is disabled")
                    continue

                prow_job_id = self.trigger_prow_job(test_job, build)

                job_item = {}
                if prow_job_id:
                    job_item["jobName"] = test_job.prow_job
                    job_item["firstJob"] = {"jobID": prow_job_id}
                    test_result.append(job_item)
                else:
                    logger.error(
                        f"Trigger prow job {test_job.prow_job} with build {build.name} failed, no prow job id returned")

            if len(test_result):
                data = json.dumps(
                    {"result": test_result, "build": build.to_dict()}, indent=2)
                logger.debug(f"Test result file content {data}")
                file_path = f"{DIR_RELEASE}/ocp-test-result-{build.name}-{self._arch}.json"
                self.release_test_record.push_file(data=data, path=file_path)
                logger.info(
                    f"Test result of {build.name} is saved to {file_path}")

    def trigger_prow_job(self, test_job, build):

        logger.info(
            f"Start to trigger prow job {test_job.prow_job} ...\n")
        if test_job.upgrade:
            prow_job_id = self.job_api.run_job(
                job_name=test_job.prow_job, upgrade_to=build.pull_spec, upgrade_from=None, payload=None)
        else:
            prow_job_id = self.job_api.run_job(
                job_name=test_job.prow_job, payload=build.pull_spec, upgrade_from=None, upgrade_to=None)
        logger.info(
            f"Triggered prow job {test_job.prow_job} with build {build.name}, job id={prow_job_id}\n")

        return prow_job_id

    def start(self):
        # get latest build info
        latest = self.get_latest_build()
        current = self.get_current_build()
        # compare whether current = latest, if latest is newer than current trigger prow jobs
        if latest.equals(current):
            logger.info(
                f"Current build is same as latest build {latest.name}, no diff found")
        else:
            logger.info(f"Found new build {latest.name}")
            self.update_current_build(latest)
            if self._trigger_prow_job:
                self.trigger_prow_jobs(latest)
            else:
                logger.warning(
                    "Won't trigger prow jobs since control flag [--trigger-prow-job] is false")


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

    def get_files(self, path):
        return self._repo.get_contents(path=path, ref=self._branch)

    def get_file_content(self, path):
        content = self._repo.get_contents(path=path, ref=self._branch)
        decoded_content = content.decoded_content.decode('utf-8')
        logger.debug(
            f"file content of {content.path} is:\n{decoded_content}")
        return decoded_content

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


class TestJobRegistry():

    def __init__(self, arch=Architectures.AMD64):
        self.release_tests_master = GithubUtil(REPO_RELEASE_TESTS)
        self._registry = {}
        self._arch = Architectures.fromString(arch)
        self.init()

    def init(self):
        logger.info("Initializing test job registry ...")

        contents = self.release_tests_master.get_files(DIR_RELEASE)
        for content in contents:
            matched_path = re.search(
                r'ocp-\d\.\d+-test-jobs-{}.json'.format(self._arch), content.path)
            if matched_path:
                release = re.search(r'\d\.\d+', matched_path.group()).group()
                file_content = self.release_tests_master.get_file_content(
                    content.path)
                self._registry[release] = json.loads(
                    file_content)
                logger.info(
                    f"Test job definitions for {release}-{self._arch} is initialized")

        logger.info("Test job registry is initialized")

    def get_test_jobs(self, release, nightly):

        test_jobs = []
        build_type = JOB_TYPE_NIGHTLY if nightly else JOB_TYPE_STABLE
        if release not in self._registry:
            logger.warning(f"no test job definition of {release} found")
            return test_jobs
        json_data = self._registry[release]
        if json_data:
            jobs = json_data[build_type]
            for job in jobs:
                test_jobs.append(TestJob(job))

        return test_jobs

    def get_test_job(self, release, nightly, job_name):

        test_job = None
        jobs = self.get_test_jobs(release, nightly)
        if len(jobs):
            filtered_jobs = [j for j in jobs if j.prow_job == job_name]
            if len(filtered_jobs):
                test_job = filtered_jobs[0]
            else:
                logger.info(
                    f"Cannot find test job {job_name} in {release} definition")

        return test_job


class ProwJobResult():

    def __init__(self, job_data):
        self._result = None
        self.job_api = Jobs()
        if "jobCompletionTime" in job_data:
            self.from_dict(job_data)
        else:
            self.fetch(job_data.get("jobID"))

    @property
    def job_id(self):
        return self._result.get("jobID")

    @property
    def job_state(self):
        return self._result.get("jobState")

    @property
    def job_url(self):
        return self._result.get("jobURL")

    @property
    def job_start_time(self):
        return self._result.get("jobStartTime")

    @property
    def job_completion_time(self):
        return self._result.get("jobCompletionTime")

    def is_completed(self):
        return bool(self.job_completion_time)

    def is_failed(self):
        return self.job_state == "failure" or self.job_state == "aborted"

    def is_success(self):
        return self.job_state == "success"

    def is_pending(self):
        return self.job_state == "pending"

    def not_found(self):
        return self._result is None

    def to_dict(self):
        return {k: v for k, v in self._result.items() if v is not None and k != "jobName"}

    def from_dict(self, result):
        if result:
            self._result = result
        return self

    def fetch(self, job_id):
        try:
            self.from_dict(self.job_api.get_job_results(job_id))
        except Exception as e:
            logger.error(f"fetch job result error: {e}")
        return self


class TestJobResult():

    def __init__(self, job_data):
        self._result = job_data
        self._retried_jobs: list[ProwJobResult] = []
        self._first_job: ProwJobResult = None
        self.job_api = Jobs()

    @property
    def job_name(self):
        return self._result.get("jobName")

    @property
    def first_job(self):
        if self._first_job is None:
            self._first_job = ProwJobResult(self._result.get("firstJob"))

        return self._first_job

    @property
    def retried_jobs(self):
        if len(self._retried_jobs) == 0:
            retried_jobs = self._result.get("retriedJobs")
            if retried_jobs and len(retried_jobs):
                for job in retried_jobs:
                    self._retried_jobs.append(ProwJobResult(job))

        return self._retried_jobs

    @property
    def raw_data(self):
        return self._result

    def has_retried_jobs(self):
        return len(self.retried_jobs) > 0

    def is_retried_jobs_completed(self):
        if self.has_retried_jobs():
            completed_jobs = 0
            for job in self.retried_jobs:
                if job.is_completed():
                    completed_jobs += 1
            return completed_jobs and completed_jobs == len(self.retried_jobs)
        else:
            return True

    def is_retry_success(self):
        if self.has_retried_jobs():
            success_jobs = 0
            for job in self.retried_jobs:
                if job.is_success():
                    success_jobs += 1
            return self.is_retried_jobs_completed() and success_jobs >= round(len(self._retried_jobs)/2)
        else:
            return False

    def is_completed(self):
        return self.first_job.is_completed() and self.is_retried_jobs_completed()

    def is_success(self):
        return self.first_job.is_success() or self.is_retry_success()

    def to_dict(self):
        retried_jobs = []
        for job in self.retried_jobs:
            retried_jobs.append(job.to_dict())
        self._result["retriedJobs"] = retried_jobs
        self._result["firstJob"] = self.first_job.to_dict()

        return self._result


class Metric():

    def __init__(self, name, increment=1):
        self._counter = 0
        self._increment = increment
        self._name = name

    def increase(self):
        self._counter += self._increment

    @property
    def value(self):
        return self._counter

    @value.setter
    def value(self, value):
        self._counter = int(value)

    def __str__(self):
        return f"{self._name}:{self._counter}"


class TestMetrics():

    def __init__(self):
        self._total = Metric("total")
        self._success = Metric("success")
        self._pending = Metric("pending")
        self._failed = Metric("failed")
        self._required = Metric("required")
        self._completed = Metric("completed")
        self._successful_required = Metric("successful_required")

    @property
    def total(self):
        return self._total

    @property
    def success(self):
        return self._success

    @property
    def pending(self):
        return self._pending

    @property
    def failed(self):
        return self._failed

    @property
    def required(self):
        return self._required

    @property
    def completed(self):
        return self._completed

    @property
    def successful_required(self):
        return self._successful_required

    def is_qe_accepted(self):
        return self.successful_required.value == self.required.value

    def all_jobs_are_completed(self):
        return self.total.value > 0 and self.completed.value > 0 and self.total.value == self.completed.value

    def __str__(self):
        return f"{self.total}, {self._success}, {self._pending}, {self._failed}, {self._required}, {self._completed}, {self._successful_required}, qe_accepted:{str(self.is_qe_accepted()).lower()}"


class TestResultAggregator():

    def __init__(self, arch=Architectures.AMD64):
        validate_required_info()
        self._arch = Architectures.fromString(arch)
        self.job_registry = TestJobRegistry(self._arch)
        self.release_test_record = GithubUtil(
            REPO_RELEASE_TESTS, BRANCH_RECORD)
        self.job_api = Jobs()

    def start(self):
        logger.info("Start to scan test result files ...")
        contents = self.release_test_record.get_files(DIR_RELEASE)
        for content in contents:
            matched_path = re.search(
                r'ocp-test-result-.*-{}.json'.format(self._arch), content.path)
            if matched_path:
                file_name = matched_path.group()
                logger.info(f"Found test result file {file_name}")
                release = re.search(r'\d\.\d+', file_name).group()
                # check if the build is nightly
                nightly = "nightly" in file_name
                # get build number from file name
                build = re.search(
                    r'\d.*\d', file_name[:file_name.index(self._arch)]).group()
                # if the nightly build is recycled/cannot be found on releasestream, will skip aggregation and delete test result file
                if nightly and self.build_does_not_exists(build, self._arch):
                    logger.info(f"build {build} is recycled, skip aggregation")
                    self.release_test_record.delete_file(content.path)
                    continue
                # load file content and start to aggregate
                file_content = self.release_test_record.get_file_content(
                    content.path)
                json_data = json.loads(file_content)
                logger.info(f"Start to check test result for {build} ...")
                # if attribute `aggregated` found, i.e. the result is already analyzed, skip aggregation for this build
                if self.is_test_result_aggregated(json_data):
                    continue

                jobs = json_data["result"]
                metrics = TestMetrics()
                metrics.total.value = len(jobs)
                for job in jobs:
                    job_result = TestJobResult(job)
                    # get job metadata to check control flag optional,
                    # if it's true, the job result will not be used to determine build is QE accepted
                    job_metadata = self.job_registry.get_test_job(
                        release, nightly, job_result.job_name)

                    # if first job is failed and it's not optional we will start to trigger retry jobs
                    # according to `retries` attribute defined in job registry
                    if job_result.first_job.is_failed() and not job_metadata.optional and not job_result.has_retried_jobs():
                        self.retry_prow_jobs(
                            release, nightly, job_metadata, Build(json_data.get("build")), job)

                    if job_result.is_completed():
                        metrics.completed.increase()
                    else:
                        metrics.pending.increase()

                    if job_result.is_success():
                        metrics.success.increase()

                    if not job_metadata.optional:
                        metrics.required.increase()
                        if job_result.is_success():
                            metrics.successful_required.increase()

                    job = job_result.to_dict()

                logger.info(f"Test result summary of {build}: {metrics}")

                if metrics.is_qe_accepted():
                    self.update_releasepayload(build)

                # if all the jobs are completed, we add a attribute `aggregated` to indicate this test result is aggregated
                if metrics.all_jobs_are_completed():
                    json_data["aggregated"] = True
                    json_data["accepted"] = metrics.is_qe_accepted()
                self.release_test_record.push_file(
                    data=json.dumps(json_data, indent=2), path=content.path)
                logger.info(
                    f"Latest test result of {build} is updated to file {content.path}")

        logger.info("Aggregation is completed")

    def update_releasepayload(self, build):

        ns = "ocp" if self._arch == Architectures.AMD64 else f"ocp-{self._arch}"
        cmd = f"oc label releasepayloads/{build} release.openshift.io/qe_state=Accepted -n {ns}"
        try:
            subprocess.run(shlex.split(cmd), check=True)
        except CalledProcessError as e:
            logger.error(
                f"add QE accepted label for releasepayload failed:\n Cmd: {e.cmd}, Return code: {e.returncode}")

    def build_does_not_exists(self, build, arch):
        # check if nightly build exists or not, if it does not exist, skip test result aggregation for it
        if build and "nightly" not in build:
            # if input is not nightly build, i.e. it is stable build, it should be there
            return True
        # get build url
        url = ReleaseStreamURLResolver.get_url_for_build(build, arch)

        return requests.get(url).status_code == 404

    def retry_prow_jobs(self, release, nightly, job_metadata, build, job_data):

        logger.info(f"Start to retry failed job {job_metadata.prow_job} ...")

        job_ids = []
        controller = JobController(release, nightly, False, self._arch)
        for x in range(job_metadata.retries):
            prow_job_id = controller.trigger_prow_job(job_metadata, build)
            if prow_job_id:
                job_ids.append(prow_job_id)

        if len(job_ids):
            retried_jobs = []
            for job_id in job_ids:
                retried_jobs.append({"jobID": job_id})
            job_data["retriedJobs"] = retried_jobs

            logger.info(f"Retried jobs: {retried_jobs}")

    def is_test_result_aggregated(self, json_data):

        if json_data.get("aggregated") == True:
            build = Build(json_data.get("build"))
            logger.info(
                f"test result of build {build} is already aggregated, skip")
            return True

        return False


def validate_required_info(release=None):
    if os.environ.get(SYS_ENV_VAR_API_TOKEN) is None:
        raise SystemExit(
            f"Cannot find environment variable {SYS_ENV_VAR_API_TOKEN}")
    if os.environ.get(SYS_ENV_VAR_GITHUB_TOKEN) is None:
        raise SystemExit(
            f"Cannot find environment variable {SYS_ENV_VAR_GITHUB_TOKEN}")
    if release and release not in VALID_RELEASES:
        raise SystemExit(f"{release} is not supported")


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
@click.option("--arch", help="architecture used to filter accepted build", default=Architectures.AMD64, type=click.Choice(Architectures.VALID_ARCHS))
def start_controller(release, nightly, trigger_prow_job, arch):
    JobController(release, nightly, trigger_prow_job, arch).start()


@click.command
@click.option("--arch", help="architecture used to filter test result", default=Architectures.AMD64, type=click.Choice(Architectures.VALID_ARCHS))
def start_aggregator(arch):
    TestResultAggregator(arch).start()


cli.add_command(start_controller)
cli.add_command(start_aggregator)
