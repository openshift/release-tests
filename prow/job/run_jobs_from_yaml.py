#!/usr/bin/env python


"""
1. read in a yaml of job names from input yaml
2. call job.py to launch the job
"""
import sys
import yaml
import subprocess


def batch_jobs(job_yaml_file):
    with open(yaml_file_name, 'r') as yfile:
        job_yaml = yaml.safe_load(yfile)
    payload = job_yaml.get('payload')
    jobs = job_yaml.get('jobs')
    for job in jobs:
        # call job.py to launch the PROW CI for example
        # python job.py run --payload=quay.io/openshift-release-dev/ocp-release:4.11.0-assembly.art6883.3 periodic-ci-openshift-openshift-tests-private-release-4.11-amd64-nightly-azure-ipi-ovn-ipsec-p2-f14
        cmd = f'''python job.py run --payload={payload} {job}'''
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        print(f'STDOUT: {stdout}')


if __name__ == '__main__':
    yaml_file_name = sys.argv[1]
    batch_jobs(yaml_file_name)
