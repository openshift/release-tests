import os
import fnmatch
import logging
import json
import re
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from google.oauth2.service_account import Credentials
from google.cloud import storage

logger = logging.getLogger(__name__)


class Artifacts():

    def __init__(self, cred_file, job_name, job_run_id, bucket=None):
        if bucket is None:
            bucket = "qe-private-deck"
        self._job_name = job_name
        self._job_run_id = job_run_id
        self._gcs = GCSClient(cred_file, bucket)
        self._root_dir = f"logs/{job_name}/{job_run_id}"

    def get_junit_files(self):
        patterns = ['.*\/junit.*import-.*xml',
                    '.*\/junit.*TEST-features-.*xml',
                    '.*\/gui_test.*console-cypress.xml']
        return self._gcs.get_files(self._root_dir, patterns)

    def get_test_failures_summary(self):
        blobs = self._gcs.get_files(
            self._root_dir, ['test-failures-summary_.*json'])
        if blobs:
            return blobs[0].download_as_bytes()
        else:
            raise FileNotFoundError(f"test failures summary file not found")

    def generate_test_failures_summary(self):
        test_count = 0
        failed_tests = []
        junit_files = self.get_junit_files()
        if junit_files:
            for jf in junit_files:
                report = JunitTestReport(jf.download_as_bytes())
                test_summary = report.get_test_summary()
                test_count += test_summary.tests
                if test_summary.failures > 0:
                    failed_tests.extend(report.get_failed_tests())
        else:
            raise FileNotFoundError("Cannnot find any junit file")

        test_failures_summary = {
            "ID": int(self._job_run_id),
            "ProwJob": {
                "Name": self._job_name
            },
            "Tests": failed_tests,
            "TestCount": test_count
        }

        return json.dumps(test_failures_summary).encode('utf-8')


class GCSClient():

    def __init__(self, cred_file, bucket):
        # check cred file exist or not
        if not os.path.exists(cred_file):
            raise FileNotFoundError(f"file {cred_file} does not exist")
        # init storage client
        cred = Credentials.from_service_account_file(cred_file)
        self._client = storage.Client(credentials=cred)
        # get root directory
        self._bucket = self._client.bucket(bucket)

    def get_file(self, path):
        # if we know the absolute file path, get the blob directly
        return self._bucket.get_blob(path)

    def get_files(self, path, name_patterns: list = None):

        blobs = self._bucket.list_blobs(prefix=path)
        if name_patterns:
            matched_blobs = []
            for b in blobs:
                for p in name_patterns:
                    if re.compile(p).search(b.name):
                        matched_blobs.append(b)
                        break
            return matched_blobs
        else:
            return blobs


class JunitTestReport():

    def __init__(self, file_content: bytes = None, file_path: str = None):
        if file_content is None and file_path is None:
            raise ValueError("all the arguments are empty")

        if file_content:
            self._root = ElementTree.fromstring(file_content.decode("utf-8"))
        else:
            if os.path.exists(file_path):
                self._root = ElementTree.parse(file_path).getroot()
            else:
                raise FileNotFoundError(f"{file_path} not found")

        self._test_summary = JunitTestSummary(self._root)

    def get_test_summary(self):
        return self._test_summary

    def get_failed_tests(self):
        test_cases = []
        elements = self._root.findall(".//testcase")
        if elements:
            for e in elements:
                tc = JunitTestCase(e)
                if tc.is_failure():
                    # https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs/periodic-ci-openshift-release-master-nightly-4.15-e2e-aws-ovn-upi/1776477546024538112/artifacts/e2e-aws-ovn-upi/openshift-e2e-test/artifacts/junit/test-failures-summary_20240406-055752.json
                    test_cases.append({
                        "Test": {"Name": tc.name},
                        "Suite": {"Name": self.get_test_summary().name},
                        "Status": 12
                    })

        return test_cases


class JunitTestSummary():

    def __init__(self, element: Element):
        self._element = element

    @property
    def name(self):
        return self._element.attrib.get("name")

    @property
    def tests(self):
        return self.__convert__(self._element.attrib.get("tests"))

    @property
    def errors(self):
        return self.__convert__(self._element.attrib.get("errors"))

    @property
    def failures(self):
        return self.__convert__(self._element.attrib.get("failures"))

    @property
    def skipped(self):
        return self.__convert__(self._element.attrib.get("skipped"))

    def __convert__(self, value):
        return int(value) if value else 0


class JunitTestCase():

    def __init__(self, element: Element):
        self._element = element

    @property
    def name(self):
        return self._element.attrib.get("name")

    def is_skipped(self):
        return self._element.find("skipped") is not None

    def is_failure(self):
        return self._element.find("failure") is not None

    def is_error(self):
        return self._element.find("error") is not None

    def is_success(self):
        return not self.is_error() and not self.is_skipped() and not self.is_failure()
