from errata_tool import Erratum
from errata_tool import ErrataException
from oar.core.config_store import ConfigStore
from oar.core.exceptions import AdvisoryException
from oar.core.jira_mgr import JiraManager, JiraException
from oar.core.const import *
import oar.core.util as util
import logging
import subprocess
import json

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
            if ad.errata_state != AD_STATUS_DROPPED_NO_SHIP:
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
            raise AdvisoryException(
                "get jira issue from advisory failed") from e

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
                # if the advisory is released, the state is like [REP_PREP/SHIPPED LIVE], it is not [QE], we should not send alert to ART
                # only check if the state is [NEW_FILES]
                # talked with ART, microshift advisory should be excluded from this check
                if ad.errata_state == AD_STATUS_NEW_FILES and ad.impetus != AD_IMPETUS_MICROSHIFT:
                    logger.warning(
                        f"advisory state is not QE, it is {ad.errata_state}")
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
        valid_status = [CVP_TEST_STATUS_PASSED, CVP_TEST_STATUS_WAIVED]
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
                        logger.info(
                            f"Greenwave CVP test {t['id']} status is {status}")
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

        triggered_ads = []
        try:
            ads = self.get_advisories()
            for ad in ads:
                if (ad.push_to_cdn()):
                    triggered_ads.append(ad.errata_id)
        except Exception as e:
            raise AdvisoryException("push to cdn failed") from e

        return len(triggered_ads) == len(ads)

    def change_advisory_status(self, target_status=AD_STATUS_REL_PREP):
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
                if target_status == AD_STATUS_REL_PREP and ad.get_state() != AD_STATUS_QE:
                    logger.warning(
                        f"cannot change state of advisory {ad.errata_id} from {target_status} to {ad.get_state()}, skip")
                    continue
                if ad.has_blocking_secruity_alert():
                    raise AdvisoryException(
                        f"advisory {ad.errata_id} has blocking secalerts, please contact prodsec team")
                ad.set_state(target_status.strip())
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
                            logger.warning(
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

    def check_cve_tracker_bug(self):
        """
        Call elliott cmd to check if any new CVE tracke bug found

        Raises:
            AdvisoryException: error when invoke elliott cmd

        Returns:
            json: missed CVE tracker bugs
        """
        cmd = [
            "elliott",
            "--data-path",
            "https://github.com/openshift-eng/ocp-build-data.git",
            "--group",
            f"openshift-{util.get_y_release(self._cs.release)}",
            "--assembly",
            self._cs.release,
            "find-bugs:sweep",
            "--include-status",
            "ON_QA",
            "--include-status",
            "MODIFIED",
            "--include-status",
            "VERIFIED",
            "--cve-only",
            "--report",
            "--output",
            "json",
        ]

        logger.debug(f"elliott cmd {cmd}")

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise AdvisoryException(f"elliott cmd error:\n {stderr}")

        cve_tracker_bugs = []
        result = stdout.decode("utf-8")
        if result:
            logger.info("found new CVE tracker bug")
            logger.debug(result)
            json_obj = json.loads(result)
            for tracker in json_obj:
                id = tracker["id"]
                summary = tracker["summary"]
                logger.info(f"{id}: {summary}")
                cve_tracker_bugs.append(id)

        return cve_tracker_bugs

    def get_doc_prodsec_approved_ads(self):
        """
        get Docs and product security approved advisories
        """
        try:
            approved_doc_ads = []
            approved_prodsec_ads = []
            ads = self.get_advisories()
            for ad in ads:
                if ad.is_doc_approved():
                    approved_doc_ads.append(ad)
                if ad.errata_type == "RHSA" and ad.is_prodsec_approved():
                    approved_prodsec_ads.append(ad)
            return approved_doc_ads, approved_prodsec_ads
        except Exception as e:
            raise AdvisoryException(
                f"get request Docs and Prodsec approved advisories failed"
            ) from e


class Advisory(Erratum):
    """
    Wrapper class of Erratum, add more functionalities and properties
    """

    def __init__(self, **kwargs):
        if "impetus" in kwargs:
            self.impetus = kwargs["impetus"]
        self.push_job_status = {}
        self.no_push_job = False
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
        logger.info(
            f"QA Owner of advisory {self.errata_id} is updated to {email}")

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
        logger.info(
            f"advisory {self.errata_id} state is updated to {state.upper()}")

    def remove_bugs(self, bug_list: list):
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

    def push_to_cdn(self, target="stage"):
        """
        Trigger push job with default target. e.g. stage or live

        if all push jobs are completed, return true
        if any push job is running and there is no failed job, return false. i.e. action is in progress
        if no jobs are triggered or there is any failed job found (retry), trigger the push job with target [stage]
        if any blocking advisory found, trigger push job for it
        if all the blocking jobs are completed, trigger push job for current advisory

        """

        if self.are_push_jobs_completed():
            return True
        elif self.are_push_jobs_running() and not self.has_failed_push_job():
            return False
        else:
            # logic to trigger jobs for blocking advisories
            if self.has_dependency():
                blocking_ads = self.get_blocking_advisories()
                for ad in blocking_ads:
                    ad.push_to_cdn()
                blocking_jobs_completed = True
                for ad in blocking_ads:
                    if ad.are_push_jobs_running():
                        blocking_jobs_completed = False
                        logger.warning(
                            f"push jobs of blocking advisory {ad.errata_id} are not completed yet, will not trigger push job for {self.errata_id}, please try again later")
                if not blocking_jobs_completed:
                    return False
            # logic to trigger jobs for current advisory
            if target and target in ["stage", "live"]:
                self.push(target=target)
            else:
                self.push()

            logger.info(f"push job for advisory {self.errata_id} is triggered")

            return False

    def get_push_job_status(self):
        """
        Get push jobs' status
        """

        # if the cached result is not empty or no push job found, won't get status again
        if len(self.push_job_status) or self.no_push_job:
            return

        url = "/api/v1/erratum/" + str(self.errata_id) + "/push"
        json = self._get(url)

        logger.info(
            f"checking push job status for advisory {self.errata_id} ...")

        if len(json) == 0:
            self.no_push_job = True
            logger.info(f"no push job found for advisory {self.errata_id}")

        for cached_job in json:
            job_id = cached_job["id"]
            job_status = cached_job["status"]
            job_target = cached_job["target"]["name"]

            if job_target in self.push_job_status:
                cached_job = self.push_job_status[job_target]
                cached_id = cached_job["id"]
                if job_id > cached_id:
                    cached_job["id"] = job_id
                    cached_job["status"] = job_status
            else:
                self.push_job_status[job_target] = {
                    "id": job_id, "status": job_status}

        for cached_target, cached_job in self.push_job_status.items():
            cached_id = cached_job["id"]
            cached_status = cached_job["status"]
            logger.info(
                f"push job for target <{cached_target}> is {cached_status}")

    def are_push_jobs_completed(self):
        """
        Check all push jobs status for different types  e.g. cdn_stage, cdn_docker_stage etc.

        Returns:
            bool: True if jobs for different types are triggered and no failed job found, otherwise False
        """

        self.get_push_job_status()

        completed = True if len(self.push_job_status) else False
        for cached_target, cached_job in self.push_job_status.items():
            cached_status = cached_job["status"]
            if cached_status != PUSH_JOB_STATUS_COMPLETE:
                completed = False
                break

        return completed

    def are_push_jobs_running(self):
        """
        Check if push jobs are triggered

        Returns:
            bool: if jobs are running return true
        """

        return (not self.are_push_jobs_completed()) and len(self.push_job_status)

    def has_failed_push_job(self):
        """
        Check if any push job is failed

        Returns:
            bool: return true if any failed job found
        """

        self.get_push_job_status()

        has_failed_job = False
        jobs = self.push_job_status.values()
        for job in jobs:
            if PUSH_JOB_STATUS_FAILED == job['status']:
                has_failed_job = True
                break

        if has_failed_job:
            logger.warning("found failed push job, will trigger again")

        return has_failed_job

    def is_doc_approved(self):
        """
        Check if doc is approved for a advisory
        Returns:
            bool: True if doc for a advisory is approved, otherwise False
        """
        return self.get_erratum_data()["doc_complete"] == 1

    def is_prodsec_approved(self):
        """
        Check if prodsec is approved for a advisory
        Returns:
            bool: True if prodsec is approved, otherwise False
        """
        return self.get_erratum_data()["security_approved"] == True

    def is_doc_requested(self):
        """
        Check if doc for a advisory is requested
        Returns:
            bool: True if doc for a advisory is requested, otherwise False
        """
        return self.get_erratum_data()["text_ready"] == 1

    def is_prodsec_requested(self):
        """
        Check if prodsec for a advisory is requested
        Returns:
        bool: False if prodsec for a advisory is requested, otherwise False
        """
        return self.get_erratum_data()["security_approved"] == False

    def request_doc_approval(self):
        """
        send doc approval request for a advisory
        """
        pdata = {"advisory[text_ready]": 1}
        url = "/api/v1/erratum/%i" % self.errata_id
        r = self._put(url, data=pdata)
        self._processResponse(r)

    def request_prodsec_approval(self):
        """
        send product security approval request for a advisory
        """
        pdata = {"advisory[security_approved]": False}
        url = "/api/v1/erratum/%i" % self.errata_id
        r = self._put(url, data=pdata)
        self._processResponse(r)

    def has_dependency(self):
        """
        Check whether there is any dependent advisories
        """
        blocking_ads = self.get_erratum_data()['blocking_advisories']
        logger.info(
            f"advisory {self.errata_id} has blocking advisory {blocking_ads}")
        return len(blocking_ads) > 0

    def get_blocking_advisories(self):
        """
        Get dependent advisory list
        """
        blocking_ads = []
        ad_list = self.get_erratum_data()['blocking_advisories']
        if len(ad_list) > 0:
            for id in ad_list:
                ad = Advisory(errata_id=id)
                blocking_ads.append(ad)

        return blocking_ads

    def get_security_alerts(self):
        """
        Get secalerts for current advisory
        """
        if self.errata_type == "RHSA":
            url = "/api/v1/erratum/%i/security_alerts" % self.errata_id
            return self._get(url)
        else:
            # RHBA does not have secalerts
            logger.warning(
                f"RHBA advisory {self.errata_id} does not have secalerts")
            return None

    def has_blocking_secruity_alert(self):
        """
        Check is RHSA advisory has blocking secalert
        """
        json_dict = self.get_security_alerts()
        if json_dict:
            alerts = json_dict["alerts"]
            blocking = alerts["blocking"]
            if blocking:
                logger.info(
                    f"found blocking secalert on advisory {self.errata_id}")
                logger.info(json.dumps(alerts["alerts"], indent=2))
            else:
                logger.info(
                    f"RHSA advisory {self.errata_id} does not have blocking secalert")
            return blocking
        else:
            return False
