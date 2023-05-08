from errata_tool import Erratum
from errata_tool import ErrataException
from oar.core.config_store import ConfigStore
from oar.core.exceptions import AdvisoryException


class AdvisoryManager:
    """
    AdvisoryManager will be used to communicate with Errata Tool API to get/update advisory
    Kerbros ticket is required to use this tool
    """

    def __init__(self, cs: ConfigStore):
        self._cs = cs

    def get_jira_issues(self):
        """
        Get all jira issues from advisories in a release

        Returns:
            []: all jira issues from advisories
        """
        all_jira_issues = []
        ads = self._cs.get_advisories()
        for k, v in ads.items():
            ad = Advisory(
                errata_id=v,
                impetus=k,
            )
            all_jira_issues += ad.jira_issues

        return all_jira_issues


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
