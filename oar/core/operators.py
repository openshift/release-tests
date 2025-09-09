import logging
import schedule
import datetime
import time
import tempfile
import os
import multiprocessing
import oar.core.util as util

from typing import Union
from oar.core.advisory import AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.worksheet import WorksheetManager
from oar.core.const import *

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
        
    def _get_scheduler_lock_file(self, minor_release: str) -> str:
        """Get the path for the scheduler lock file for a specific release"""
        return os.path.join(tempfile.gettempdir(), f"oar_scheduler_{minor_release}.lock")
        
    def _is_scheduler_running(self, minor_release: str) -> bool:
        """Check if scheduler is already running by checking for lock file"""
        lock_file = self._get_scheduler_lock_file(minor_release)
        return os.path.exists(lock_file)
        
    def _acquire_scheduler_lock(self, minor_release: str) -> bool:
        """Acquire scheduler lock by creating lock file"""
        lock_file = self._get_scheduler_lock_file(minor_release)
        try:
            # Create lock file
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
            return True
        except (IOError, OSError):
            logger.warning(f"Failed to create scheduler lock file: {lock_file}")
            return False
            
    def _release_scheduler_lock(self, minor_release: str) -> None:
        """Release scheduler lock by removing lock file"""
        lock_file = self._get_scheduler_lock_file(minor_release)
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
                logger.info("Scheduler lock released")
        except (IOError, OSError):
            logger.warning(f"Failed to remove scheduler lock file: {lock_file}")

    def _background_metadata_checker(self, minor_release: str) -> None:
        """
        Background process that checks metadata URL accessibility and sends notifications
        
        This runs in a separate process and handles the periodic checking of metadata URL
        accessibility with proper timeout and notification handling.
        """
        TIMEOUT_DAYS = 2
        # Capture all log messages during execution
        log_messages = []
        
        # Create a custom logger to capture messages
        class LogCaptureHandler(logging.Handler):
            def __init__(self, log_messages):
                super().__init__()
                self.log_messages = log_messages
                
            def emit(self, record):
                log_entry = self.format(record)
                self.log_messages.append(log_entry)
        
        # Add the capture handler to the logger
        capture_handler = LogCaptureHandler(log_messages)
        capture_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(capture_handler)
        
        # Get test report for current release
        report = WorksheetManager(self._am._cs).get_test_report()
        
        try:
            # Check if scheduler is already running using file lock
            if self._is_scheduler_running(minor_release):
                logger.warning(f"Scheduler is already running for release {minor_release} (lock file exists), skipping additional instance")
                return
            
            # Acquire scheduler lock
            if not self._acquire_scheduler_lock(minor_release):
                logger.warning("Failed to acquire scheduler lock, skipping additional instance")
                return
            
            logger.info("Scheduler lock acquired")
            
            try:
                # Create a shared variable to track success
                accessible = False
                check_count = 0
                
                # Define a wrapper function that can set the accessible flag
                def check_metadata_accessibility():
                    nonlocal accessible, check_count
                    check_count += 1
                    logger.info(f"Scheduler check #{check_count}: Checking payload metadata URL accessibility for release {minor_release}")
                    if util.is_payload_metadata_url_accessible(minor_release):
                        accessible = True
                        logger.info("Payload metadata URL is now accessible")
                    else:
                        logger.info(f"Scheduler check #{check_count}: Payload metadata URL still not accessible")
                
                # Schedule the check to run every 30 minutes
                schedule.every(30).minutes.do(check_metadata_accessibility)
                logger.info("Scheduler started: Checking payload metadata URL every 30 minutes")
                
                # Calculate the time when the process should exit.
                start_time = datetime.datetime.now()
                end_time = start_time + datetime.timedelta(days=TIMEOUT_DAYS)
                
                # Log initial timing information
                logger.info(f"Scheduler will run until {end_time.strftime('%Y-%m-%d %H:%M:%S')} or until URL becomes accessible")
                
                # This loop runs until the job is successful or the timeout is reached.
                while datetime.datetime.now() < end_time and not accessible:
                    # Calculate time until next scheduled run
                    next_run = schedule.idle_seconds()
                    if next_run is None:
                        # No more jobs scheduled, break out
                        logger.info("No more scheduled jobs, breaking out of scheduler loop")
                        break
                    if next_run > 0:
                        # Sleep until next scheduled run or timeout, whichever comes first
                        sleep_time = min(next_run, (end_time - datetime.datetime.now()).total_seconds())
                        if sleep_time > 0:
                            remaining_time = end_time - datetime.datetime.now()
                            logger.info(f"Scheduler sleeping for {sleep_time:.0f} seconds (timeout in {remaining_time})")
                            time.sleep(sleep_time)
                    # Run pending jobs
                    schedule.run_pending()
                
                if accessible:
                    # Move advisories to REL_PREP
                    self._am.change_advisory_status()
                    
                    # Update test report status to PASS
                    try:
                        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_PASS)
                        report.update_task_status(LABEL_TASK_NIGHTLY_BUILD_TEST, TASK_STATUS_PASS)
                        report.update_task_status(LABEL_TASK_SIGNED_BUILD_TEST, TASK_STATUS_PASS)
                        logger.info("Test report status updated to PASS")
                    except Exception as e:
                        logger.error(f"Failed to update test report status: {str(e)}")
                    
                    # Add success summary to logs
                    success_message = f"Release approval completed. Payload metadata URL is now accessible and advisories have been moved to REL_PREP."
                    log_messages.append(success_message)
                    
                    # Send completion notification with full logs including summary
                    self._send_completion_notification(minor_release, success=True, log_messages=log_messages)
                else:
                    logger.warning(f"Timeout reached after {TIMEOUT_DAYS} days, payload metadata URL still not accessible")
                    
                    # Update test report status to FAIL for timeout
                    try:
                        report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
                        logger.info("Test report status updated to FAIL due to timeout")
                    except Exception as e:
                        logger.error(f"Failed to update test report status: {str(e)}")
                    
                    # Add timeout summary to logs
                    timeout_message = f"Release approval timeout. Payload metadata URL still not accessible after {TIMEOUT_DAYS} days."
                    log_messages.append(timeout_message)
                    
                    # Send timeout notification with full logs including summary
                    self._send_completion_notification(minor_release, success=False, log_messages=log_messages)
            finally:
                # Always release scheduler lock when done
                self._release_scheduler_lock(minor_release)
                # Clear all scheduled jobs
                schedule.clear()
                logger.info("All scheduled jobs cleared")
        except Exception as e:
            logger.error(f"Background metadata checker failed: {str(e)}")
            
            # Update test report status to FAIL for error
            try:
                report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
                logger.info("Test report status updated to FAIL due to error")
            except Exception as update_error:
                logger.error(f"Failed to update test report status: {str(update_error)}")
            
            # Add error summary to logs
            error_message = f"Release approval failed with error: {str(e)}"
            log_messages.append(error_message)
            
            # Send error notification with full logs including summary
            self._send_completion_notification(minor_release, success=False, error=str(e), log_messages=log_messages)
        finally:
            # Remove the capture handler
            logger.removeHandler(capture_handler)

    def _send_completion_notification(self, minor_release: str, success: bool, error: str = None, log_messages: list = None) -> None:
        """
        Send completion notification based on environment variables
        
        If Slack context is available in environment variables, send full logs to specific thread.
        Otherwise, send summary only to default QE release channel.
        """
        try:
            # Use the new NotificationManager method
            nm = NotificationManager(self._am._cs)
            release = self._am._cs.release
            
            nm.share_release_approval_completion(
                release=release,
                success=success,
                error=error,
                log_messages=log_messages
            )
                
        except Exception as e:
            logger.error(f"Failed to send completion notification: {str(e)}")

    def approve_release(self) -> Union[bool, str]:
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
            bool: True if all approvals succeeded, False if payload metadata URL not accessible and scheduler already running
            str: "SCHEDULED" if background job started
            
        Raises:
            Exception: If approval operations fail for either flow type
        """
        try:
            # Only handle shipment approval for konflux flow
            if self._sd._cs.is_konflux_flow():
                self._sd.add_qe_approval()
                # only move rpm advisory status when payload metadata url is accessible
                minor_release = util.get_y_release(self._am._cs.release)
                
                # Check if metadata URL is accessible immediately
                if util.is_payload_metadata_url_accessible(minor_release):
                    # when the release is Konflux based, only rpm advisory is available in AdvisoryManager
                    self._am.change_advisory_status()
                    return True
                
                # If not accessible immediately, launch background process
                logger.info(f"Payload metadata URL not accessible immediately, scheduling background check...")
                
                # Check if scheduler is already running using file lock
                if self._is_scheduler_running(minor_release):
                    logger.warning(f"Scheduler is already running for release {minor_release} (lock file exists), skipping additional instance")
                    return False
                
                # Launch background process for metadata checking
                process = multiprocessing.Process(
                    target=self._background_metadata_checker,
                    args=(minor_release,)
                )
                process.daemon = False  # Allow process to complete cleanup and timeout handling (non-daemon processes continue after parent exit on Unix/Linux)
                process.start()
                
                logger.info(f"Background metadata checker process started (PID: {process.pid})")
                return "SCHEDULED"
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


class CVETrackerOperator:
    """Handles CVE tracker bug checking operations for both advisory and shipment data"""
    
    def __init__(self, cs: ConfigStore):
        self._am = AdvisoryManager(cs)
        self._sd = ShipmentData(cs)
        self._nm = NotificationManager(cs)
        self._cs = cs

    def check_cve_tracker_bugs(self) -> tuple[list, list]:
        """
        Check for missed CVE tracker bugs across both advisory and shipment sources
        
        Returns:
            tuple[list, list]: (list of missed CVE tracker bugs from advisories, 
                              list of missed CVE tracker bugs from shipments)
            
        Raises:
            Exception: If CVE tracker bug checking operations fail
        """
        try:
            advisory_cve_bugs = []
            shipment_cve_bugs = []
            
            # Check for missed CVE tracker bugs in advisories
            advisory_cve_bugs = self._am.check_cve_tracker_bug()
            
            # Check for missed CVE tracker bugs in shipments if konflux flow
            if self._sd._cs.is_konflux_flow():
                shipment_cve_bugs = self._sd.check_cve_tracker_bug()
            
            return advisory_cve_bugs, shipment_cve_bugs
        except Exception as e:
            logger.error(f"CVE tracker bug check failed: {str(e)}")
            raise

    def share_new_cve_tracker_bugs(self, cve_tracker_bugs: list) -> None:
        """
        Share notification about new CVE tracker bugs found
        
        Args:
            cve_tracker_bugs (list): Combined list of missed CVE tracker bugs from both advisories and shipments
            
        Raises:
            Exception: If notification fails
        """
        try:
            if cve_tracker_bugs:
                self._nm.share_new_cve_tracker_bugs(cve_tracker_bugs)
        except Exception as e:
            logger.error(f"Failed to share CVE tracker bug notification: {str(e)}")
            raise


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
                self._nm.share_shipment_mr_and_ad_info(
                    mr, updated_ads, abnormal_ads, updated_subtasks, new_owner
                )
            else:
                self._nm.share_ownership_change_result(
                    updated_ads, abnormal_ads, updated_subtasks, new_owner
                )
        except Exception as e:
            logger.error(f"Ownership change notification failed: {str(e)}")
            raise
