#coding:utf-8
import requests
import time
import json
from semver.version import Version
import yaml
import base64
import os
import sys
import re
import csv
import click

class Payloads(object):
    def __init__(self):
        self.url = 'https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/tags'
        # config the based URL here
        self.jobURL='https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/{}?ref=master'
        self.gangwayURL = "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions/"
        self.prowJobURL = "https://prow.ci.openshift.org/prowjob?prowjob={}"

    # get_prow_headers func adds the Prow Token
    def get_prow_headers(self):
        token = os.getenv('APITOKEN')
        if token:
            headers = {'Authorization': 'Bearer ' + token.strip()}
            return headers
        else:
            print('No Prow API token found, exit...')
            sys.exit(0)

    def get_job_data(self):
        data = {'job_execution_type': '1'}
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

    def push_versions(self, content, file):
        # file = ".auto-OCP-4.12.txt"
        url = "https://api.github.com/repos/openshift/release-tests/contents/_releases/" + file
        base64Content = base64.b64encode(bytes(content, encoding='utf-8')).decode('utf-8')
        # print(base64Content)
        # check if the file exist
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            print("file %s exist, update it." % url)
            sha = self.get_sha(url)
            # sha is Required if you are updating a file.
            data = {"sha": sha,"content": base64Content,"branch": "master", "message":"got the latest version %s" % content,"committer":{"name":"Release Bot","email":"jianzhanbjz@github.com"}}
            self.push_action(url, data)
        elif res.status_code == 404:
            print("file %s doesn't exist, create it." % url)
            data = {"content":base64Content,"branch": "master", "message":"got the latest version %s" % content,"committer":{"name":"Release Bot","email":"jianzhanbjz@github.com"}}
            self.push_action(url, data)
        else:
            print(res.status_code, res.reason)

    def get_versions(self):
        # it will use the default master branch
        url = "https://api.github.com/repos/openshift/release-tests/contents/_releases/.auto-OCP-4.13.txt"
        res = requests.get(url=url, headers=self.get_github_headers())
        if res.status_code == 200:
            print(base64.b64decode(json.loads(res.text)["content"]).decode('utf-8').replace("\n", ""))
        else:
            print(res.status_code, res.reason)


    def save_job_data(self, dict):
         # save it to the crrent CSV file
         with open('prow-jobs.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            L = [dict['time'].strip(), dict['jobID'].strip(), dict['jobURL'].strip()]
            writer.writerow(L)
            print(L)

    # get_github_headers func adds Github Token in case rate limit   
    def get_github_headers(self):
        token = os.getenv('GITHUB_TOKEN')
        if token:
            headers = {'Authorization': 'Bearer ' + token.strip()}
            return headers
        else:
            print('No GITHUB_TOKEN found, exit...')
            sys.exit(0)

    # run_job func runs job by calling the API
    def run_job(self, jobName):
        # jobName = input('Please input a prow job name: ')
        if jobName is None:
            print('Error! Please input the correct prow job name!')
        elif jobName.startswith("periodic-ci-"):
            periodicJob = jobName.strip()
        else:
            payloads = Payloads()
            periodicJob = payloads.get_periodic_job(jobName)

        if periodicJob is not None:
            url = self.gangwayURL+periodicJob.strip()
            res = requests.post(url=url, json=self.get_job_data(), headers=self.get_prow_headers())
            if res.status_code == 200:
                print(res.text)
            else:
                print("Error code: %s, reason: %s" % (res.status_code, res.reason))
        else:
            print("Error! Could NOT find the job!")

    def get_periodic_job(self, jobName):
        baseURL = 'https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/?ref=master'
        req = requests.get(url=baseURL, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            for file in file_dict:
                fileName = file['name'].strip()
                if fileName.endswith('.yaml'):
                    if 'upgrade' in fileName or 'stable' in fileName:
                        url = self.jobURL.format(fileName)
                        res=requests.get(url=url, headers=self.get_github_headers(), timeout=3)
                        if res.status_code == 200:
                            content = base64.b64decode(res.json()['content'].replace("\n", "")).decode('utf-8')
                            job_dict = yaml.load(content, Loader=yaml.FullLoader)
                            for job in job_dict['tests']:
                                if jobName == job['as'] and ('remote_api' in job.keys()) and job['remote_api'] == True:
                                    print("find %s in file %s" % (jobName, fileName))
                                    periodicJobName = "periodic-ci-%s-%s" % (fileName.replace("__", "-").replace(".yaml", ""), jobName)
                                    return periodicJobName
                            #         break
                            # else:
                            #     continue
                            # break
                        else:
                            print("Fail to get job: %s", res.status_code)
            return None
        else:
            print("Faile to get openshift-tests-private's files: %s" % req.status_code)
            return None


    def query_jobs(self,url, neededJobs):
        try:
            res=requests.get(url=url, headers=self.get_github_headers(), timeout=3)
            if res.status_code == 200:
                content = base64.b64decode(res.json()['content'].replace("\n", "")).decode('utf-8')
                job_dict = yaml.load(content, Loader=yaml.FullLoader)
                for job in job_dict['tests']:
                    if 'remote_api' in job.keys() and job['remote_api'] == True:
                        jobName = job['as']
                        if jobName in neededJobs['amd64']['jobs'] or jobName in neededJobs['arm64']['jobs']:
                            print(jobName)
                        else:
                            print("Warning %s is not list in the required JSON list, skip!!!" % jobName)
            else:
                print('warning:' + res.reason)

        except Exception as e:
            print(e)

    def check_job_status(self):
        jobID = input('Please input job ID: ')
        if jobID:
            req = requests.get(url=self.prowJobURL.format(jobID.strip()))
            if req.status_code == 200:
                # the returned content is not correct JSON format
                # jsonData = json.loads(req.text)
                # jsonData = req.json()
                urlPattern = re.compile('.*url: (.*)\n$', re.S)
                timePattern = re.compile('.*creationTimestamp: \"(.*?)\"', re.S)
                urlList = urlPattern.findall(req.text)
                timeList = timePattern.findall(req.text)
                if len(urlList) == 1 and len(timeList) == 1:
                    jobURL = urlList[0]
                    createTime = timeList[0]
                    print(jobID, createTime, jobURL)
                    dict = {
                        'time' : createTime,
                        'jobID' : jobID,
                        'jobURL' : jobURL
                    }
                    self.save_job_data(dict=dict)
                else:
                    print("Not found the url link or creationTimestamp...")
            else:
                raise Exception("return status code: {}".format(req.status_code))
        else:
            print('No job ID input, exit...')
            sys.exit(0)

    def get_payloads(self):
        res = requests.get(url=self.url, timeout=5)
        print(res.status_code)
        dict = json.loads(res.text)
        print(dict['name'])
        releaseVersions = ["4.10.0", "4.11.0", "4.12.0"]
        startVersion = '4.11.16'
        for version in releaseVersions:
            for tag in dict['tags']:
                if tag['phase'] == 'Accepted':
                    new = Version.parse(tag['name'])
                    old = Version.parse(version)
                    if new > old:
                        if new.minor == old.minor:
                            print("The latest version of %s is: %s" %(version[:-2],tag['name']))
                            file = ".auto-OCP-%s.txt" % version[:-2]
                            self.push_versions(content=tag['name'], file=file)
                            break
                        # else:
                        #     print("Not in the same Y release: %s" % new)

    def get_required_jobs(self):
        with open("/Users/jianzhang/goproject/src/github.com/openshift/release-tests/_releases/release-ocp-4.12.json") as f:
            jobs = f.read()
            return json.loads(jobs)
            # print(json.loads(jobs)['amd64']['jobs'])
            # print(json.loads(jobs)['arm64']['jobs'])

    # version is OCP stable payload x.y version, such as 4.12  
    def query_files(self, version):
        neededJobs = self.get_required_jobs()
        baseURL = 'https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/?ref=master'
        req = requests.get(url=baseURL, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            for file in file_dict:
                fileName = file['name'].strip()
                if fileName.endswith('.yaml') and (version in fileName):
                    if 'upgrade' in fileName:
                        # print('upgrade: ' + fileName)
                        url = self.jobURL.format(fileName)
                        self.query_jobs(url, neededJobs)
                    elif 'stable' in fileName:
                        # print('installation: ' + fileName)
                        url = self.jobURL.format(fileName)
                        self.query_jobs(url, neededJobs)
                        pass
                    else:
                        # print('others: ' + fileName)
                        pass
        else:
            print(req.reason)

# main
payloads = Payloads()
@click.group()
@click.option('--debug/--no-debug', default=False)
def cli(debug):
    click.echo('Debug mode is %s' % ('on' if debug else 'off'))

@cli.command('run')
@click.option('--job', help="The Prow job name.")
def run_cmd(job):
    """if input is a full job path, such as "periodic-ci-openshift-openshift-tests-private-release-4.12-amd64-stable-4.12-upgrade-from-stable-4.6-azure-ipi-fips-p2-f30" it will run it directly.
    If not, such as "azure-ipi-fips-p2-f30", it will query all currents jobs and then run all jobs, which match this job name. """
    payloads.run_job(job)

# sub command
@cli.command('payloads')
def payloads_cmd():
    """Get the latest stable payloads from https://amd64.ocp.releases.ci.openshift.org/"""
    payloads.get_payloads()

@cli.command('push')
@click.option('--file', help='The file stores the version info.')
@click.option('--version', help='The latest version info.')
def push_cmd(version, file):
    """Push version into a file under https://github.com/openshift/release-tests/tree/master/_releases"""
    if version is None or file is None:
        print("Please check help info.")
        sys.exit(0)
    payloads.push_versions(version, file)

if __name__ == '__main__':
    start=time.time()
    cli()
    # run_cmd()
    # payloads = Payloads()
    # payloads.get_payloads()
    # fileName = input('Please input a YAML file: ')
    # url = payloads.jobURL.format(fileName)
    # payloads.query_jobs(url)
    # test = "4.12"
    # payloads.query_files(test)
    # payloads.get_required_jobs()
    # payloads.run_job()
    # payloads.check_job_status()
    # payloads.get_periodic_job("aws-ipi-proxy-cco-manual-sts-p2-f14")
    # payloads.push_versions("4.12.18")
    # payloads.get_versions()
    end=time.time()
    print('execute time cost:%.2f'%(end-start))

