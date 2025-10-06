import json
import logging
import re
import subprocess
import koji
import urllib3
import oar.core.util as util
from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import AdvisoryException
from oar.core.jira import JiraManager
from datetime import datetime, timezone
from dateutil import parser
from errata_tool import Erratum, ErrataException, security

logger = logging.getLogger(__name__)


class AdvisoryManager:
    """
    AdvisoryManager is used to communicate with Errata Tool API to get/update advisory
    Kerberos ticket is required to use this tool
    """

    def __init__(self, cs: ConfigStore):
        self._cs = cs

    def get_advisories(self):
        """
        Get all advisories

        Returns:
            list[Advisory]: all advisory wrappers
        """
        ads = []
        for k, v in self._cs.get_advisories().items():
            # in errata flow, handle all advisories except MICROSHIFT and DROPPED_NO_SHIP
            if k != AD_IMPETUS_MICROSHIFT:
                ad = Advisory(errata_id=v, impetus=k)
                if ad.errata_state != AD_STATUS_DROPPED_NO_SHIP:
                    ads.append(ad)
        return ads

    def get_jira_issues(self):
        """
        Get all jira issues from advisories in a release

        Returns:
           list: all jira issues from advisories
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
            updated_ads (list): updated advisory id list
            abnormal_ads (list): advisory id list of the ones state are not QE
        """
        updated_ads = []
        abnormal_ads = []
        try:
            for ad in self.get_advisories():
                # check advisory status, if it is not QE, log warn message
                # if the advisory is released, the state is like [REP_PREP/SHIPPED LIVE], it is not [QE], we should not send alert to ART
                # only check if the state is [NEW_FILES]
                if ad.errata_state == AD_STATUS_NEW_FILES:
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
            test (list): abnormal test list
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

        # check if all push jobs are completed, if not, trigger new push job with default value [stage]
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
            target_status (str, optional): status used to update. Defaults to REL_PREP.

        Raises:
            AdvisoryException: error when update advisory status
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
        Drop unverified bugs from all advisories that are not cve tracker bugs.

        This method iterates through all advisories and identifies bugs in ON_QA status that
        have not been verified. These bugs are removed from the advisories unless they are
        CVE tracker bugs, which must be verified and cannot be dropped

        Raises:
            AdvisoryException: error when dropping bugs from advisory

        Returns:
            list[str]: list of jira keys that were successfully dropped from advisories
        """
        jm = JiraManager(self._cs)
        ads = self.get_advisories()
        all_dropped_bugs = []
        for ad in ads:
            drop_bug_list = jm.get_unverified_issues_excluding_cve(ad.jira_issues)
            if drop_bug_list:
                all_dropped_bugs.extend(drop_bug_list)
                for key in drop_bug_list:
                    issue = jm.get_issue(key)
                # issue can be dropped
                logger.info(
                    f"jira issue {key} is {issue.get_status()}, it will be dropped from advisory {ad.errata_id}"
                )
                ad.remove_bugs(drop_bug_list)
                logger.info(
                    f"not verified and non cve track bugs are dropped from advisory {ad.errata_id}"
                )
            else:
                logger.info(
                    f"there is no bug in advisory {ad.errata_id} that can be dropped"
                )

        return all_dropped_bugs

    def check_cve_tracker_bug(self):
        """
        Call elliott cmd to check if any new CVE tracker bug found

        Raises:
            AdvisoryException: error when invoke elliott cmd

        Returns:
            list: CVE tracker bugs not found in RHSA advisories
        """
        cmd = [
            "elliott",
            "--data-path",
            "https://github.com/openshift-eng/ocp-build-data.git",
            "--group",
            f"openshift-{util.get_y_release(self._cs.release)}",
            "--assembly",
            util.get_release_key(self._cs.release),
            "--build-system",
            "brew",
            "find-bugs",
            "--cve-only",
            "--output",
            "json",
            "--permissive"
        ]

        logger.debug(f"elliott cmd {cmd}")

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise AdvisoryException(f"elliott cmd error:\n {stderr}")

        cve_tracker_bugs = []
        result = stdout.decode("utf-8")
        if result:
            logger.debug(result)
            json_obj = json.loads(result)
            # OCPERT-66 double check if the bug is already attached on advisory
            # get all jira issues from RHSA advisories
            rhsa_ads = [ad for ad in self.get_advisories() if ad.is_rhsa()]
            rhsa_jira_issues = []
            for ad in rhsa_ads:
                rhsa_jira_issues += ad.jira_issues
            for trackers in json_obj.values():
                if isinstance(trackers, list):
                    for tracker in trackers:
                        # add it to missed bug list if it is not attached on advisories
                        if tracker not in rhsa_jira_issues:
                            logger.info(f"CVE tracker bug {tracker} is not found in RHSA advisories")
                            cve_tracker_bugs.append(tracker)

        return cve_tracker_bugs

    def get_doc_prodsec_approved_ads(self):
        """
        Get Docs and product security approved advisories
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

    def check_advisories_grades_health(self):
        """
        Check advisories overall grade, advisories image builds grades and return unhealthy advisories.

        Returns:
            list: Unhealthy advisories {errata_id, ad_grade, unhealthy_builds}.
        """
        unhealthy_advisories = []

        for ad in self.get_advisories():
            if ad.impetus == AD_IMPETUS_RPM:
                logger.info(
                    f"skipping RPM advisory - {ad.errata_id}, it has no container")
                continue

            ad_grade = ad.get_overall_grade()

            if not util.is_grade_healthy(ad_grade):
                logger.error(
                    f"advisory {ad.errata_id} is unhealthy, overall grade is {ad_grade}")
                unhealthy_builds = ad.get_unhealthy_builds()
                unhealthy_advisories.append(
                    {"errata_id": ad.errata_id, "ad_grade": ad_grade, "unhealthy_builds": unhealthy_builds})

                for ub in unhealthy_builds:
                    logger.error(
                        f"build {ub['nvr']} for architecture {ub['arch']} with grade {ub['grade']} is unhealthy")
            else:
                logger.info(
                    f"advisory {ad.errata_id} is healthy, overall grade is {ad_grade}")

        return unhealthy_advisories
    
    def has_finished_all_advisories_jiras(self):
        """
        Check all advisories jiras are finished (Closed, Verified or Release Pending) or they are dropped from advisories.

        Returns:
            bool: True if all advisories jiras are finished, False otherwise
        """
        jm = JiraManager(self._cs)
        has_finished_all_advisories_jiras = True

        for ad in self.get_advisories():
            for jira_key in ad.jira_issues:
                if not jm.get_issue(jira_key).is_finished():
                    logger.warning(f"Advisory {ad.errata_id} has unfinished jira {jira_key}")
                    has_finished_all_advisories_jiras = False

        return has_finished_all_advisories_jiras

class Advisory(Erratum):
    """
    Wrapper class of Erratum, add more functionalities and properties
    """

    def __init__(self, **kwargs):
        if "impetus" in kwargs:
            self.impetus = kwargs["impetus"]
        self.push_job_status = {}
        self.no_push_job = False
        # temp w/a to handle INC3282265 - errata.devel.redhat.com certificate has expired
        # TODO: when errata cert is updated, rollback this change
        security.security_settings._verify_ssl = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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

    def remove_bugs(self, bug_list: list[str]):
        """
        Drop bugs from advisory

        Args:
            bug_list (list[str]): bug list
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
        Check if doc is approved for an advisory

        Returns:
            bool: True if doc for an advisory is approved, otherwise False
        """
        return self.get_erratum_data()["doc_complete"] == 1

    def is_prodsec_approved(self):
        """
        Check if prodsec is approved for an advisory

        Returns:
            bool: True if prodsec is approved, otherwise False
        """
        return self.get_erratum_data()["security_approved"] == True

    def is_doc_requested(self):
        """
        Check if doc for an advisory is requested

        Returns:
            bool: True if doc for an advisory is requested, otherwise False
        """
        return self.get_erratum_data()["text_ready"] == 1

    def is_prodsec_requested(self):
        """
        Check if prodsec for an advisory is requested

        Returns:
            bool: False if prodsec for an advisory is requested, otherwise False
        """
        return self.get_erratum_data()["security_approved"] == False

    def request_doc_approval(self):
        """
        Send doc approval request for an advisory
        """
        pdata = {"advisory[text_ready]": 1}
        url = "/api/v1/erratum/%i" % self.errata_id
        r = self._put(url, data=pdata)
        self._processResponse(r)

    def request_prodsec_approval(self):
        """
        Send product security approval request for an advisory
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

    def refresh_security_alerts(self):
        """
        Makes a request to the ProdSec errata review microservice to refresh the security alert data for an RHSA.
        """
        if self.errata_type == "RHSA":
            url = "/api/v1/erratum/%i/security_alerts/refresh" % self.errata_id
            resp = self._post(url)
            resp.raise_for_status()
            return resp.json()
        else:
            logger.warning(
                f"RHBA advisory {self.errata_id} does not have secalerts")
            return None

    def has_blocking_secruity_alert(self):
        """
        Check RHSA advisory has blocking security alert
        """
        # get refreshed results directly
        json_dict = self.refresh_security_alerts()
        if json_dict:
            alerts = json_dict["alerts"]
            # if alerts are empty or attr blocking not found, return false
            if len(alerts) == 0 or "blocking" not in alerts:
                logger.warning(
                    f"Cannot find alerts for advisory {self.errata_id}")
                return False
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

    def get_unhealthy_builds(self):
        """
        Get unhealthy builds of advisory.

        Returns:
            list: Unhealthy builds.
        """
        unhealthy_builds = []

        for product_version in self.errata_builds:
            for nvr in self.errata_builds[product_version]:
                build_grades = self.get_build_grades(nvr)
                for bg in build_grades:
                    if not util.is_grade_healthy(bg["grade"]):
                        unhealthy_builds.append(bg)

        return unhealthy_builds

    def get_build_grades(self, nvr):
        """
        Get all architecture grades of build.

        Returns:
            list: All architecture grades of build {nvr, architecture, grade}.
        """
        nvr_url = "https://pyxis.engineering.redhat.com/v1/images/nvr/%s?include=data.freshness_grades&include=data.architecture" % nvr
        resp = self._get(nvr_url, raw=True)
        nvr_grades = []

        if resp.ok:
            for arch in resp.json()["data"]:
                effective_grade = None
                for fg in arch["freshness_grades"]:
                    checked_grade = fg["grade"]
                    start_date = parser.parse(fg["start_date"])

                    # skip if checked grade is not effective yet
                    if start_date > datetime.now(timezone.utc):
                        continue

                    # skip if checked grade is no longer effective
                    if "end_date" in fg and parser.parse(fg["end_date"]) < datetime.now(timezone.utc):
                        continue

                    # skip if checked grade is smaller than current effective grade (if intervals are overlapping, bigger grade is taken)
                    if effective_grade and checked_grade < effective_grade:
                        continue

                    # save new effective grade
                    effective_grade = checked_grade

                nvr_grades.append(
                    {"nvr": nvr, "arch": arch["architecture"], "grade": effective_grade})
        else:
            raise AdvisoryException(f"error when accessing build nvr - {nvr}")
        return nvr_grades

    def get_overall_grade(self):
        """
        Get overall grade of advisory.

        Retruns:
            str: Overall grade of advisory.
        """
        container_url = f"{util.get_advisory_domain_url()}/errata/container/{self.errata_id}"
        resp = self._get(container_url, raw=True)

        if resp.ok:
            search_result = re.search(
                "Docker Container Content - ([A-F])", resp.text)
            if search_result:
                return search_result.group(1)
            else:
                raise AdvisoryException(
                    f"cannot find overall advisory grade - {self.errata_id}")
        else:
            raise AdvisoryException(
                f"error when accessing advisory containers - {self.errata_id}")

    def check_kernel_tag(self):
        """
        Check kernel tag from advisory build image.

        Returns:
            bool: True if kernel build is tagged with early-kernel-stop-ship.
        """
        #Check if impetus is image/rhcos or not, if it's not then skip this function.
        if self.impetus not in [AD_IMPETUS_IMAGE, AD_IMPETUS_RHCOS]:
            logger.info(f"{self.impetus} advisory does not have RHCOS build, skip checking kernel tag")
            return False
        #Get rhcos nvr from image advisory build
        build_response = self._get(f"/api/v1/erratum/{self.errata_id}/builds")
        rhcos_nvr = None
        for value in build_response.values():
            for build in value['builds']:
                for build_name in build.keys():
                    if build_name.startswith("rhcos-x86"):
                        rhcos_nvr = build_name
                        break
        logger.info(f"RHCOS nvr is {rhcos_nvr}")
        # if there is no rhcos build found, skip checking
        if rhcos_nvr is None:
            logger.warning("No RHCOS nvr found, skip kernel tag checking")
            return False
        #Download the commit metadata based on info in nvr.
        rhcos_nvr_url = re.sub(r"-([\d.]+)-(\d+)$", r"/\1/\2", rhcos_nvr)
        rhcos_nvr_url_full = "https://download.engineering.redhat.com/brewroot/packages/"+rhcos_nvr_url+"/metadata.json"
        rhos_meta_data_full = self._get(rhcos_nvr_url_full)
        kernel_build = [
            f"{comp['name']}-{comp['version']}-{comp['release']}"
            for entry in rhos_meta_data_full['output']
            if entry['components']
            for comp in entry['components']
            if comp['name'] == 'kernel'
        ][0]
        logger.info(f"The commit metadata is {kernel_build}")
        #Use koji api to query tags of this build
        session = koji.ClientSession("https://brewhub.engineering.redhat.com/brewhub")
        tags = session.listTags(build=kernel_build)
        logger.info(f"Tags of this build is {tags}")
        for t in tags:
            if t["name"] == 'early-kernel-stop-ship':
                logger.info("kernel tag early-kernel-stop-ship is detected")
                return True
        return False

    def is_rhsa(self):
        return self.errata_type == 'RHSA'
