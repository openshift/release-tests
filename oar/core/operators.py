import logging
import oar.core.util as util

from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData

logger = logging.getLogger(__name__)

class ReleaseOwnershipOperator:
    """Handles composite ownership operations across advisories and shipments"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)

    def update_owners(self, email: str) -> tuple[list, list]:
        """
        Update ownership across advisories and shipments
        
        Args:
            email (str): Email of the new owner
            
        Returns:
            tuple[list, list]: (list of updated advisories, list of advisories with abnormal states)
        """
        try:
            updated_ads, abnormal_ads = self._am.change_ad_owners()
            if self._sd._cs.is_konflux_flow():
                self._sd.add_qe_release_lead_comment(email)
            return updated_ads, abnormal_ads
        except Exception as e:
            logger.error(f"Failed to update owners: {str(e)}")
            raise

class BugOperator:
    """Handles composite bug operations across advisories and shipments"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)
        self._jm = JiraManager(cs)

    def get_jira_issues(self) -> list:
        """
        Get jira issues from both advisory and shipment sources
        
        Returns:
            list: Combined list of jira issues from all sources
        """
        try:
            advisory_issues = self._am.get_jira_issues()
            shipment_issues = self._sd.get_jira_issues() if self._sd._cs.is_konflux_flow() else []
            return sorted(set(advisory_issues + shipment_issues))
        except Exception as e:
            logger.error(f"Bug sync failed: {str(e)}")
            raise

    def drop_bugs(self) -> tuple[list, list]:
        """Execute bug drop operation across both sources
        
        Returns:
            tuple[list, list]: (list of successfully dropped bugs, list of high severity bugs that couldn't be dropped)
        """
        try:
            # Drop from advisories first
            dropped_from_ads = self._am.drop_bugs()
            
            # Then drop from shipments if konflux flow
            if self._sd._cs.is_konflux_flow():
                dropped_from_shipments = self._sd.drop_bugs()
                return (dropped_from_ads + dropped_from_shipments)
            
            return dropped_from_ads
        except Exception as e:
            logger.error(f"Bug drop failed: {str(e)}")
            raise

    def has_finished_all_jiras(self) -> bool:
        """
        Check if all jira issues are in finished state
        
        Finished states include: Closed, Verified or Release Pending
        
        Returns:
            bool: True if all jira issues are finished, False otherwise
        """
        try:
            has_finished_all = True
            
            # Check advisory jiras
            for ad in self._am.get_advisories():
                for jira_key in ad.jira_issues:
                    if not self._jm.get_issue(jira_key).is_finished():
                        logger.warning(f"Advisory {ad.errata_id} has unfinished jira {jira_key}")
                        has_finished_all = False
            
            # Check shipment jiras if konflux flow
            if self._sd._cs.is_konflux_flow():
                for jira_key in self._sd.get_jira_issues():
                    if not self._jm.get_issue(jira_key).is_finished():
                        logger.warning(f"Shipment has unfinished jira {jira_key}")
                        has_finished_all = False
            
            return has_finished_all
        except Exception as e:
            logger.error(f"Jira status check failed: {str(e)}")
            raise


class ApprovalOperator:
    """Handles approval operations based on release flow type (errata or konflux)"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)

    def approve_release(self) -> bool:
        """
        Execute approval operations based on release flow type (errata or konflux)
        
        For konflux flow:
        - Adds QE approval to shipment
        - Changes RPM advisory status to REL_PREP only if payload metadata URL is accessible
          for the Y-stream release (e.g. 4.19)
        
        For errata flow:
        - Changes all advisory statuses to REL_PREP
        
        Note: The payload metadata URL check ensures we don't prematurely move advisories
        before the url is accessible.
        
        Returns:
            bool: True if all approvals succeeded, False if payload metadata URL not accessible (konflux only)
            
        Raises:
            Exception: If approval operations fail for either flow type
        """
        try:
            # Only handle shipment approval for konflux flow
            if self._sd._cs.is_konflux_flow():
                self._sd.add_qe_approval()
                # only move rpm advisory status when payload metadata url is accessible
                if util.is_payload_metadata_url_accessible(util.get_y_release(self._am._cs.release)):
                    # when the release is Konflux based, only rpm advisory is available in AdvisoryManager
                    self._am.change_advisory_status()
                    return True
                return False
            else:
                # Move all the advisories to REL_PREP
                self._am.change_advisory_status()
                return True
        except Exception as e:
            logger.error(f"Failed to approve release: {str(e)}")
            raise


class ImageHealthOperator:
    """Handles image health check operations for both advisory and shipment data"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)
        self._nm = NotificationManager(cs)

    def check_image_health(self) -> bool:
        """
        Check image container health (grade info) handling different release flows:
        - Konflux: Checks shipment data and adds comment to MR
        - Errata: Checks advisory data and sends notifications for unhealthy containers
        
        Returns:
            bool: True if all image containers are healthy (grade A or B), False otherwise
            
        Raises:
            Exception: If health check operations fail
        """
        healthy = True
        try:
            if self._sd._cs.is_konflux_flow():
                # Konflux flow - check shipment data and add MR comment
                health_data = self._sd.check_component_image_health()
                self._sd.add_image_health_summary_comment(health_data)
                healthy = health_data.unhealthy_count == 0
            else:
                # Errata flow - check advisory data and notify if unhealthy
                unhealthy_ads = self._am.check_advisories_grades_health()
                if unhealthy_ads:
                    self._nm.share_unhealthy_advisories(unhealthy_ads)
                    healthy = False
                
        except Exception as e:
            logger.error(f"Image health check failed: {str(e)}")
            raise

        return healthy


class NotificationOperator:
    """Handles notification operations based on release flow type (errata or konflux)"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)
        self._nm = NotificationManager(cs)

    def share_ownership_change(self, updated_ads, abnormal_ads, updated_subtasks, new_owner) -> None:
        """Share ownership change notification
        
        Args:
            updated_ads (list): Updated advisory list
            abnormal_ads (list): Advisory list that state is not QE
            updated_subtasks (list): Updated jira subtasks
            new_owner (str): Email of new owner
            
        Raises:
            Exception: If notification fails
        """
        try:
            if self._sd._cs.is_konflux_flow():
                mr = self._sd._cs.get_shipment_mr()
                self._nm.share_shipment_mrs_and_ad_info(
                    mr, updated_ads, abnormal_ads, updated_subtasks, new_owner
                )
            else:
                self._nm.share_ownership_change_result(
                    updated_ads, abnormal_ads, updated_subtasks, new_owner
                )
        except Exception as e:
            logger.error(f"Ownership change notification failed: {str(e)}")
            raise
