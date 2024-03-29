import requests
import logging
import json
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class Sippy():

    def __init__(self, host, port=443, secure=True):
        self._host = host
        self._port = port
        schema = "https" if secure else "http"
        self._base_url = f"{schema}://{self._host}:{self._port}/api"

        # define retry strategy
        self._retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504])

        self._adapter = HTTPAdapter(max_retries=self._retry_strategy)

    def _request(self, url, params):
        session = requests.Session()
        session.mount("http://", self._adapter)
        session.mount("https://", self._adapter)

        response = session.get(url, params=params, verify=False)
        response.raise_for_status()

        return response.json()

    def health_check(self, release):
        url = f"{self._base_url}/health"
        return self._request(url, ParamBuilder().release(release).done())

    def query_jobs(self, params):
        url = f"{self._base_url}/jobs"
        return self._request(url, params)

    def query_tests(self, params):
        url = f"{self._base_url}/tests"
        return self._request(url, params)

    def query_component_readiness(self, params):
        url = f"{self._base_url}/component_readiness"
        return self._request(url, params)

    def query_variant_status(self, params):
        url = f"{self._base_url}/jobs/analysis"
        return self._request(url, params)


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
