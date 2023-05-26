from errata_tool import Erratum
from errata_tool import ErrataException
from oar.core.config_store import ConfigStore
from oar.core.exceptions import AdvisoryException
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
            []Advisory: all advisoriy wrappers
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
            AdvisoryException: _description_
        """
        try:
            for ad in self.get_advisories():
                # check advisory status, if it is not QE, log warn message
                if ad.errata_state != "QE":
                    logger.warn(f"advisory state is not QE, it is {ad.errata_state}")
                ad.change_qe_email(self._cs.get_owner())
        except ErrataException as e:
            raise AdvisoryException("change advisory owner failed") from e

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

    def remove_bugs(self, bugs):
        """
        Drop bugs from advisory

        Args:
            bugs (str[]): bug list
        """
        self.removeBugs(bugs)
        need_refresh = self.commit()
        if need_refresh:
            self.refresh()

    def get_greenwave_cvp_tests(self):
        """
        Get Greenwave CVP test result
        """

        return self.externalTests(test_type="greenwave_cvp")
