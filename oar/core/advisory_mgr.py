from errata_tool import Erratum
from errata_tool import ErrataException
from oar.core.config_store import ConfigStore
from oar.core.exceptions import AdvisoryException
from oar.core.jira_mgr import JiraManager, JiraException
from oar.core.const import *
import logging

logger = logging.getLogger(__name__)


class AdvisoryManager:
    """
    AdvisoryManager will be used to communicate with Errata Tool API to get/update advisory
    Kerbros ticket is required to use this tool
    """

    def __init__(self, cs: ConfigStore):
        self._cs = cs

    def get_advisories(self):
        """
        Get all advisories

        Returns:
            []Advisory: all advisory wrappers
        """
        ads = []
        for k, v in self._cs.get_advisories().items():
            ad = Advisory(
                errata_id=v,
                impetus=k,
            )
            ads.append(ad)

        return ads

    def get_jira_issues(self):
        """
        Get all jira issues from advisories in a release

        Returns:
            []: all jira issues from advisories
        """
        all_jira_issues = []
        try:
            for ad in self.get_advisories():
                all_jira_issues += ad.jira_issues
        except ErrataException as e:
            raise AdvisoryException("get jira issue from advisory failed") from e

        return all_jira_issues

    def change_ad_owners(self):
        """
        Change QA owner of all the advisories

        Raises:
            AdvisoryException: error when communicate with errata tool

        Returns:
            updated_ads ([]): updated advisory id list
            abnormal_ads ([]): advisory id list of the ones state are not QE
        """
        updated_ads = []
        abnormal_ads = []
        try:
            for ad in self.get_advisories():
                # check advisory status, if it is not QE, log warn message
                if ad.errata_state != "QE":
                    logger.warn(f"advisory state is not QE, it is {ad.errata_state}")
                    abnormal_ads.append(ad.errata_id)
                ad.change_qe_email(self._cs.get_owner())
                updated_ads.append(ad.errata_id)
        except ErrataException as e:
            raise AdvisoryException("change advisory owner failed") from e

        return updated_ads, abnormal_ads

    def check_greenwave_cvp_tests(self):
        """
        Check whether all the Greenwave CVP tests in all advisories
        All the test status should be PASSED

        Raises:
            AdvisoryException: error found when checking CVP test result

        Returns:
            []test: abnormal test list
        """
        abnormal_tests = []
        try:
            ads = self.get_advisories()
            for ad in ads:
                logger.info(
                    f"checking Greenwave CVP test for advisory {ad.errata_id} ..."
                )
                tests = ad.get_greenwave_cvp_tests()
                all_passed = True
                if len(tests):
                    for t in tests:
                        status = t["attributes"]["status"]
                        logger.debug(f"Greenwave CVP test {t['id']} status is {status}")
                        valid_status = [CVP_TEST_STATUS_PASSED, CVP_TEST_STATUS_PENDING]
                        if status not in valid_status:
                            all_passed = False
                            logger.error(
                                f"Greenwave CVP test {t['id']} status is not {valid_status}"
                            )
                            abnormal_tests.append(t)
                    logger.info(
                        f"Greenwave CVP tests in advisory {ad.errata_id} are {'all' if all_passed else 'not all'} passed"
                    )
                else:
                    logger.info(
                        f"advisory {ad.errata_id} does not have Greenwave CVP tests"
                    )
        except ErrataException as e:
            raise AdvisoryException("Get greenwave cvp test failed") from e

        if len(abnormal_tests):
            logger.error(f"NOT all Greenwave CVP tests are passed")

        return abnormal_tests

    def push_to_cdn_staging(self):
        """
        Trigger push job for stage, if job is triggered, check the result

        Raises:
            AdvisoryException: error when communicate with errata

        Returns:
            bool: job is triggered or not
        """

        # check if all the push jobs are completed, if no, trigger new push job with default value [stage]
        # request with default value will not redo any push which has already successfully completed since the last respin of the advisory. It will redo failed pushes

        triggered = False
        try:
            ads = self.get_advisories()
            for ad in ads:
                if not ad.are_all_push_jobs_completed():
                    ad.push_to_cdn()
                    triggered = True
        except Exception as e:
            raise AdvisoryException("push to cdn failed") from e

        return triggered

    def change_advisory_status(self, status=AD_STATUS_REL_PREP):
        """
        Change advisories status, e.g. REL_PREP

        Args:
            status (str, optional): status used to update. Defaults to REL_PREP.

        Raises:
            AdvisoryException: error when update advisory status

        Returns:
            _type_: _description_
        """
        try:
            ads = self.get_advisories()
            for ad in ads:
                ad.set_state(status.strip())
                logger.info(f"advisory {ad.errata_id} status is changed to {status}")
        except Exception as e:
            raise AdvisoryException(f"change advisory status failed") from e

    def drop_bugs(self):
        """
        Go thru all attached bugs. drop the not verified bugs if they're not critical/blocker/customer_case

        Raises:
            AdvisoryException: error when dropping bugs from advisory

        Returns:
            []: bugs cannot be dropped
        """
        jm = JiraManager(self._cs)
        ads = self.get_advisories()
        all_dropped_bugs = []
        all_must_verify_bugs = []
        for ad in ads:
            bug_list = []
            issues = ad.jira_issues
            if len(issues):
                for key in issues:
                    issue = jm.get_issue(key)
                    if issue.is_verified() or issue.is_closed():
                        continue
                    else:
                        # check whether the issue must be verified
                        if (
                            issue.is_critical_issue()
                            or issue.is_customer_case()
                            or issue.is_cve_tracker()
                        ):
                            logger.warn(
                                f"jira issue {key} is critical: {issue.is_critical_issue()} or customer case: {issue.is_customer_case()} or cve tracker: {issue.is_cve_tracker()}, it must be verified"
                            )
                            all_must_verify_bugs.append(key)
                        else:
                            # issue can be dropped
                            logger.info(
                                f"jira issue {key} is {issue.get_status()} will be dropped from advisory {ad.errata_id}"
                            )
                            bug_list.append(key)

                if len(bug_list):
                    all_dropped_bugs += bug_list
                    ad.remove_bugs(bug_list)
                    logger.info(
                        f"not verified and non-critical bugs are dropped from advisory {ad.errata_id}"
                    )
                else:
                    logger.info(
                        f"there is no bug in advisory {ad.errata_id} can be dropped"
                    )

        return all_dropped_bugs, all_must_verify_bugs


class Advisory(Erratum):
    """
    Wrapper class of Erratum, add more functionalities and properties
    """

    def __init__(self, **kwargs):
        if "impetus" in kwargs:
            self.impetus = kwargs["impetus"]
        try:
            super().__init__(**kwargs)
        except ErrataException as e:
            raise AdvisoryException("initialize erratum failed") from e

    def change_qe_email(self, email):
        """
        Change advisory owner

        Args:
            email (str): owner's email address
        """
        self.update(qe_email=email)
        self.commit()
        logger.info(f"QA Owner of advisory {self.errata_id} is updated to {email}")

    def get_qe_email(self):
        """
        Get qe email of this advisory
        """
        return self.qe_email

    def get_state(self):
        """
        Get advisory state e.g. QE, NEW_FILES
        """
        return self.errata_state

    def set_state(self, state):
        """
        Change advisory state

        Args:
            state (str): state e.g. QE, REL_PREP
        """
        self.setState(state.upper())
        self.commit()
        logger.info(f"advisory {self.errata_id} state is updated to {state.upper()}")

    def remove_bugs(self, bug_list: []):
        """
        Drop bugs from advisory

        Args:
            bugs (str[]): bug list
        """
        self.removeJIRAIssues(bug_list)
        need_refresh = self.commit()
        if need_refresh:
            self.refresh()

    def get_greenwave_cvp_tests(self):
        """
        Get Greenwave CVP test result
        """
        return self.externalTests(test_type="greenwave_cvp")

    def push_to_cdn(self, target):
        """
        Trigger push job with default target. e.g. stage or live
        """
        if target and target in ["stage", "live"]:
            self.push(target=target)
        else:
            self.push()

        logger.info(f"push job for advisory {self.errata_id} is triggered")

    def get_push_job_status(self):
        """
        Get push jobs' status
        """

        url = "/api/v1/erratum/" + str(self.errata_id) + "/push"
        json = self._get(url)

        return json

    def are_all_push_jobs_completed(self):
        """
        Check all push jobs status for different types  e.g. cdn_stage, cdn_docker_stage etc.

        Returns:
            bool: True if jobs for different types are all complete, otherwise False
        """
        logger.info(f"checking push job status for advisory {self.errata_id} ...")
        job_result = {}
        json = self.get_push_job_status()
        for cached_job in json:
            job_id = cached_job["id"]
            job_status = cached_job["status"]
            job_target = cached_job["target"]["name"]

            if job_target in job_result:
                cached_job = job_result[job_target]
                cached_id = cached_job["id"]
                if job_id > cached_id:
                    cached_job["id"] = job_id
                    cached_job["status"] = job_status
            else:
                job_result[job_target] = {"id": job_id, "status": job_status}

        completed = True if len(job_result) else False
        for cached_target, cached_job in job_result.items():
            cached_id = cached_job["id"]
            cached_status = cached_job["status"]
            logger.info(f"push job for target <{cached_target}> is {cached_status}")
            if cached_status != PUSH_JOB_STATUS_COMPLETE:
                completed = False

        return completed
