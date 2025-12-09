#!/usr/bin/env python3
# coding:utf-8
import base64
import csv
import http.client as httpclient
import json
import logging
import os
import re
import sys
import time

import click
import requests
import yaml
from requests.adapters import HTTPAdapter
from semver import VersionInfo
from urllib3.util import Retry


class Jobs:
    """Class Jobs handle Prow job by calling the API"""

    def __init__(self):
        self.run = False
        self.url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/tags"
        # config the based URL here
        self.job_url = "https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/{}?ref=master"
        self.gangway_url = "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions/"
        self.prow_job_url = "https://prow.ci.openshift.org/prowjob?prowjob={}"
        self.base_image = "quay.io/openshift-release-dev/ocp-release:4.13.4-x86_64"

        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504])

        self._adapter = HTTPAdapter(max_retries=retry_strategy)

    def _get_session(self):
        session = requests.Session()
        session.mount("https://", self._adapter)
        session.mount("http://", self._adapter)
        return session

    # get_prow_headers func adds the Prow Token
    def get_prow_headers(self):
        """Function get HTTP header"""
        token = os.getenv("APITOKEN")
        if token:
            headers = {"Authorization": "Bearer " + token.strip()}
            return headers
        else:
            print("No APITOKEN env var found, exit...")
            sys.exit(0)

    # it's for ARM test, now unable to find the 'cli' image in the provided ARM release image, but x86
    # so extract the corresponding amd64 version from the arm64 build,
    # see bug: https://issues.redhat.com/browse/DPTP-3538, https://issues.redhat.com/browse/OCPQE-17600
    def get_amd_image_for_arm(self, payload):
        """Function get amd64 image as the ARM platform base image"""
        version_pattern = re.compile(r':(\d*\.\d{2}\.\d)(-.*)?-')
        version = version_pattern.findall(payload)
        if len(version) > 0:
            version_string = "".join(version[0])
            self.base_image = f"quay.io/openshift-release-dev/ocp-release:{version_string}-x86_64"
            print(
                f"Infer the amd64 image: {self.base_image} from arm payload: {payload}")
        else:
            print(
                f"Warning! Fail to get the corresponding amd64 base image, use the default one: {self.base_image}")

    def get_job_data(self, payload, upgrade_from, upgrade_to):
        """Function get prow job payload data"""
        data = {"job_execution_type": "1"}
        env = None
        if payload is not None and upgrade_from is not None and upgrade_to is not None:
            print("Error! You cannot run e2e and upgrade test at the same time!")
            sys.exit(1)
        # amd_latest env is must no mater what platforms you run
        # support platforms: https://github.com/openshift/release-controller/blob/master/cmd/release-controller/sync_verify_prow.go#L203
        amd_latest = "RELEASE_IMAGE_LATEST"
        amd_target = "RELEASE_IMAGE_TARGET"
        arm_latest = "RELEASE_IMAGE_ARM64_LATEST"
        arm_target = "RELEASE_IMAGE_ARM64_TARGET"
        multi_latest = "RELEASE_IMAGE_MULTI_LATEST"
        multi_target = "RELEASE_IMAGE_MULTI_TARGET"
        ppc64le_latest = "RELEASE_IMAGE_PPC64LE_LATEST"
        ppc64le_target = "RELEASE_IMAGE_PPC64LE_TARGET"

        if payload is not None:
            env = {"envs": {amd_latest: payload}}
            if "arm64" in payload or "aarch64" in payload:
                # OCPQE-24207 only specify RELEASE_IMAGE_LATEST if payload is stable build
                if "nightly" in payload:
                    env = {"envs": {arm_latest: payload}}
                else:
                    self.get_amd_image_for_arm(payload)
                    env = {"envs": {amd_latest: self.base_image, arm_latest: payload}}
            if "multi" in payload:
                env = {"envs": {multi_latest: payload}}
            if "ppc64le" in payload:
                env = {"envs": {ppc64le_latest: payload}}
            if "ppc64le" in payload:
                env = {"envs": {ppc64le_latest: payload}}

        if upgrade_from is not None and upgrade_to is not None:
            # x86 as default
            env = {"envs": {amd_latest: upgrade_from, amd_target: upgrade_to}}
            if "multi" in upgrade_from and "multi" in upgrade_to:
                env = {"envs": {multi_latest: upgrade_from,
                                multi_target: upgrade_to}}
            if "ppc64le" in upgrade_from and "ppc64le" in upgrade_to:
                env = {"envs": {ppc64le_latest: upgrade_from,
                                ppc64le_target: upgrade_to}}
            # check if it's for ARM, and amd_latest env is must no mater what platforms you run
            # if "arm64" in upgrade_from or "aarch64" in upgrade_from:
            #     self.get_amdBaseImage_for_arm(upgrade_from)
            #     env = {"envs": {amd_latest: self.base_image, arm_latest: upgrade_from}}
            # if "arm64" in upgrade_to or "aarch64" in upgrade_to:
            #     self.get_amdBaseImage_for_arm(upgrade_to)
            #     env = {"envs": {amd_latest: self.base_image, arm_target: upgrade_to}}
            if ("arm64" in upgrade_from or "aarch64" in upgrade_from) and (
                "arm64" in upgrade_to or "aarch64" in upgrade_to
            ):
                if "nightly" in upgrade_from or "nightly" in upgrade_to:
                    env = {"envs": {arm_latest: upgrade_from,
                                    arm_target: upgrade_to}}
                else:
                    self.get_amd_image_for_arm(upgrade_from)
                    env = {
                        "envs": {
                            amd_latest: self.base_image,
                            arm_latest: upgrade_from,
                            arm_target: upgrade_to,
                        }
                    }
        if upgrade_from is None and upgrade_to is not None:
            env = {"envs": {amd_target: upgrade_to}}
            if "multi" in upgrade_to:
                env = {"envs": {multi_target: upgrade_to}}
            if "ppc64le" in upgrade_to:
                env = {"envs": {ppc64le_target: upgrade_to}}
            if "arm64" in upgrade_to or "aarch64" in upgrade_to:
                if "nightly" in upgrade_to:
                    env = {"envs": {arm_target: upgrade_to}}
                else:
                    self.get_amd_image_for_arm(upgrade_to)
                    env = {"envs": {amd_latest: self.base_image,
                                    arm_target: upgrade_to}}
        if upgrade_from is not None and upgrade_to is None:
            env = {"envs": {amd_latest: upgrade_from}}
            if "multi" in upgrade_from:
                env = {"envs": {multi_latest: upgrade_from}}
            if "ppc64le" in upgrade_from:
                env = {"envs": {ppc64le_latest: upgrade_from}}
            if "arm64" in upgrade_from or "aarch64" in upgrade_from:
                if "nightly" in upgrade_from:
                    env = {"envs": {arm_latest: upgrade_from}}
                else:
                    self.get_amd_image_for_arm(upgrade_from)
                    env = {"envs": {amd_latest: self.base_image,
                                    arm_latest: upgrade_from}}
        if env is not None:
            data = {"job_execution_type": "1", "pod_spec_options": env}
        print(data)
        return data

    def get_sha(self, url):
        """Function get returned sha data"""
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            sha = json.loads(res.text)["sha"]
            print(f"sha: {sha}")
            return sha
        else:
            print(res.status_code, res.reason)
            return None

    def push_action(self, url, data):
        """Function push data to the Github repo"""
        res = requests.put(url=url, json=data,
                           headers=self.get_github_headers())
        if res.status_code == 200:
            print(res.reason)
        else:
            print(res.status_code, res.reason)

    def push_versions(self, content, file, run):
        """Function push OCP payload version info to the Github repo"""
        url = f"https://api.github.com/repos/openshift/release-tests/contents/_releases/{file}?ref=record"
        base64_content = base64.b64encode(bytes(content, encoding="utf-8")).decode(
            "utf-8"
        )
        # print(base64Content)
        # check if the file exist
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            old_version = self.get_recored_version(url)
            if VersionInfo.parse(old_version) < VersionInfo.parse(content):
                sha = self.get_sha(url)
                # sha is Required if you are updating a file.
                data = {
                    "sha": sha,
                    "content": base64_content,
                    "branch": "record",
                    "message": f"got the latest version {content}",
                    "committer": {
                        "name": "Release Bot",
                        "email": "jianzhanbjz@github.com",
                    },
                }
                self.push_action(url, data)
                if run:
                    default_file = "_releases/required-jobs.json"
                    channel = content[:-2]
                    self.run_required_jobs(channel, default_file, content)
            else:
                self.run = False
                print(
                    f"No update! since the recored version {old_version} >= the new version {content}")
        elif res.status_code == 404:
            print(f"file {url} doesn't exist, create it.")
            data = {
                "content": base64_content,
                "branch": "record",
                "message": f"got the latest version {content}",
                "committer": {"name": "Release Bot", "email": "jianzhanbjz@github.com"},
            }
            self.push_action(url, data)
            if run:
                default_file = "_releases/required-jobs.json"
                channel = content[:-2]
                self.run_required_jobs(channel, default_file, content)
        else:
            self.run = False
            print(f"Push error: {res.status_code}, {res.reason}")

    def get_recored_version(self, url):
        """Function get the stored OCP payload info"""
        # it will use the default master branch
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code != 200:
            print(
                f"Fail to get recored version! {res.status_code}:{res.reason}")
            return None
        return (base64.b64decode(json.loads(res.text)["content"]).decode("utf-8").replace("\n", ""))

    def get_payloads(self, versions, push, run):
        """Function get the payload info from https://amd64.ocp.releases.ci.openshift.org/"""
        if versions is None:
            print("Please input the correct version info...")
            sys.exit(0)
        version_list = versions.split(",")
        res = requests.get(url=self.url, timeout=5)
        if res.status_code != 200:
            print(f"Fail to get payload info, {res.status_code}:{res.reason}")
            sys.exit(1)
        tags_dict = json.loads(res.text)
        # Current three z-stream releases
        # releaseVersions = ["4.10.0", "4.11.0", "4.12.0"]
        for version in version_list:
            print(f"getting the latest payload of {version}")
            for tag in tags_dict["tags"]:
                new = VersionInfo.parse(tag["name"])
                old = VersionInfo.parse(version)
                if tag["phase"] == "Accepted" and new >= old and new.minor == old.minor:
                    channel = version[:-2]
                    print(f'The latest version of {channel} is: {tag["name"]}')
                    file = f"Auto-OCP-{version[:-2]}.txt"
                    if push:
                        self.push_versions(
                            content=tag["name"], file=file, run=run)
                    break
                # else:
                #     print("Not in the same Y release: %s" % new)

    def save_job_data(self, job_dict):
        """Function save job results to the file"""
        # save it to the crrent CSV file
        with open("/tmp/prow-jobs.csv", "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            line = list(job_dict.values())
            writer.writerow(line)

    # get_github_headers func adds Github Token in case rate limit
    def get_github_headers(self):
        """Function check the Github token"""
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers = {"Authorization": "Bearer " + token.strip()}
            return headers
        print("No GITHUB_TOKEN env var found, exit...")
        sys.exit(0)

    def get_required_jobs(self, file_path):
        """Function get the required Prow jobs from the file"""
        print(f"use JSON file: {file_path}")
        if file_path is None:
            return None
        with open(file_path, encoding="utf-8") as f:
            jobs = f.read()
            return json.loads(jobs)

    # channel means OCP minor version, such as 4.12
    # version means OCP version, such as 4.10.63
    # file_path the path of the jobs file
    def run_required_jobs(self, channels, file_path, version):
        """Function run Prow jobs from the file"""
        job_dict = self.get_required_jobs(file_path)
        if channels is not None and job_dict is not None:
            channel_list = channels.split(",")
            for channel in channel_list:
                print(f"Hanling {channel}")
                if channel in job_dict.keys():
                    for prow_job in job_dict[channel]:
                        print(f"Hanling {prow_job}")
                        # amd64 as default
                        payload = f"quay.io/openshift-release-dev/ocp-release:{version}-x86_64"
                        if "arm64" in prow_job:
                            payload = f"quay.io/openshift-release-dev/ocp-release:{version}-aarch64"
                        # specify the latest stable payload for upgrade test
                        if "upgrade-from-stable" in prow_job:
                            self.run_job(prow_job, None, None,
                                         upgrade_to=payload)
                        # specify the latest stable payload for e2e test
                        elif "upgrade" not in prow_job:
                            self.run_job(prow_job, payload, None, None)
                        # as default
                        else:
                            self.run_job(prow_job, None, None, None)

    def run_job(self, job_name, payload, upgrade_from, upgrade_to):
        """Function run Prow job by calling the API"""

        job_id = None

        if job_name is None:
            print("Error! Please input the correct prow job name!")
        elif job_name.startswith("periodic-ci-"):
            periodic_job = job_name.strip()
        else:
            # it returns the first match job
            periodic_job = self.search_job(job_name, None)

        if periodic_job is not None:
            url = self.gangway_url + periodic_job.strip()

            res = self._get_session().post(
                url=url,
                json=self.get_job_data(payload, upgrade_from, upgrade_to),
                headers=self.get_prow_headers(),
            )
            if res.status_code == 200:
                # print(res.text)
                job_id = json.loads(res.text)["id"]
                print(f"Returned job id: {job_id}")
                # wait 1s for the job startup
                time.sleep(5)
                try:
                    self.get_job_results(
                        job_id, job_name, payload, upgrade_from, upgrade_to)
                except Exception as e:
                    print(f"get job result error: {e}")
            else:
                print(f"Error code: {res.status_code}, reason: {res.reason}")
                if res.status_code == 403:
                    raise Exception("Please check the Prow token. Error code: {res.status_code}, reason: {res.reason}")
        else:
            print(f"Warning! Couldn't find job: {job_name}")

        return job_id

    def search_job(self, job_name, ocp_version):
        """Function search the prow job from https://github.com/openshift/release/tree/master/ci-operator/jobs/openshift/openshift-tests-private"""
        print("Searching job...")
        jobs_url = "https://api.github.com/repos/openshift/release/contents/ci-operator/jobs/openshift/openshift-tests-private/?ref=master"
        req = requests.get(url=jobs_url, timeout=3)
        if req.status_code != 200:
            print(f"Error code: {req.status_code}, reason: {req.reason}")
            return None
        file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
        for file in file_dict:
            file_name = file["name"].strip()
            if ocp_version is not None and ocp_version not in file_name:
                continue
            if not file_name.endswith(".yaml") or "periodics" not in file_name:
                continue
            print(">>>> " + file_name)
            url = f"https://api.github.com/repos/openshift/release/contents/ci-operator/jobs/openshift/openshift-tests-private/{file_name}?ref=master"
            res = requests.get(
                url=url, headers=self.get_github_headers(), timeout=3)
            if res.status_code != 200:
                continue
            response = requests.get(
                url=res.json()["git_url"], headers=self.get_github_headers(), timeout=3)
            if response.status_code != 200:
                continue
            # We have to get the git blobs when the size is very large, such as
            # git_url = 'https://api.github.com/repos/openshift/release/git/blobs/7546acab2fdc5fcde2df8d549df1d2886fcb4efc'
            content = base64.b64decode(
                response.json()["content"].replace("\n", "")).decode("utf-8")
            job_dict = yaml.load(content, Loader=yaml.FullLoader)
            if job_dict is None:
                print(
                    f"Warning! Couldn't get retunred JSON content when scanning: {file_name}!")
                continue
            if job_name is not None:
                for periodics_job in job_dict["periodics"]:
                    if job_name in periodics_job["name"]:
                        return periodics_job["name"]
        return None

    def get_job_results(self, job_id, job_name=None, payload=None, upgrade_from=None, upgrade_to=None):
        """Function get job results"""
        if job_id:
            resp = self._get_session().get(url=self.prow_job_url.format(job_id.strip()))
            if resp.status_code == 200 and resp.text:
                job_result = yaml.safe_load(resp.text)
                if job_result:
                    status = job_result["status"]
                    spec = job_result["spec"]
                    job_name = spec["job"]
                    # it is possible that any of the follow attributes is not in response
                    # use func `get` to avoid key error
                    job_url = status.get("url")
                    job_state = status.get("state")
                    job_start_time = status.get("startTime")
                    print(job_name, payload, job_id,
                          job_start_time, job_url, job_state)
                    job_dict = {
                        "jobName": job_name,
                        "payload": payload,
                        "upgrade_from": upgrade_from,
                        "upgrade_to": upgrade_to,
                        "jobStartTime": job_start_time,
                        "jobID": job_id,
                        "jobURL": job_url,
                        "jobState": job_state,
                    }
                    if "completionTime" in status:
                        job_dict["jobCompletionTime"] = status["completionTime"]
                    self.save_job_data(job_dict)
                    print("Done.\n")
                    return job_dict
                else:
                    print("Not found the url link or creationTimestamp...")
            else:
                print(
                    f"return status code:{resp.status_code} reason:{resp.reason}")
        else:
            print("No job ID input, exit...")
            sys.exit(0)

        return None

    def list_jobs(self, component, branch):
        """Function list prow jobs"""
        if component is None:
            component = "openshift/openshift-tests-private"
        if branch is None:
            branch = "master"
        base_url = f"https://api.github.com/repos/openshift/release/contents/ci-operator/config/{component}/?ref={branch}"
        req = requests.get(url=base_url, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            file_count = 0
            for file in file_dict:
                if file["name"].endswith(".yaml"):
                    url = self.job_url.format(file["name"].strip())
                    print(url)
                    self.get_jobs(url)
                    file_count += 1
            print(
                f"Total file number under {component} folder is: {str(file_count)}")
        else:
            print(req.reason)

    def get_jobs(self, url):
        """Function get prow jobs"""
        res = requests.get(
            url=url, headers=self.get_github_headers(), timeout=3)
        if res.status_code == 200:
            content = base64.b64decode(
                res.json()["content"].replace("\n", "")).decode("utf-8")
            job_dict = yaml.load(content, Loader=yaml.FullLoader)
            api_count = 0
            for test_job in job_dict["tests"]:
                api = "true"
                api_count += 1
                print(test_job["as"] + "   " + api)
            print("Total number of api job is: " + str(api_count))
        else:
            print("warning:" + res.reason)

    def run_z_stream_test(self):
        # get required OCP version info and jobs from JSON file
        """
        { 
            "4.10" : [
                    "periodic-ci-openshift-openshift-tests-private-release-4.10-amd64-stable-aws-ipi-ovn-fips-p2-f28",
                    "periodic-ci-openshift-openshift-tests-private-release-4.10-amd64-stable-azure-ipi-fips-p2-f28",
                    ...
                    ],
            "4.11" : [...],
            ...
        """
        # get the payload info
        res = requests.get(url=self.url, timeout=5)
        if res.status_code != 200:
            print(f"Fail to get payload info, {res.status_code}:{res.reason}")
            sys.exit(1)
        payloads_dict = json.loads(res.text)
        # get the job info from a JSON file
        job_dict = self.get_required_jobs("_releases/required-jobs.json")
        for y_version, jobs in job_dict.items():
            # z_version is like "4.10.0", and y_version is like "4.10"
            print(f"getting the latest payload of {y_version}")
            latest_version = ""
            self.run = True
            for tag in payloads_dict["tags"]:
                if tag["phase"] == "Accepted":
                    new = VersionInfo.parse(tag["name"])
                    old = VersionInfo.parse(y_version+".0")
                    if new >= old:
                        if new.minor == old.minor:
                            print(
                                f'The latest version of {y_version} is: {tag["name"]}')
                            latest_version = tag["name"]
                            self.push_versions(
                                content=latest_version, file=f"Auto-OCP-{y_version}.txt", run=False)
                            break
            else:
                # if no break, that means no new version found, so continue
                continue
            if not self.run:
                continue
            for prow_job in jobs:
                print(f"Run job: {prow_job}")
                # amd64 as default
                payload = f"quay.io/openshift-release-dev/ocp-release:{latest_version}-x86_64"
                if "arm64" in prow_job:
                    payload = f"quay.io/openshift-release-dev/ocp-release:{latest_version}-aarch64"
                # specify the latest stable payload for upgrade test
                if "upgrade-from-stable" in prow_job:
                    self.run_job(prow_job, None, None, upgrade_to=payload)
                # specify the latest stable payload for e2e test
                elif "upgrade" not in prow_job:
                    self.run_job(prow_job, payload, None, None)
                # as default
                else:
                    self.run_job(prow_job, None, None, None)


JOB = Jobs()


@click.group()
@click.version_option(package_name="job")
@click.option("--debug/--no-debug", default=False, help="output the HTTP log info.")
def cli(debug):
    """
    This job tool based on the Prow REST API(https://github.com/kubernetes/test-infra/issues/27824), 
    used to handle the Prow job.
    """
    click.echo(f'Debug mode is {"on" if debug else "off"}')
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        httpclient.HTTPConnection.debuglevel = 1


@cli.command("get_results")
@click.argument("job_id")
# @click.option('--job_id', help="The Prow job ID.")
def get_cmd(job_id):
    """Return the Prow job executed info."""
    JOB.get_job_results(job_id)


@cli.command("run")
@click.argument("job_name")
@click.option(
    "--payload",
    help="specify a payload for e2e test, if not, it will use the latest payload from https://amd64.ocp.releases.ci.openshift.org/",
)
@click.option("--upgrade_from", help="specify an original payload for upgrade test.")
@click.option("--upgrade_to", help="specify a target payload for upgrade test.")
def run_cmd(job_name, payload, upgrade_from, upgrade_to):
    """Run a job and save results to /tmp/prow-jobs.csv. \n
    For ARM test, we hard code a x86 image as the base image. 
    Details: https://issues.redhat.com/browse/DPTP-3538
    """
    JOB.run_job(job_name, payload, upgrade_from, upgrade_to)


@cli.command("list")
@click.option(
    "--component",
    help="The detault is 'openshift/openshift-tests-private': https://github.com/openshift/release/tree/master/ci-operator/config/openshift/openshift-tests-private ",
)
@click.option("--branch", help="the master branch is as default.")
def run_list_job(component, branch):
    """List the jobs which support the API call."""
    JOB.list_jobs(component, branch)


@cli.command("run_required")
@click.option(
    "--channel",
    help="The OCP minor version, if multi versions, comma spacing, such as 4.12,4.11",
)
@click.option("--file", help="a file that stores required jobs for all OCP versions.")
@click.option("--version", help="OCP version, such as 4.10.63")
def run_required(channel, file, version):
    """
    Run required jobs from a file. 
    Note that: this command only run stable payload, not nightly!
    For example, $job run_required --channel 4.10 --file _releases/required-jobs.json --version 4.10.63
    """
    JOB.run_required_jobs(channel, file, version)


@cli.command("get_payloads")
@click.argument("versions")
@click.option(
    "--push",
    default=False,
    help="push the info to the https://api.github.com/repos/openshift/release-tests/contents/_releases/",
)
@click.option(
    "--run",
    default=False,
    help="Run the jobs stored in the _releases/required-jobs.json file if any updates. Note that: it won't be executed if --push is False",
)
def run_payloads(versions, push, run):
    """Check the latest stable payload of each version. Use comma spacing if multi versions, such as, 4.10.0,4.11.0,4.12.0"""
    JOB.get_payloads(versions, push, run)


@cli.command("run_z_stream_test")
def run_z_stream():
    """Run jobs list in the _releases/required-jobs.json file.
     It only used for periodic-ci-openshift-release-tests-master-stable-build-test prow job.
    """
    JOB.run_z_stream_test()

# no need this program entry since this file won't be imported as a module.
# if __name__ == "__main__":
#     start = time.time()
#     cli(False)
#     end = time.time()
#     print(f"execute time cost:{end - start}.2f")
