#!/usr/bin/python3
# author : xzha
import os
import re
import time
import subprocess
from unittest import skip
import urllib3
import requests
import argparse
import json
import logging
import yaml
import glob
from urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_logger(filePath):
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(filePath)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    formatter = logging.Formatter(fmt='%(asctime)s %(lineno)d %(message)s',
                                  datefmt='%Y-%m-%d-%H:%M:%S')
    fh.setFormatter(formatter)
    sh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

class SummaryClient:
    def __init__(self, args):
        self.logFile = args.log
        if not self.logFile:
            self.logFile = os.path.join(os.path.abspath(os.path.dirname(__file__)), "collect_prow_result_stream.log")
        if os.path.isfile(self.logFile):
            os.remove(self.logFile)
        self.logger = get_logger(self.logFile)
        token = args.token
        if not token:
            if os.getenv('RP_TOKEN'):
                token = os.getenv('RP_TOKEN')
            else:
                if os.path.exists('/root/rp.key'):
                    with open('/root/rp.key', 'r') as outfile:
                        data = json.load(outfile)
                        token =data["ginkgo_rp_mmtoken"]
        if not token:
            raise BaseException("ERROR: token is empty, please input the token using -t")
        
        urllib3.disable_warnings(category=InsecureRequestWarning)
        self.session = requests.Session()
        self.session.headers["Authorization"] = "bearer {0}".format(token)
        self.session.verify = False
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

        self.key_file = args.key
        if not self.key_file:
            self.key_file = os.getenv('HOME')+'/test/PROW/collect_result/key.json'
        self.type = args.type
        self.release_path = args.release_path
        self.config_sub_path = "ci-operator/config/openshift/openshift-tests-private/"
        self.gclient = self.getclient()
        
        self.target_file = 'https://docs.google.com/spreadsheets/d/1v43fn27WDqDuKbG1kDFkl5UZ_Km6InIvEC1Z7_SN2Eo/edit#gid=1613481050'
        self.base_url = "https://reportportal-openshift.apps.ocp-c1.prod.psi.redhat.com"
        self.launch_url = self.base_url +"/api/v1/prow/launch"
        self.item_url = self.base_url + "/api/v1/prow/item"
        self.ui_url = self.base_url + "/ui/#prow/launches/all/"
        self.days = 7
        self.version = args.version
        self.e2e_sheet = self.version
        self.update_range = args.update_range
        self.profile_list = dict()
        self.upgrade_profile_list = dict()

    def getclient(self):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(self.key_file, scope)
        return gspread.authorize(creds)
    
    def get_release_path(self):
        if not self.release_path:
            self.release_path= "/Users/zhaoxia/go/src/github.com/openshift/release/"
        if not os.path.exists(self.release_path):
            self.release_path= "./release"
            subprocess.run("git clone git@github.com:openshift/release.git")
            
    def get_e2e_profile_list_config(self):
        self.get_release_path()
        for arch in ["amd64", "arm64", "multi", "ppc64le"]:
            self.profile_list[arch] = dict()
            for build_type in ["nightly", "stable"]:
                file_name = "openshift-openshift-tests-private-release-"+self.version+"__"+arch+"-"+build_type+".yaml"
                file_path = os.path.join(self.release_path, self.config_sub_path, file_name)
                profile_list_get = []
                if not os.path.isfile(file_path):
                    continue
                with open(file_path) as f:
                    dict_all = yaml.safe_load(f)
                    self.logger.debug(dict_all)
                    profile_all = dict_all["tests"]
                    for profile_index in profile_all:
                        profile_name = profile_index["as"]
                        profile_list_get.append(profile_name)
                self.profile_list[arch][build_type] = profile_list_get
        self.logger.debug(self.profile_list)

    def get_upgrade_profile_list_config(self):
        self.get_release_path()
        fileList = glob.glob(os.path.join(self.release_path, self.config_sub_path) +"/*release-"+self.version+"*upgrade*.yaml")
        for file_path in fileList:
            self.logger.debug(file_path)
            all_profile_list = []
            if "amd64" in file_path:
                arch = "amd64"
            elif "arm64" in file_path:
                arch = "arm64"
            elif "multi" in file_path:
                arch = "multi"
            else:
                arch = "unknow"
            if arch not in self.upgrade_profile_list.keys():
                self.upgrade_profile_list[arch] = dict()
            from_version = file_path.split("-")[-1].replace(".yaml","")
            with open(file_path) as f:
                dict_all = yaml.safe_load(f)
                #self.logger.debug(dict_all)
                profile_all = dict_all["tests"]
                for profile_index in profile_all:
                    profile_name = profile_index["as"]
                    all_profile_list.append(profile_name)
            self.logger.debug(all_profile_list)
            self.upgrade_profile_list[arch][from_version]=all_profile_list
        self.logger.debug(json.dumps(self.upgrade_profile_list, indent=4, sort_keys=True))
       
    def get_e2e_test_result(self, profile_name_input, arch, build_type):
        launchs=dict()
        profile = re.sub('e2e-|-p[1-9]|-f[0-9]{1,2}',"", profile_name_input)
        self.logger.info("profile: %s", profile)
        launchs= self.get_e2e_rp_result(profile, arch, build_type) 
        if not launchs:
            self.logger.error("ERROR: no Launch is found")
        self.logger.debug(launchs)
        return launchs

    def get_e2e_rp_result(self, profile_name_input, arch, build_type):
        day_number = self.days
        launchs=dict()
        profile_name = profile_name_input
        filterProfile = "profilename:"+profile_name
        if "-destructive" in profile_name_input:
            filterProfile = "profilename:"+profile_name_input.replace("-destructive","")
        if "long-duration" in profile_name_input:
            filterProfile = "profilename:"+profile_name_input.replace("-long-duration", "").split("-part")[0]
        if len(profile_name_input.split()) > 1:
            if profile_name_input.split()[1] != "":
                self.logger.debug("get profile name")
                profile_name = profile_name_input.split()[0]
                filterProfile = "profilename:"+profile_name_input.split()[1]
        filter_arch = "architecture:"+arch
        filter_build_type = "build:"+build_type
        filter_url = self.launch_url + '?filter.has.compositeAttribute={0},{1},{2},version:{3}&filter.btw.startTime=-{4};1440;-0000&page.size=2000'.format(filterProfile, filter_arch, filter_build_type, self.version, str(1440*day_number))
        
        self.logger.info("filter_url is "+filter_url)
        try:
            r = self.session.get(url=filter_url)
            if (r.status_code != 200):
                self.logger.error("get launch error: {0}".format(r.text))
            self.logger.debug(json.dumps(r.json(), indent=4, sort_keys=True))
            if len(r.json()["content"]) == 0:
                self.logger.debug("no launch found by profile: {0}".format(profile_name))
            version = ''
            for ret in r.json()["content"]:
                version = ''
                version_installed = ''
                install_status = ''
                architecture = 'amd64'
                for attribute in ret['attributes']:
                    if attribute['key'] == 'version':
                        version = attribute['value']
                    if attribute['key'] == 'version_installed':
                        version_installed = attribute['value']
                    if attribute['key'] == 'install':
                        install_status = attribute['value']
                    if attribute['key'] == 'architecture':
                        architecture = attribute['value']
                if version != self.version:
                    self.logger.debug("verison %s is not %s", version, self.version)
                    continue
                if architecture != arch:
                    self.logger.debug("architecture %s is not %s", architecture, arch)
                    continue
               
                name = ret["name"]
                if "-destructive" in profile_name_input:
                    if "-destructive" not in name:
                        self.logger.debug("name %s doesn't end with %s", name, profile_name)
                        continue
                elif "long-duration" in profile_name_input:
                    if "long-duration" not in name:
                        self.logger.debug("name %s doesn't end with %s", name, profile_name)
                        continue
                    if "part1" in profile_name_input:
                        if "part1" not in name:
                            self.logger.debug("name %s doesn't end with %s", name, profile_name)
                            continue
                    if "part2" in profile_name_input:
                        if "part2" not in name:
                            self.logger.debug("name %s doesn't end with %s", name, profile_name)
                            continue
                    if "part3" in profile_name_input:
                        if "part3" not in name:
                            self.logger.debug("name %s doesn't end with %s", name, profile_name)
                            continue
                else:
                    if "long-duration" in name or "-destructive" in name:
                        self.logger.debug("name %s doesn't end with %s", name, profile_name)
                        continue
                    
                start_time = ret["startTime"]
                date_str = datetime.fromtimestamp(int(start_time)/1000).strftime('%Y-%m-%d')
                
                if not ret["statistics"]["executions"]:
                    self.logger.debug("%s: statistics.executions is empty", name )
                    continue

                self.logger.debug("check testrun: %s %s", str(start_time), str(ret["number"]))
                launchs[start_time] = dict()
                launchs[start_time]["name"] = ret["name"]
                launchs[start_time]["id"] = ret["id"]
                launchs[start_time]["number"] = ret["number"]
                launchs[start_time]["description"] = ret["description"]
                launchs[start_time]["date"] = date_str
                launchs[start_time]["link"] = self.ui_url+str(ret["id"])
                launchs[start_time]["build"] = version_installed
                failed = 0
                passed = 0
                if 'failed' in ret["statistics"]["executions"].keys():
                    failed = int(ret["statistics"]["executions"]["failed"])
                if 'passed' in ret["statistics"]["executions"].keys():
                    passed = int(ret["statistics"]["executions"]["passed"])
                total = int(ret["statistics"]["executions"]["total"])
                launchs[start_time]["failed"] = failed
                launchs[start_time]["passed"] = passed
                launchs[start_time]["total"] = total
                if install_status != "succeed":
                    launchs[start_time]["passRate"] = "Installation Fail"
                else:
                    launchs[start_time]["passRate"] = str(round(float(passed)/(failed+passed)*100,2))+"%"
                self.logger.debug(launchs)

            self.logger.info(launchs.keys())
            return launchs
        except BaseException as e:
            print(e)
            return dict()
    
    def write_e2e_google_sheet(self):
        spreadsheet_target = self.gclient.open_by_url(self.target_file)
        worksheet_target = spreadsheet_target.worksheet(self.version+"-e2e")
        start = 4
        end = 300
        profiles_added = dict()
        self.get_e2e_profile_list_config()
        all_row_values = worksheet_target.get_all_values()
        self.logger.debug(all_row_values)
        if self.update_range:
            start = int(self.update_range.split(":")[0])
            end = int(self.update_range.split(":")[1])
        if len(all_row_values) <= 3:
            self.logger.info("no record")
        else:
            for row in range(start, end):
                if row > len(all_row_values):
                    break
                values_list = all_row_values[row-1]
                if not values_list:
                    break
                profile_name = values_list[0].strip()
                if not profile_name:
                    continue
                if "remove it" in profile_name:
                    continue
                if len(values_list) < 25:
                    self.logger.warning("unknow arch, please update manually")
                    continue
                arch = values_list[21]
                build_type = values_list[24]
                if profile_name not in self.profile_list[arch][build_type]:
                    worksheet_target.update_acell('A'+str(row), profile_name+os.linesep+"!!!!! profile has been remove it form config !!!!!")
                else:
                    if arch not in profiles_added.keys():
                        profiles_added[arch]=dict()
                    if build_type not in profiles_added[arch].keys():
                        profiles_added[arch][build_type]=[]
                    profiles_added[arch][build_type].append(profile_name)
                    self.logger.info("================ %s: update row %s %s ================", arch, row, profile_name)
                    test_result = self.get_e2e_test_result(profile_name, arch, build_type)
                    if not test_result:
                        self.logger.error("ERROR: Cannot get test result %s for row %s, please update manually", profile_name, row)
                        continue
                    start_time_list = sorted([start_time for start_time in test_result.keys()], reverse=True)
                    max_start_time = start_time_list[0]
                    max_number = test_result[max_start_time]['number']
                    if len(values_list) >2 and str(values_list[17]) == str(max_number):
                        if str(values_list[19]) == test_result[max_start_time]['date']:
                            self.logger.info("================same test run date is %s, skip update [%s] ======================", values_list[19], profile_name)
                            continue
                    self.logger.info("update record with %s", str(test_result[max_start_time]))
                    worksheet_target.update_acell('D'+str(row),test_result[max_start_time]['build'])
                    worksheet_target.update_acell('E'+str(row),test_result[max_start_time]['passed'])
                    worksheet_target.update_acell('F'+str(row),test_result[max_start_time]['failed'])
                    worksheet_target.update_acell('J'+str(row),test_result[max_start_time]['passRate'])
                    worksheet_target.update_acell('T'+str(row),test_result[max_start_time]['date'])
                    worksheet_target.update_acell('S'+str(row),test_result[max_start_time]['link'])
                    worksheet_target.update_acell('R'+str(row),test_result[max_start_time]['number'])
                    
                    
                    if "Fail" in test_result[max_start_time]['passRate']:
                        for start_index in start_time_list:
                            if "Fail" not in test_result[start_index]['passRate']:
                                worksheet_target.update_acell('K'+str(row),test_result[start_index]['build']+os.linesep+test_result[start_index]['date'])
                                worksheet_target.update_acell('L'+str(row),test_result[start_index]['passed'])
                                worksheet_target.update_acell('M'+str(row),test_result[start_index]['failed'])
                                worksheet_target.update_acell('N'+str(row),0)
                                worksheet_target.update_acell('O'+str(row),0)
                                time.sleep(10)
                                break
                    else:
                        worksheet_target.update_acell('K'+str(row),test_result[max_start_time]['build']+os.linesep+test_result[max_start_time]['date'])
                        worksheet_target.update_acell('L'+str(row),test_result[max_start_time]['passed'])
                        worksheet_target.update_acell('M'+str(row),test_result[max_start_time]['failed'])
                        worksheet_target.update_acell('N'+str(row),0)
                        worksheet_target.update_acell('O'+str(row),0)

                    history_list = []
                    history_number = 0
                    for start_time_index in start_time_list:
                        history_number = history_number + 1
                        if history_number > 10:
                            break
                        self.logger.debug("update history %s %s", history_number, start_time_index)
                        history_list.append(test_result[start_time_index]['date']+": "+str(test_result[start_time_index]['number'])+": "+test_result[start_time_index]['passRate'] + "    " +test_result[start_time_index]['link'])
                    worksheet_target.update_acell('U'+str(row),os.linesep.join(history_list))
                    time.sleep(10)
                    self.logger.info("================ update %s ======================", profile_name)
    
        if self.update_range:
            return
        for arch in self.profile_list.keys():
            self.logger.info("start to insert record for %s", arch)
            for build_type in self.profile_list[arch].keys():
                for profile_name in self.profile_list[arch][build_type]:
                    time.sleep(1)
                    if arch in profiles_added.keys():
                        if build_type in profiles_added[arch].keys():
                            if profile_name in profiles_added[arch][build_type]:
                                self.logger.info("profile %s has been added, skip insert", profile_name)
                                continue
                    row = '4'
                    self.logger.info("insert record %s", profile_name)
                    worksheet_target.insert_row([profile_name], index=int(row))
                    worksheet_target.update_acell('V'+str(row),arch)
                    worksheet_target.update_acell('X'+str(row),'PROW')
                    worksheet_target.update_acell('Y'+str(row),build_type)
                    
                    test_result = self.get_e2e_test_result(profile_name, arch, build_type)
                    if not test_result:
                        self.logger.error("ERROR: Cannot get test result %s for row %s, please update manually", profile_name, row)
                        time.sleep(20)
                        continue
                    self.logger.info("================ %s: insert row %s ================", arch, profile_name)
                    start_time_list = sorted([start_time for start_time in test_result.keys()], reverse=True)
                    max_start_time = start_time_list[0]
                    max_number = test_result[max_start_time]['number']
                    worksheet_target.update_acell('R'+str(row),test_result[max_start_time]['number'])
                    worksheet_target.update_acell('S'+str(row),test_result[max_start_time]['link'])
                    worksheet_target.update_acell('D'+str(row),test_result[max_start_time]['build'])
                    worksheet_target.update_acell('E'+str(row),test_result[max_start_time]['passed'])
                    worksheet_target.update_acell('F'+str(row),test_result[max_start_time]['failed'])
                    worksheet_target.update_acell('T'+str(row),test_result[max_start_time]['date'])
                    worksheet_target.update_acell('I'+str(row),'=E4+F4+G4+H4')
                    worksheet_target.update_acell('J'+str(row),'=E4/I4')
                    if "Fail" in test_result[max_start_time]['passRate']:
                        for start_index in start_time_list:
                            if "Fail" not in test_result[start_index]['passRate']:
                                worksheet_target.update_acell('K'+str(row),test_result[start_index]['build']+os.linesep+test_result[start_index]['date'])
                                worksheet_target.update_acell('L'+str(row),test_result[start_index]['passed'])
                                worksheet_target.update_acell('M'+str(row),test_result[start_index]['failed'])

                                time.sleep(10)
                                break
                    else:
                        worksheet_target.update_acell('K'+str(row),test_result[max_start_time]['build']+os.linesep+test_result[max_start_time]['date'])
                        worksheet_target.update_acell('L'+str(row),test_result[max_start_time]['passed'])
                        worksheet_target.update_acell('M'+str(row),test_result[max_start_time]['failed'])
                    worksheet_target.update_acell('P'+str(row),'=L4+M4+N4+O4')    
                    worksheet_target.update_acell('Q'+str(row),'=IFerror(L4/P4, 0)')

                    history_list = []
                    history_number = 0
                    for start_time_index in start_time_list:
                        history_number = history_number + 1
                        if history_number > 10:
                            break
                        self.logger.debug("update history %s %s", history_number, start_time_index)
                        history_list.append(test_result[start_time_index]['date']+": "+str(test_result[start_time_index]['number'])+": "+test_result[start_time_index]['passRate'] + "    " +test_result[start_time_index]['link'])
                    worksheet_target.update_acell('U'+str(row),os.linesep.join(history_list))
                    time.sleep(20)
                    self.logger.info("================ update %s ======================", profile_name)
        worksheet_target.sort((1, 'asc'))

    def get_upgrade_test_result(self, profile_name_input, arch, from_version_input):
        launchs=dict()
        profiles = []
        profile_name = re.sub('e2e-|-p[1-9]|-f[0-9]{1,2}',"", profile_name_input)
        profiles.append(profile_name)   
        self.logger.debug("profiles: %s", profiles)
        for profile in profiles:
            launchs_index= self.get_upgrade_rp_result(profile, arch, from_version_input)
            if launchs_index:
                launchs.update(launchs_index)
        if not launchs:
            self.logger.error("ERROR: no Launch is found")
        self.logger.debug(launchs)
        return launchs
    
    def get_upgrade_rp_result(self, profile_name, arch="amd64", from_version_input="4.11"):
        day_number = 20
        launchs=dict()
        filterProfile = "profilename:"+profile_name
        filterFromVersion = "from:"+from_version_input
        filterArchitecture = "architecture:"+arch
        filter_url = self.launch_url + '?filter.has.compositeAttribute={0},to:{1},{2},{3}&filter.btw.startTime=-{4};1440;-0000&page.size=2000'.format(filterProfile, self.version, filterFromVersion, filterArchitecture, str(1440*day_number))
        self.logger.debug("filter_url is "+filter_url)
        try:
            r = self.session.get(url=filter_url)
            if (r.status_code != 200):
                self.logger.error("get launch error: {0}".format(r.text))
            ids = []
            self.logger.debug(json.dumps(r.json(), indent=4, sort_keys=True))
            if len(r.json()["content"]) == 0:
                self.logger.debug("no launch found by profile: {0}".format(profile_name))
            for ret in r.json()["content"]:
                install_status = ''
                upgraded_version = ""
                initial_version = ""
                for attribute in ret['attributes']:
                    if attribute['key'] == 'version_upgraded':
                        upgraded_version = attribute['value']
                    if attribute['key'] == 'version_installed':
                        initial_version = attribute['value']
                    if attribute['key'] == 'install':
                        install_status = attribute['value']
               
                start_time = ret["startTime"]
                date_str = datetime.fromtimestamp(int(start_time)/1000).strftime('%Y-%m-%d')
                self.logger.debug("check testrun: "+str(start_time))
                launchs[start_time] = dict()
                launchs[start_time]["name"] = ret["name"]
                launchs[start_time]["id"] = ret["id"]
                launchs[start_time]["description"] = ret["description"]
                launchs[start_time]["date"] = date_str
                launchs[start_time]["link"] = self.ui_url+str(ret["id"])
                launchs[start_time]["status"] = ret["status"]
                launchs[start_time]["number"] = ret["number"]
                launchs[start_time]["upgraded_version"] = upgraded_version
                launchs[start_time]["initial_version"] = initial_version
                failed = 0
                passed = 0
                if 'failed' in ret["statistics"]["executions"].keys():
                    failed = int(ret["statistics"]["executions"]["failed"])
                if 'passed' in ret["statistics"]["executions"].keys():
                    passed = int(ret["statistics"]["executions"]["passed"])
                total = int(ret["statistics"]["executions"]["total"])
                launchs[start_time]["failed"] = failed
                launchs[start_time]["passed"] = passed
                launchs[start_time]["total"] = total
                launchs[start_time]['failedCase'] = self.get_failed_case_id(launchs[start_time]["id"])
                if launchs[start_time]["status"] == "FAILED":
                    launchs[start_time]["status"] = "Upgrade Fail"
                if launchs[start_time]["status"] == "PASSED":
                    launchs[start_time]["status"] = "Pass"
                if install_status != 'succeed':
                    launchs[start_time]["status"] = "Installation Fail"
                elif failed > 0:
                    if "cluster upgrade:upgrade should succeed" not in launchs[start_time]['failedCase']:
                        launchs[start_time]["status"] = "Pass"
            return launchs
        except BaseException as e:
            print(e)
            return launchs
    
    def get_failed_case_id(self, launchId):
        item_url = self.item_url + "?filter.eq.launchId={0}&filter.eq.status=FAILED&isLatest=false&launchesLimit=0&page.size=150".format(launchId)
        self.logger.debug(item_url)
        try:
            r = self.session.get(url=item_url)
            if (r.status_code != 200):
                self.logger.error("get item case error: {0}".format(r.text))
            FailedCase = []
            if len(r.json()["content"]) == 0:
                return ''
            self.logger.debug(json.dumps(r.json(), indent=4, sort_keys=True))
            for ret in r.json()["content"]:
                if ret["type"] == "STEP":
                    subteamOut = ret["pathNames"]["itemPaths"][0]["name"]
                    name = ret["name"]
                    caseids = re.findall(r'OCP-\d{4,}', ret["name"])
                    if len(caseids) > 0:
                        if ":" in ret["name"]:
                            caseAuthor = ret["name"].split(":")[1]
                        else:
                            caseAuthor = ""
                        FailedCase.append(subteamOut+":"+caseids[0][4:]+"-"+caseAuthor)
                    else:
                        FailedCase.append(subteamOut+":"+name)
            return os.linesep.join(FailedCase)
        except BaseException as e:
            self.logger.error(e)
            return ''

    def write_upgrade_google_sheet(self):
        preadsheet_target = self.gclient.open_by_url(self.target_file)
        worksheet_target = preadsheet_target.worksheet(self.version+"-upgrade")
        self.get_upgrade_profile_list_config()
        start = 3
        end = 500
        upgrade_added=dict()
        if self.update_range:
            start = int(self.update_range.split(":")[0])
            end = int(self.update_range.split(":")[1])
        all_row_values = worksheet_target.get_all_values()
        self.logger.debug(all_row_values)
        if len(all_row_values) <= 2:
            self.logger.info("no record")
        else:
            for row in range(start, end):
                time.sleep(1)
                if row > len(all_row_values):
                    break
                values_list = all_row_values[row-1]
                if not values_list:
                    break
                profile_name = values_list[0]
                if not profile_name:
                    continue
                self.logger.info("================START: update row %s %s ================", row, profile_name)
                arch = values_list[14]
                profile_name_input = profile_name
                from_version_input = values_list[13]
                if arch not in upgrade_added.keys():
                    upgrade_added[arch] = dict()
                if from_version_input not in upgrade_added[arch].keys():
                    upgrade_added[arch][from_version_input]=[]
                upgrade_added[arch][from_version_input].append(profile_name)
                if profile_name not in self.upgrade_profile_list[arch][from_version_input]:
                    self.logger.info("%s has been deleted", profile_name)
                    worksheet_target.update_acell('A'+str(row), profile_name+os.linesep+"!!!!! profile has been remove it form config !!!!!")
                    continue
                
                test_result = self.get_upgrade_test_result(profile_name_input, arch, from_version_input)
                if not test_result:
                    self.logger.error("ERROR: Cannot get test result %s for row %s, please update manually", profile_name, row)
                else:
                    start_time_list = sorted([start_time for start_time in test_result.keys()], reverse=True)
                    max_start_time = start_time_list[0]
                    max_build_number = test_result[max_start_time]['number']
                    max_date = test_result[max_start_time]['date']
                    if len(values_list) >11:
                        if str(values_list[1]) == str(max_build_number):
                            if str(values_list[10]) == test_result[max_start_time]['date']:
                                self.logger.info("================same test run at %s:%s, skip update [%s] ======================", max_date,max_build_number, profile_name)
                                continue
                    worksheet_target.update_acell('B'+str(row),test_result[max_start_time]['number'])
                    worksheet_target.update_acell('C'+str(row),test_result[max_start_time]['link'])
                    worksheet_target.update_acell('D'+str(row),test_result[max_start_time]["initial_version"]+" -> " + os.linesep + test_result[max_start_time]["upgraded_version"])
                    worksheet_target.update_acell('E'+str(row),test_result[max_start_time]['passed'])
                    worksheet_target.update_acell('F'+str(row),test_result[max_start_time]['failed'])
                    worksheet_target.update_acell('G'+str(row),test_result[max_start_time]['total'])
                    worksheet_target.update_acell('H'+str(row),test_result[max_start_time]['status'])
                    worksheet_target.update_acell('K'+str(row),test_result[max_start_time]['date'])
                    worksheet_target.update_acell('M'+str(row),test_result[max_start_time]['failedCase'])
                    history_list = []
                    for start_time_index in start_time_list:
                        history_list.append(test_result[start_time_index]['date']+": "+str(test_result[start_time_index]['number'])+":  "+test_result[start_time_index]['status'] + "    " +test_result[start_time_index]['link'])
                    worksheet_target.update_acell('L'+str(row),os.linesep.join(history_list))
                    time.sleep(10)
                    self.logger.info("================ FINISH: update %s ======================", profile_name)

        if self.update_range:
            return
        for arch in self.upgrade_profile_list.keys():
            self.logger.info("================START: insert arch %s ================", arch)
            for from_version in self.upgrade_profile_list[arch].keys():
                self.logger.info("================START: insert from version %s ================", from_version)
                for profile_name in self.upgrade_profile_list[arch][from_version]:
                    if arch in upgrade_added.keys():
                        if from_version in upgrade_added[arch].keys():
                            if profile_name in upgrade_added[arch][from_version]:
                                self.logger.info("%s %s %s has been added", arch, from_version, profile_name)
                                continue
                    time.sleep(2)
                    self.logger.info("================START: insert row %s %s %s ================", arch, from_version, profile_name)
                    profile_name_input = profile_name
                    from_version_input = from_version

                    test_result = self.get_upgrade_test_result(profile_name_input, arch, from_version_input)
                    row=3
                    if not test_result:
                        self.logger.error("ERROR: Cannot get test result %s for row %s, please update manually", profile_name, row)
                        worksheet_target.insert_row([profile_name], index=row)
                        worksheet_target.update_acell('N'+str(row),from_version)
                        worksheet_target.update_acell('O'+str(row),arch)
                        worksheet_target.update_acell('P'+str(row),'PROW')
                    else:
                        start_time_list = sorted([start_time for start_time in test_result.keys()], reverse=True)
                        max_start_time = start_time_list[0]
                        max_build_number = test_result[max_start_time]['number']
                        max_date = test_result[max_start_time]['date']
                        worksheet_target.insert_row( [profile_name], index=row)
                        worksheet_target.update_acell('B'+str(row),test_result[max_start_time]['number'])
                        worksheet_target.update_acell('C'+str(row),test_result[max_start_time]['link'])
                        worksheet_target.update_acell('D'+str(row),test_result[max_start_time]["initial_version"]+" -> " + os.linesep + test_result[max_start_time]["upgraded_version"])
                        worksheet_target.update_acell('E'+str(row),test_result[max_start_time]['passed'])
                        worksheet_target.update_acell('F'+str(row),test_result[max_start_time]['failed'])
                        worksheet_target.update_acell('G'+str(row),test_result[max_start_time]['total'])
                        worksheet_target.update_acell('H'+str(row),test_result[max_start_time]['status'])
                        worksheet_target.update_acell('K'+str(row),test_result[max_start_time]['date'])
                        worksheet_target.update_acell('M'+str(row),test_result[max_start_time]['failedCase'])
                        worksheet_target.update_acell('N'+str(row),from_version)
                        worksheet_target.update_acell('O'+str(row),arch)
                        worksheet_target.update_acell('P'+str(row),'PROW')
                        history_list = []
                        history_number = 0
                        for start_time_index in start_time_list:
                            history_number = history_number+1
                            if history_number == 10:
                                break
                            history_list.append(test_result[start_time_index]['date']+": "+str(test_result[start_time_index]['number'])+":  "+test_result[start_time_index]['status'] + "    " +test_result[start_time_index]['link'])
                        worksheet_target.update_acell('L'+str(row),os.linesep.join(history_list))
                        time.sleep(10)
                        self.logger.info("================ FINISH: insert %s ======================", profile_name)
        worksheet_target.sort((10, 'asc'))

    def collectResult(self):
        types=[self.type.lower()]
        if "e2e" in types:
            self.logger.info("Collect E2E CI result for %s", self.version)
            self.write_e2e_google_sheet()
        if "upgrade" in types:
            self.logger.info("Collect upgrade CI result for %s", self.version)
            self.write_upgrade_google_sheet()


########################################################################################################################################
if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python3 collect_result.py", usage='''%(prog)s''')
    parser.add_argument("-t","--token", default="")
    parser.add_argument("-k","--key", default="", required=False, help="the key file path")
    parser.add_argument("-v", "--version", default='4.13', help="the ocp version")
    parser.add_argument("-u", "--update_range", default='', help="update range")
    parser.add_argument("-p", "--release_path", default='', help="the name of the sheet")
    parser.add_argument("-type","--type", default="all", required=False, help="the type, e2e/upgrade")
    parser.add_argument("-log","--log", default="", required=False, help="the log file")
    args=parser.parse_args()

    sclient = SummaryClient(args)
    sclient.collectResult()
    
    exit(0)

    

    
