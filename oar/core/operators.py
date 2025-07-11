from oar.core.advisory import AdvisoryManager
from oar.core.shipment import ShipmentData
from oar.core.jira import JiraManager
import logging

logger = logging.getLogger(__name__)

class ReleaseOwnershipOperator:
    """Handles composite ownership operations across advisories and shipments"""
    
    def __init__(self, cs):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)

    def update_owners(self, email: str) -> tuple[list, list]:
        """Update ownership across advisories and shipments"""
        try:
            updated_ads, abnormal_ads = self._am.change_ad_owners()
            self._sd.add_qe_release_lead_comment(email)
            return updated_ads, abnormal_ads
        except Exception as e:
            logger.error(f"Ownership operation failed: {str(e)}")
            raise

class BugOperator:
    """Handles composite bug operations across advisories and shipments"""
    
    def __init__(self, cs):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)
        self._jm = JiraManager(cs)

    def get_jira_issues(self) -> list:
        """Get jira issues from both advisory and shipment sources"""
        try:
            advisory_issues = self._am.get_jira_issues()
            shipment_issues = self._sd.get_jira_issues()
            return sorted(set(advisory_issues + shipment_issues))
        except Exception as e:
            logger.error(f"Bug sync failed: {str(e)}")
            raise

    def drop_bugs(self) -> tuple[list, list]:
        """Execute bug drop operation across both sources"""
        try:
            # Drop from advisories first
            dropped_from_ads, high_severity = self._am.drop_bugs()
            
            # Then drop from shipments
            high_from_shipments, dropped_from_shipments = self._sd.drop_bugs()
            
            return (
                dropped_from_ads + dropped_from_shipments,
                high_severity + high_from_shipments
            )
        except Exception as e:
            logger.error(f"Bug drop failed: {str(e)}")
            raise
