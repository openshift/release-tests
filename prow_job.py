#coding:utf-8
import requests
import os
import sys
import re
import csv

'''
MacBook-Pro:~ jianzhang$ curl -w "%{http_code}\n" -X POST -d '{"job_execution_type": "1"}' -H "Authorization: Bearer $APITOKEN" https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions/periodic-ci-openshift-openshift-tests-private-release-4.9-sanity
{
 "id": "cecdbd1e-e3f5-11ed-934d-0a580a8004aa",
 "job_name": "periodic-ci-openshift-openshift-tests-private-release-4.9-sanity",
 "job_type": "PERIODIC",
 "job_status": "TRIGGERED",
 "gcs_path": ""
}
200
'''

class ProwJob(object):
    def __init__(self):
        self.gangwayURL = "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions/"
        self.prowJobURL = "https://prow.ci.openshift.org/prowjob?prowjob={}"

    def get_headers(self):
        token = os.getenv('APITOKEN')
        if token:
            headers = {'Authorization': 'Bearer ' + token.strip()}
            return headers
        else:
            print('No Prow API token found, exit...')
            sys.exit(0)

    def get_data(self):
        data = {'job_execution_type': '1'}
        return data
    def save_data(self, dict):
         # save it to the crrent CSV file
         with open('prow-jobs.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            L = [dict['time'].strip(), dict['jobID'].strip(), dict['jobURL'].strip()]
            writer.writerow(L)
            print(L)

    def post(self):
        jobName = input('Please input a prow job name: ')
        if jobName:
            url = self.gangwayURL+jobName.strip()
            res = requests.post(url=url, json=self.get_data(), headers=self.get_headers())
            print(res.text)
            print(res.status_code)
        else:
            print('Error! Please input the correct prow job name!')

    def check_status(self):
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
                    self.save_data(dict=dict)
                else:
                    print("Not found the url link or creationTimestamp...")
            else:
                raise Exception("return status code: {}".format(req.status_code))
        else:
            print('No job ID input, exit...')
            sys.exit(0)

        
if __name__ == '__main__':
    prowJob = ProwJob()
    # prowJob.post()
    prowJob.check_status()

