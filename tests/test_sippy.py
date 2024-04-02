import unittest
import logging
import sys
import urllib3
from job.sippy import Sippy, DataAnalyzer
from job.sippy import ParamBuilder, FilterBuilder, DatetimePicker, StartEndTimePicker

logging.basicConfig(
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)


class TestSippy(unittest.TestCase):

    def setUp(self):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.sippy = Sippy("sippy.dptools.openshift.org")

    def test_health_check(self):
        resp = self.sippy.health_check("4.16")
        indicators = resp.get("indicators")
        self.assertTrue("tests" in indicators)
        tests = resp.get("indicators").get("tests")
        self.assertIsNotNone(tests.get("name"))
        self.assertIsNotNone(tests.get("current_pass_percentage"))
        self.assertIsNotNone(tests.get("previous_pass_percentage"))

    def test_query_jobs_by_name(self):
        job_name = "periodic-ci-openshift-release-master-ci-4.16-e2e-gcp-sdn-upgrade-out-of-change"
        filters = FilterBuilder().filter("name", "equals", job_name).done()
        params = ParamBuilder().release("4.16").filter(filters).done()
        resp = self.sippy.query_jobs(params)
        self.assertGreater(len(resp), 0, "Cannot find any job")
        self.assertEqual(resp[0].get("name"), job_name)
        self.assertEqual(resp[0].get("brief_name"),
                         "e2e-gcp-sdn-upgrade-out-of-change")

    def test_query_jobs_by_currentruns_and_variants(self):
        filters = FilterBuilder().filter("current_runs", ">=",
                                         "2").filter("variants", "contains", "never-stable", True).done()
        params = ParamBuilder().release("4.16").filter(
            filters).limit().period().sort().sort_field().done()
        resp = self.sippy.query_jobs(params)
        self.assertGreater(len(resp), 0, "Cannot find any job")
        for job in resp:
            logger.info(f"name: {job.get('name')}")
            logger.info(f"variant: {job.get('variants')}")
            logger.info(f"current_runs: {job.get('current_runs')}")
            logger.info(f"previous_runs: {job.get('previous_runs')}\n")

    def test_query_tests(self):
        filters = FilterBuilder().filter("name", "contains", "FIPS").done()
        params = ParamBuilder().release("4.16").filter(filters).done()
        resp = self.sippy.query_tests(params)
        self.assertGreater(len(resp), 0, "Cannot find any test")
        for test in resp:
            name = test.get("name")
            logger.info(f"test: {name}")
            self.assertRegex(name, '(?i)FIPS')

    def test_start_end_time_picker(self):

        startendtime = StartEndTimePicker()
        logger.info(startendtime.today())
        logger.info(startendtime.lastweek())
        logger.info(startendtime.last2weeks())
        logger.info(startendtime.last4weeks())
        logger.info('')

        startendtime = StartEndTimePicker(DatetimePicker.lastmonth())
        logger.info(startendtime.today())
        logger.info(startendtime.lastweek())
        logger.info(startendtime.last2weeks())
        logger.info(startendtime.last4weeks())
        logger.info('')

        startendtime = StartEndTimePicker(DatetimePicker.anyday(2024, 5, 1))
        logger.info(startendtime.today())
        logger.info(startendtime.lastweek())
        logger.info(startendtime.last2weeks())
        logger.info(startendtime.last4weeks())

    def test_query_component_readiness(self):

        base_startendtime = StartEndTimePicker(DatetimePicker.lastmonth())
        sample_startendtime = StartEndTimePicker()
        params = ParamBuilder().base_release("4.15") \
            .base_starttime(base_startendtime.last4weeks()) \
            .base_endtime(base_startendtime.today()) \
            .sample_release("4.16") \
            .sample_starttime(sample_startendtime.lastweek()) \
            .sample_endtime(sample_startendtime.today()) \
            .confidence() \
            .exclude_arches() \
            .exclude_clouds() \
            .exclude_variants() \
            .ignore_disruption() \
            .ignore_missing() \
            .group_by() \
            .min_fail() \
            .pity() \
            .done()
        resp = self.sippy.query_component_readiness(params)
        rows = resp.get("rows")
        self.assertGreater(len(rows), 1)

        for component in rows:
            name = component.get("component")
            cols = component.get("columns")
            logger.info(f"verifying component <{name}>")
            for col in cols:
                logger.info(col)
                self.assertTrue("status" in col)
            logger.info("OK\n")

    def test_query_variant(self):
        params = ParamBuilder().release("4.16").done()
        resp = self.sippy.query_variant_status(params)
        self.assertGreater(len(resp), 0, "Cannnot get any varaint records")
        for v in resp:
            logger.info(f"name: {v.get('name')}")
            logger.info(
                f"current_pass_percentage: {v.get('current_pass_percentage')}")
            logger.info(
                f"previous_pass_percentage: {v.get('previous_pass_percentage')}\n")

    def test_analyze_component_readiness(self):

        base_startendtime = StartEndTimePicker(DatetimePicker.lastmonth())
        sample_startendtime = StartEndTimePicker()
        params = ParamBuilder().base_release("4.15") \
            .base_starttime(base_startendtime.last4weeks()) \
            .base_endtime(base_startendtime.today()) \
            .sample_release("4.16") \
            .sample_starttime(sample_startendtime.lastweek()) \
            .sample_endtime(sample_startendtime.today()) \
            .confidence() \
            .exclude_arches() \
            .exclude_clouds() \
            .exclude_variants() \
            .ignore_disruption() \
            .ignore_missing() \
            .group_by() \
            .done()

        analyzer = self.sippy.analyze_component_readiness(params)
        self.assertTrue(
            analyzer.is_component_readiness_status_green() == False)

    def test_analyze_variant_status(self):

        self.assertRaises(ValueError, DataAnalyzer, None)

        analyzer = self.sippy.analyze_variants(
            ParamBuilder().release("4.16").done())
        self.assertFalse(analyzer.is_variants_status_green())
        self.assertTrue(analyzer.is_variants_status_green(
            ['gcp', 'upgrade', 'realtime']))
