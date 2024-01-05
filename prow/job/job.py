#!/usr/bin/env python3
# coding:utf-8
import requests
import time
import json
from semver import VersionInfo
import yaml
import base64
import os
import sys
import re
import csv
import click
import logging
import http.client as httpclient


class Jobs(object):
    def __init__(self):
        self.run = False
        self.url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/tags"
        # config the based URL here
        self.jobURL = "https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/{}?ref=master"
        self.gangwayURL = (
            "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions/"
        )
        self.prowJobURL = "https://prow.ci.openshift.org/prowjob?prowjob={}"
        self.base_image = "quay.io/openshift-release-dev/ocp-release:4.13.4-x86_64"

    # get_prow_headers func adds the Prow Token
    def get_prow_headers(self):
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
    def get_amdBaseImage_for_arm(self, payload):
        versionPattern = re.compile(":(\d*\.\d{2}\.\d)(-.*)?-")
        version = versionPattern.findall(payload)
        if len(version) > 0:
            version_string = "".join(version[0])
            self.base_image = "quay.io/openshift-release-dev/ocp-release:%s-x86_64" % version_string
            print("Infer the amd64 image: %s from arm payload: %s" % (self.base_image, payload))
        else:
            print("Warning! Fail to get the corresponding amd64 base image, use the default one:%s" % self.base_image)

    def get_job_data(self, payload, upgrade_from, upgrade_to):
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
                self.get_amdBaseImage_for_arm(payload)
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
                env = {"envs": {multi_latest: upgrade_from, multi_target: upgrade_to}}
            if "ppc64le" in upgrade_from and "ppc64le" in upgrade_to:
                env = {"envs": {ppc64le_latest: upgrade_from, ppc64le_target: upgrade_to}}
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
                self.get_amdBaseImage_for_arm(upgrade_from)
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
                self.get_amdBaseImage_for_arm(upgrade_to)
                env = {"envs": {amd_latest: self.base_image, arm_target: upgrade_to}}
        if upgrade_from is not None and upgrade_to is None:
            env = {"envs": {amd_latest: upgrade_from}}
            if "multi" in upgrade_from:
                env = {"envs": {multi_latest: upgrade_from}}
            if "ppc64le" in upgrade_from:
                env = {"envs": {ppc64le_latest: upgrade_from}}
            if "arm64" in upgrade_from or "aarch64" in upgrade_from:
                self.get_amdBaseImage_for_arm(upgrade_from)
                env = {"envs": {amd_latest: self.base_image, arm_latest: upgrade_from}}
        if env is not None:
            data = {"job_execution_type": "1", "pod_spec_options": env}
        print(data)
        return data

    def get_sha(self, url):
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            sha = json.loads(res.text)["sha"]
            print("sha: %s" % sha)
            return sha
        else:
            print(res.status_code, res.reason)
            return None

    def push_action(self, url, data):
        res = requests.put(url=url, json=data, headers=self.get_github_headers())
        if res.status_code == 200:
            print(res.reason)
        else:
            print(res.status_code, res.reason)

    def push_versions(self, content, file, run):
        url = "https://api.github.com/repos/openshift/release-tests/contents/_releases/{}?ref=record".format(
            file
        )
        base64Content = base64.b64encode(bytes(content, encoding="utf-8")).decode(
            "utf-8"
        )
        # print(base64Content)
        # check if the file exist
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            oldVersion = self.get_recored_version(url)
            if VersionInfo.parse(oldVersion) < VersionInfo.parse(content):
                sha = self.get_sha(url)
                # sha is Required if you are updating a file.
                data = {
                    "sha": sha,
                    "content": base64Content,
                    "branch": "record",
                    "message": "got the latest version %s" % content,
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
                print("No update! since the recored version %s >= the new version %s" % (oldVersion, content))
        elif res.status_code == 404:
            print("file %s doesn't exist, create it." % url)
            data = {
                "content": base64Content,
                "branch": "record",
                "message": "got the latest version %s" % content,
                "committer": {"name": "Release Bot", "email": "jianzhanbjz@github.com"},
            }
            self.push_action(url, data)
            if run:
                default_file = "_releases/required-jobs.json"
                channel = content[:-2]
                self.run_required_jobs(channel, default_file, content)
        else:
            self.run = False
            print("Push error: %s, %s" % (res.status_code, res.reason))

    def save_results(self, content, file):
        file_json = file
        url = (
            "https://api.github.com/repos/openshift/release-tests/contents/_releases/"
            + file
        )
        base64Content = base64.b64encode(bytes(content, encoding="utf-8")).decode(
            "utf-8"
        )
        # print(base64Content)
        # check if the file exist
        res = requests.get(url=url, headers=self.get_github_headers())

    def get_recored_version(self, url):
        try:
            # it will use the default master branch
            res = requests.get(url=url, headers=self.get_github_headers())
            if res.status_code == 200:
                return (
                    base64.b64decode(json.loads(res.text)["content"])
                    .decode("utf-8")
                    .replace("\n", "")
                )
            else:
                print(
                    "Fail to get recored version! %s:%s" % (res.status_code, res.reason)
                )
                return None
        except Exception as e:
            print(e)

    def get_payloads(self, versions, push, run):
        if versions is None:
            print("Please input the correct version info...")
            sys.exit(0)
        version_list = versions.split(",")
        res = requests.get(url=self.url, timeout=5)
        if res.status_code != 200:
            print("Fail to get payload info, %s:%s" % (res.status_code, res.reason))
            sys.exit(1)
        dict = json.loads(res.text)
        # Current three z-stream releases
        # releaseVersions = ["4.10.0", "4.11.0", "4.12.0"]
        for version in version_list:
            print("getting the latest payload of %s" % version)
            for tag in dict["tags"]:
                if tag["phase"] == "Accepted":
                    new = VersionInfo.parse(tag["name"])
                    old = VersionInfo.parse(version)
                    if new >= old:
                        if new.minor == old.minor:
                            channel = version[:-2]
                            print(
                                "The latest version of %s is: %s"
                                % (channel, tag["name"])
                            )
                            file = "Auto-OCP-%s.txt" % version[:-2]
                            if push:
                                self.push_versions(
                                    content=tag["name"], file=file, run=run
                                )
                            break
                        # else:
                        #     print("Not in the same Y release: %s" % new)

    def save_job_data(self, dict):
        # save it to the crrent CSV file
        with open("/tmp/prow-jobs.csv", "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            L = [
                dict["jobName"],
                dict["payload"],
                dict["upgrade_from"],
                dict["upgrade_to"],
                dict["time"],
                dict["jobID"],
                dict["jobURL"],
            ]
            writer.writerow(L)

    # get_github_headers func adds Github Token in case rate limit
    def get_github_headers(self):
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers = {"Authorization": "Bearer " + token.strip()}
            return headers
        else:
            print("No GITHUB_TOKEN env var found, exit...")
            sys.exit(0)

    def get_required_jobs(self, file_path):
        print("use JSON file: %s" % file_path)
        if file_path is None:
            return None
        with open(file_path) as f:
            jobs = f.read()
            return json.loads(jobs)

    # channel means OCP minor version, such as 4.12
    # version means OCP version, such as 4.10.63
    # file_path the path of the jobs file
    def run_required_jobs(self, channels, file_path, version):
        job_dict = self.get_required_jobs(file_path)
        if channels is not None and job_dict is not None:
            channel_list = channels.split(",")
            for channel in channel_list:
                print("Hanling %s" % channel)
                if channel in job_dict.keys():
                    for job in job_dict[channel]:
                        print("Hanling %s" % job)
                        # amd64 as default
                        payload = "quay.io/openshift-release-dev/ocp-release:{}-x86_64".format(
                            version
                        )
                        if "arm64" in job:
                            payload = "quay.io/openshift-release-dev/ocp-release:{}-aarch64".format(
                                version
                            )
                        # specify the latest stable payload for upgrade test
                        if "upgrade-from-stable" in job:
                            self.run_job(job, None, None, upgrade_to=payload)
                        # specify the latest stable payload for e2e test
                        elif "upgrade" not in job:
                            self.run_job(job, payload, None, None)
                        # as default
                        else:
                            self.run_job(job, None, None, None)

    # run_job func runs job by calling the API
    def run_job(self, jobName, payload, upgrade_from, upgrade_to):
        if jobName is None:
            print("Error! Please input the correct prow job name!")
        elif jobName.startswith("periodic-ci-"):
            periodicJob = jobName.strip()
        else:
            # it returns the first match job
            periodicJob = self.search_job(jobName, None)

        if periodicJob is not None:
            url = self.gangwayURL + periodicJob.strip()

            res = requests.post(
                url=url,
                json=self.get_job_data(payload, upgrade_from, upgrade_to),
                headers=self.get_prow_headers(),
            )
            if res.status_code == 200:
                # print(res.text)
                job_id = json.loads(res.text)["id"]
                print("Returned job id: %s" % job_id)
                self.get_job_results(job_id, jobName, payload, upgrade_from, upgrade_to)
            else:
                print("Error code: %s, reason: %s" % (res.status_code, res.reason))
        else:
            print("Warning! Couldn't find job:%s" % jobName)

    def search_job(self, jobName, ocp_version):
        print("Searching job...")
        jobURLs = "https://api.github.com/repos/openshift/release/contents/ci-operator/jobs/openshift/openshift-tests-private/?ref=master"
        req = requests.get(url=jobURLs, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            for file in file_dict:
                fileName = file["name"].strip()
                if ocp_version is not None and ocp_version not in fileName:
                    continue
                if fileName.endswith(".yaml") and "periodics" in fileName:
                    print(">>>> " + fileName)
                    url = "https://api.github.com/repos/openshift/release/contents/ci-operator/jobs/openshift/openshift-tests-private/{}?ref=master".format(
                        fileName
                    )
                    res = requests.get(
                        url=url, headers=self.get_github_headers(), timeout=3
                    )
                    if res.status_code == 200:
                        # We have to get the git blobs when the size is very large, such as
                        # git_url = 'https://api.github.com/repos/openshift/release/git/blobs/7546acab2fdc5fcde2df8d549df1d2886fcb4efc'
                        git_url = res.json()["git_url"]
                        res = requests.get(
                            url=git_url, headers=self.get_github_headers(), timeout=3
                        )
                        if res.status_code == 200:
                            content = base64.b64decode(
                                res.json()["content"].replace("\n", "")
                            ).decode("utf-8")
                            job_dict = yaml.load(content, Loader=yaml.FullLoader)
                            if job_dict is None:
                                print(
                                    "Warning! Couldn't get retunred JSON content when scanning %s!"
                                    % fileName
                                )
                                continue
                            if jobName is not None:
                                for job in job_dict["periodics"]:
                                    if jobName in job["name"]:
                                        return job["name"]
                            else:
                                return job_dict

    def get_job_results(
        self, jobID, jobName=None, payload=None, upgrade_from=None, upgrade_to=None
    ):
        if jobID:
            req = requests.get(url=self.prowJobURL.format(jobID.strip()))
            if req.status_code == 200:
                # the returned content is not the standard JSON format so use RE instead
                # jsonData = json.loads(req.text)
                # jsonData = req.json()
                urlPattern = re.compile(".*url: (.*)\n$", re.S)
                timePattern = re.compile('.*creationTimestamp: "(.*?)"', re.S)
                urlList = urlPattern.findall(req.text)
                timeList = timePattern.findall(req.text)
                if len(urlList) == 1 and len(timeList) == 1:
                    jobURL = urlList[0]
                    createTime = timeList[0]
                    print(jobName, payload, jobID, createTime, jobURL)
                    dict = {
                        "jobName": jobName,
                        "payload": payload,
                        "upgrade_from": upgrade_from,
                        "upgrade_to": upgrade_to,
                        "time": createTime,
                        "jobID": jobID,
                        "jobURL": jobURL,
                    }
                    self.save_job_data(dict=dict)
                    print("Done.")
                else:
                    print("Not found the url link or creationTimestamp...")
            else:
                raise Exception(
                    "return status code:%s reason:%s" % (req.status_code, req.reason)
                )
        else:
            print("No job ID input, exit...")
            sys.exit(0)

    def list_jobs(self, component, branch):
        if component is None:
            component = "openshift/openshift-tests-private"
        if branch is None:
            branch = "master"
        baseURL = (
            "https://api.github.com/repos/openshift/release/contents/ci-operator/config/%s/?ref=%s"
            % (component, branch)
        )
        req = requests.get(url=baseURL, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            file_count = 0
            for file in file_dict:
                if file["name"].endswith(".yaml"):
                    url = self.jobURL.format(file["name"].strip())
                    print(url)
                    self.get_jobs(url)
                    file_count += 1
            print(
                "Total file number under %s folder is:%s" % (component, str(file_count))
            )
        else:
            print(req.reason)

    def get_jobs(self, url):
        try:
            res = requests.get(url=url, headers=self.get_github_headers(), timeout=3)
            if res.status_code == 200:
                content = base64.b64decode(
                    res.json()["content"].replace("\n", "")
                ).decode("utf-8")
                job_dict = yaml.load(content, Loader=yaml.FullLoader)
                api_count = 0
                for job in job_dict["tests"]:
                    api = "true"
                    api_count += 1
                    print(job["as"] + "   " + api)
                print("Total number of api job is: " + str(api_count))
            else:
                print("warning:" + res.reason)
        except Exception as e:
            print(e)

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
            print("Fail to get payload info, %s:%s" % (res.status_code, res.reason))
            sys.exit(1)
        dict = json.loads(res.text)
        # get the job info from a JSON file
        job_dict = self.get_required_jobs("_releases/required-jobs.json")
        for y_version, jobs in job_dict.items():
            # z_version is like "4.10.0", and y_version is like "4.10"
            print("getting the latest payload of %s" % y_version)
            latest_version = ""
            self.run = True
            for tag in dict["tags"]:
                if tag["phase"] == "Accepted":
                    new = VersionInfo.parse(tag["name"])
                    old = VersionInfo.parse(y_version+".0")
                    if new >= old:
                        if new.minor == old.minor:
                            print("The latest version of %s is: %s" % (y_version, tag["name"]))
                            latest_version = tag["name"]
                            self.push_versions(content=latest_version, file="Auto-OCP-%s.txt" % y_version, run=False)
                            break
            else:
                # if no break, that means no new version found, so continue
                continue
            if not self.run:
                continue
            for job in jobs:
                print("Run job: %s" % job)
                # amd64 as default
                payload = "quay.io/openshift-release-dev/ocp-release:{}-x86_64".format(latest_version)
                if "arm64" in job:
                    payload = "quay.io/openshift-release-dev/ocp-release:{}-aarch64".format(latest_version)
                # specify the latest stable payload for upgrade test
                if "upgrade-from-stable" in job:
                    self.run_job(job, None, None, upgrade_to=payload)
                # specify the latest stable payload for e2e test
                elif "upgrade" not in job:
                    self.run_job(job, payload, None, None)
                # as default
                else:
                    self.run_job(job, None, None, None)


job = Jobs()

@click.group()
@click.version_option(package_name="job")
@click.option("--debug/--no-debug", default=False)
def cli(debug):
    """ "This job tool based on Prow REST API(https://github.com/kubernetes/test-infra/issues/27824), used to handle those prow jobs."""
    click.echo("Debug mode is %s" % ("on" if debug else "off"))
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        httpclient.HTTPConnection.debuglevel = 1


@cli.command("get_results")
@click.argument("job_id")
# @click.option('--job_id', help="The Prow job ID.")
def get_cmd(job_id):
    """Return the Prow job executed info."""
    job.get_job_results(job_id)


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
    For ARM test, we hard code a x86 image as the base image. Details: https://issues.redhat.com/browse/DPTP-3538
    """
    job.run_job(job_name, payload, upgrade_from, upgrade_to)


@cli.command("list")
@click.option(
    "--component",
    help="The detault is 'openshift/openshift-tests-private': https://github.com/openshift/release/tree/master/ci-operator/config/openshift/openshift-tests-private ",
)
@click.option("--branch", help="the master branch is as default.")
def run_cmd(component, branch):
    """List the jobs which support the API call."""
    job.list_jobs(component, branch)


@cli.command("run_required")
@click.option(
    "--channel",
    help="The OCP minor version, if multi versions, comma spacing, such as 4.12,4.11",
)
@click.option("--file", help="a file that stores required jobs for all OCP versions.")
@click.option("--version", help="OCP version, such as 4.10.63")
def run_cmd(channel, file, version):
    """Run required jobs from a file. Note that: this command only run stable payload, not nightly!
    For example, $ job run_required --channel 4.10 --file _releases/required-jobs.json --version 4.10.63
    """
    job.run_required_jobs(channel, file, version)


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
    job.get_payloads(versions, push, run)

@cli.command("run_z_stream_test")
def run_cmd():
    """Run jobs list in the _releases/required-jobs.json file.
     It only used for periodic-ci-openshift-release-tests-master-stable-build-test prow job.
    """
    job.run_z_stream_test()

if __name__ == "__main__":
    start = time.time()
    cli()
    end = time.time()
    print("execute time cost:%.2f" % (end - start))
