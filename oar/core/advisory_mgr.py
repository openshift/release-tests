from errata_tool import Erratum
from errata_tool import ErrataException
from oar.core.config_store import ConfigStore
from oar.core.exceptions import AdvisoryException
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
