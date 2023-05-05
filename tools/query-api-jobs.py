#coding:utf-8
import requests
import time
import random
import yaml
import base64
import os
import sys


class ProwJobs(object):
    def __init__(self):
        # config the based URL here
        self.url='https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/{}?ref=master'

    def get_headers(self):
        token = os.getenv('GITHUB_TOKEN')
        if token:
            headers = {'Authorization': 'Bearer ' + token.strip()}
            return headers
        else:
            print('No GITHUB_TOKEN found, exit...')
            sys.exit(0)
    
    def get_jobs(self,url):
        try:
            res=requests.get(url=url, headers=self.get_headers(), timeout=3)
            if res.status_code == 200:
                content = base64.b64decode(res.json()['content'].replace("\n", "")).decode('utf-8')
                job_dict = yaml.load(content, Loader=yaml.FullLoader)
                api_count = 0
                for job in job_dict['tests']:
                    api = 'false'
                    if 'remote_api' in job.keys() and job['remote_api'] == 'true':
                        api = 'true'
                        api_count += 1
                    print(job['as'] + "   " + api)
                print('Total number of api job is: ' + str(api_count))
            else:
                print('warning:' + res.reason)

        except Exception as e:
            print(e)

    def get_files(self):
        baseURL = 'https://api.github.com/repos/openshift/release/contents/ci-operator/config/openshift/openshift-tests-private/?ref=master'
        req = requests.get(url=baseURL, timeout=3)
        if req.status_code == 200:
            file_dict = yaml.load(req.text, Loader=yaml.FullLoader)
            file_count = 0
            for file in file_dict:
                if file['name'].endswith('.yaml'):
                    url = self.url.format(file['name'].strip())
                    self.get_jobs(url)
                    file_count += 1
            print("Total file number under openshift-tests-private folder is: " + str(file_count))
        else:
            print(req.reason)

    def run(self):
        # try:
            # file_name=input('Please input the file name you want to query: ')
            # url = self.url.format(file_name.strip())
            # print(url)
            # self.get_jobs(url)
            self.get_files()
            time.sleep(random.randint(1,3))
            self.blog=1
        # except Exception as e:
        #     print('Fatal error:', e)

if __name__ == '__main__':
    start=time.time()
    job=ProwJobs()
    job.run()
    end=time.time()
    print('execute time cost:%.2f'%(end-start))