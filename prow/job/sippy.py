from __future__ import annotations
import requests
import logging
import json
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError
from requests import Response
from urllib3.util import Retry
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class Sippy():

    def __init__(self, host, port=443, secure=True):
        self._host = host
        self._port = port
        self._secure = secure
        schema = "https" if self._secure else "http"
        self._base_url = f"{schema}://{self._host}:{self._port}/api"

        # define retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504])

        self._adapter = HTTPAdapter(max_retries=retry_strategy)

    def _get_session(self):
        session = requests.Session()
        session.mount(
            f"{'https' if self._secure else 'http'}://", self._adapter)
        return session

    def _get_request(self, url, params, data=None):
        session = self._get_session()
        response = session.get(url, params=params, verify=False, data=data)
        self._raise_http_status(response)

        return response.json()

    def _post_request(self, url, data, headers=None):
        if not data:
            raise ValueError("request body should not be empty")

        session = self._get_session()
        response = session.post(url, data=data, headers=headers)
        self._raise_http_status(response)

        return response.json()

    def _raise_http_status(self, response: Response):
        if not response.ok:
            raise HTTPError(
                f"{response.status_code} {response.reason}, {response.text}")

    def health_check(self, release):
        url = f"{self._base_url}/health"
        return self._get_request(url, ParamBuilder().release(release).done())

    def query_jobs(self, params):
        url = f"{self._base_url}/jobs"
        return self._get_request(url, params)

    def query_tests(self, params):
        url = f"{self._base_url}/tests"
        return self._get_request(url, params)

    def query_component_readiness(self, params):
        url = f"{self._base_url}/component_readiness"
        return self._get_request(url, params)

    def query_variant_status(self, params):
        url = f"{self._base_url}/variants"
        return self._get_request(url, params)

    def query_risk_analysis(self, job_data=None, job_run_id=None):
        if job_data is None and job_run_id is None:
            raise ValueError("job data and job_run_id are all empty")

        url = f"{self._base_url}/jobs/runs/risk_analysis"
        if job_run_id:
            # send get request
            return self._get_request(url, ParamBuilder().prow_job_run_id(job_run_id).done())

        if job_data:
            # send get reuqest with json data
            # https://github.com/openshift/sippy/blob/72a5f3e16bc99483db09155707ad14280c3a7554/pkg/sippyserver/server.go#L1080
            return self._get_request(url, params=None, data=job_data)

    def analyze_component_readiness(self, params) -> DataAnalyzer:
        return DataAnalyzer(self.query_component_readiness(params))

    def analyze_variants(self, params) -> DataAnalyzer:
        return DataAnalyzer(self.query_variant_status(params))

    def analyze_job_run_risk(self, job_data=None, job_run_id=None):
        return DataAnalyzer(self.query_risk_analysis(job_data=job_data, job_run_id=job_run_id))


class ParamBuilder():

    def __init__(self):
        self._params = {}

    def release(self, release):
        self._params.update(release=release)
        return self

    def filter(self, filter):
        self._params.update(filter=filter)
        return self

    def base_release(self, release):
        self._params.update(baseRelease=release)
        return self

    def base_starttime(self, starttime):
        self._params.update(baseStartTime=starttime)
        return self

    def base_endtime(self, endtime):
        self._params.update(baseEndTime=endtime)
        return self

    def sample_release(self, release):
        self._params.update(sampleRelease=release)
        return self

    def sample_starttime(self, starttime):
        self._params.update(sampleStartTime=starttime)
        return self

    def sample_endtime(self, endtime):
        self._params.update(sampleEndTime=endtime)
        return self

    def confidence(self, confidence="95"):
        self._params.update(confidence=confidence)
        return self

    def ignore_disruption(self, ignore="true"):
        self._params.update(ignoreDisruption=ignore)
        return self

    def ignore_missing(self, ignore="false"):
        self._params.update(ignoreMissing=ignore)
        return self

    def exclude_arches(self, arches="arm64,heterogeneous,ppc64le,s390x"):
        self._params.update(excludeArches=arches)
        return self

    def exclude_clouds(self, clouds="openstack,ibmcloud,libvirt,ovirt,unknown"):
        self._params.update(excludeClouds=clouds)
        return self

    def exclude_variants(self, variants="hypershift,osd,microshift,techpreview,single-node,assisted,compact"):
        self._params.update(excludeVariants=variants)
        return self

    def group_by(self, group_by="cloud,arch,network"):
        self._params.update(groupBy=group_by)
        return self

    def min_fail(self, min="3"):
        self._params.update(minFail=min)
        return self

    def pity(self, pity="5"):
        self._params.update(pity=pity)
        return self

    def limit(self, limit="10"):
        self._params.update(limit=limit)
        return self

    def sort(self, sort="asc"):
        self._params.update(sort=sort)
        return self

    def sort_field(self, field="net_improvement"):
        self._params.update(sortField=field)
        return self

    def period(self, period="towDay"):
        self._params.update(period=period)
        return self

    def prow_job_run_id(self, prow_job_run_id):
        self._params.update(prow_job_run_id=prow_job_run_id)
        return self

    def view(self, name):
        self._params.update(view=name)
        return self

    def done(self):
        return self._params


class FilterBuilder():
    # https://github.com/openshift/sippy/blob/master/pkg/api/README.md#filtering-and-sorting

    def __init__(self):
        self._params = {}
        self._items = []

    def filter(self, key, op, value, not_op=False):
        '''
          String operators are: contains, starts with, ends with, equals, is empty, is not empty.
          Numerical operators are: =, !=, <, <=, >, >=
          Array operators are: contains
        '''

        filter = {"columnField": key, "operatorValue": op, "value": value}
        if not_op:
            filter.update({"not": True})

        self._items.append(filter)

        return self

    def link(self, AND=True):
        if AND:
            self._params.update(linkOperator="and")
        else:
            self._params.update(linkOperator="or")

    def done(self):
        if "linkOperator" not in self._params:
            self.link()
        self._params.update(items=self._items)
        return json.dumps(self._params)


class DatetimePicker():

    _now = datetime.now(timezone.utc)

    @staticmethod
    def today():
        return DatetimePicker._now

    @staticmethod
    def lastweek():
        return DatetimePicker._now - timedelta(days=7)

    @staticmethod
    def lastmonth():
        return date.today().replace(day=1) - timedelta(days=1)

    @staticmethod
    def anyday(year, month, day):
        return datetime(year, month, day)


class StartEndTimePicker():

    starttime_format = "%Y-%m-%dT00:00:00Z"
    endtime_format = "%Y-%m-%dT23:59:59Z"

    def __init__(self, endtime=None):
        self._now = endtime
        if not self._now:
            self._now = datetime.now(timezone.utc)

    def today(self):
        return self._now.strftime(self.endtime_format)

    def lastweek(self):
        lastweek = self._now - timedelta(days=7)
        return lastweek.strftime(self.starttime_format)

    def last2weeks(self):
        last2weeks = self._now - timedelta(days=14)
        return last2weeks.strftime(self.starttime_format)

    def last4weeks(self):
        last4weeks = self._now - timedelta(days=28)
        return last4weeks.strftime(self.starttime_format)


class DataAnalyzer():

    def __init__(self, data: dict):
        if data:
            self._data_set = data
        else:
            raise ValueError("job data is empty")

    def is_component_readiness_status_green(self):
        '''
          Check if any component has attribute `regressed_tests` and status >= -1
        '''
        logger.info('-' * 50)
        logger.info("Start to analyze component readiness status")

        issued_comps = []
        rows = self._data_set.get("rows")
        if len(rows):
            for comp in rows:
                name = comp.get("component")
                cols = comp.get("columns")
                for col in cols:
                    status = col.get("status")
                    if status <= -2 or "regressed_tests" in col:
                        regressed_tests = col.get("regressed_tests")
                        logger.warning(
                            f"{name} has regressed tests:\n{regressed_tests}\n")
                        issued_comps.append(name)

        if not issued_comps:
            logger.info("No issued component found")

        logger.info("Component readiness status is analyzed")

        return len(issued_comps) == 0

    def is_variants_status_green(self, expected_variants: list[str] = None, threshold=2):
        '''
          Check if the current pass percentage > or ~= previous pass percentage of the variants
        '''

        logger.info('-' * 50)
        logger.info(
            f"Start to analyze variants status {expected_variants if expected_variants else ''}")

        issued_variants = []
        if len(self._data_set):
            for variant in self._data_set:
                name = variant.get("name")
                if expected_variants and name not in expected_variants:
                    continue
                current_pass_percentage = variant.get(
                    "current_pass_percentage")
                previous_pass_percentage = variant.get(
                    "previous_pass_percentage")
                net_improvement = variant.get("net_improvement")
                if net_improvement < 0 and abs(net_improvement) >= threshold:
                    logger.warning(
                        f"issued variant <{name}> current %: {float('%.1f' % current_pass_percentage)}%, previous %:{float('%.1f' % previous_pass_percentage)}%")
                    issued_variants.append(name)

        if not issued_variants:
            logger.info("No issued variant found")

        logger.info("Variants are analyzed")

        return len(issued_variants) == 0

    def is_job_run_risky(self, threshold=50):
        '''
          Check risk level in job run risk analysis result
        '''
        job_name = self._data_set.get("ProwJobName")
        job_run_id = self._data_set.get("ProwJobRunID")
        level_dict = self._data_set.get("OverallRisk").get("Level")
        level = level_dict.get("Level")
        reasons = level_dict.get("Reasons")

        risky = False
        if level > threshold:
            risky = True
            logger.warning(f"{job_name} run {job_run_id} is risky: {reasons}")

        return risky
