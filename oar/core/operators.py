import logging
import schedule
import datetime
import time
import tempfile
import os
import subprocess
import sys
import oar.core.util as util

from typing import Union
from oar.core.advisory import AdvisoryManager, Advisory
from oar.core.configstore import ConfigStore
from oar.core.jira import JiraManager
from oar.core.notification import NotificationManager
from oar.core.shipment import ShipmentData
from oar.core.statebox import StateBox
from oar.core.worksheet import WorksheetManager
from oar.core.const import *
from oar.core.exceptions import ShipmentDataException, WorksheetException
from gspread.exceptions import WorksheetNotFound

logger = logging.getLogger(__name__)

class LogCaptureHandler(logging.Handler):
    """Custom logging handler to capture log messages for background processes"""
    
    def __init__(self):
        super().__init__()
        self.log_messages = []
        
    def emit(self, record):
        log_entry = self.format(record)
        self.log_messages.append(log_entry)
        
    def get_log_messages(self):
        """Get all captured log messages"""
        return self.log_messages

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
        self._cs = cs

        # Try to initialize ShipmentData gracefully
        # For already shipped Konflux releases, MR is merged and ShipmentData will raise exception
        self._sd = None
        self._sd_init_error = None
        if cs.is_konflux_flow():
            try:
                self._sd = ShipmentData(cs)
            except ShipmentDataException as e:
                # Store the error - "state is not open" means the MR is merged (shipped)
                self._sd_init_error = str(e)
                logger.info(f"ShipmentData initialization failed (MR likely merged): {str(e)}")
        
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

        # Initialize logging for subprocess FIRST (required for LogCaptureHandler to capture logs)
        util.init_logging(logging.DEBUG)

        # Add the capture handler to the logger
        capture_handler = LogCaptureHandler()
        capture_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        capture_handler.setLevel(logging.DEBUG)  # Capture all log levels
        logger.addHandler(capture_handler)
        
        # Initialize StateBox for task status updates
        statebox = StateBox(self._am._cs)

        # Get test report (Google Sheets) if available for backward compatibility
        report = None
        try:
            report = WorksheetManager(self._am._cs).get_test_report()
        except WorksheetException as e:
            # Check if root cause is specifically WorksheetNotFound (expected for StateBox releases)
            if isinstance(e.__cause__, WorksheetNotFound):
                logger.info(f"Google Sheets worksheet not found (expected for StateBox releases): {e}")
            else:
                # Other worksheet errors (API failures, network issues) should fail
                raise

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
                    
                    # Update test report status to PASS (Google Sheets - backward compatibility)
                    if report is not None:
                        try:
                            report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_PASS)
                            report.update_task_status(LABEL_TASK_NIGHTLY_BUILD_TEST, TASK_STATUS_PASS)
                            report.update_task_status(LABEL_TASK_SIGNED_BUILD_TEST, TASK_STATUS_PASS)
                            logger.info("Google Sheets test report status updated to PASS")
                        except Exception as e:
                            logger.error(f"Failed to update Google Sheets test report status: {str(e)}")

                    # Log success summary (will be captured by LogCaptureHandler)
                    logger.info("Release approval completed. Payload metadata URL is now accessible and advisories have been moved to REL_PREP.")

                    # Update StateBox
                    try:
                        statebox.update_task(
                            "change-advisory-status",
                            status=TASK_STATUS_PASS,
                            result="\n".join(capture_handler.get_log_messages())
                        )
                        logger.info("StateBox updated to PASS")
                    except Exception as e:
                        logger.error(f"Failed to update StateBox: {str(e)}")

                    # Send completion notification with full logs including summary
                    self._send_completion_notification(minor_release, success=True, log_messages=capture_handler.get_log_messages())
                else:
                    logger.warning(f"Timeout reached after {TIMEOUT_DAYS} days, payload metadata URL still not accessible")
                    
                    # Update test report status to FAIL for timeout (Google Sheets - backward compatibility)
                    if report is not None:
                        try:
                            report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
                            logger.info("Google Sheets test report status updated to FAIL due to timeout")
                        except Exception as e:
                            logger.error(f"Failed to update Google Sheets test report status: {str(e)}")

                    # Log timeout summary (will be captured by LogCaptureHandler)
                    logger.warning(f"Release approval timeout. Payload metadata URL still not accessible after {TIMEOUT_DAYS} days.")

                    # Update StateBox
                    try:
                        statebox.update_task(
                            "change-advisory-status",
                            status=TASK_STATUS_FAIL,
                            result="\n".join(capture_handler.get_log_messages())
                        )
                        logger.info("StateBox updated to FAIL")
                    except Exception as e:
                        logger.error(f"Failed to update StateBox: {str(e)}")

                    # Send timeout notification with full logs including summary
                    self._send_completion_notification(minor_release, success=False, log_messages=capture_handler.get_log_messages())
            finally:
                # Always release scheduler lock when done
                self._release_scheduler_lock(minor_release)
                # Clear all scheduled jobs
                schedule.clear()
                logger.info("All scheduled jobs cleared")
        except Exception as e:
            logger.error(f"Background metadata checker failed: {str(e)}")
            
            # Update test report status to FAIL for error (Google Sheets - backward compatibility)
            if report is not None:
                try:
                    report.update_task_status(LABEL_TASK_CHANGE_AD_STATUS, TASK_STATUS_FAIL)
                    logger.info("Google Sheets test report status updated to FAIL due to error")
                except Exception as update_error:
                    logger.error(f"Failed to update Google Sheets test report status: {str(update_error)}")

            # Log error summary (will be captured by LogCaptureHandler)
            logger.error(f"Release approval failed with error: {str(e)}")

            # Update StateBox
            try:
                statebox.update_task(
                    "change-advisory-status",
                    status=TASK_STATUS_FAIL,
                    result="\n".join(capture_handler.get_log_messages())
                )
                logger.info("StateBox updated to FAIL")
            except Exception as statebox_error:
                logger.error(f"Failed to update StateBox: {str(statebox_error)}")

            # Send error notification with full logs including summary
            self._send_completion_notification(minor_release, success=False, error=str(e), log_messages=capture_handler.get_log_messages())
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
        - Adds QE approval to shipment (if MR is still open)
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
            if self._cs.is_konflux_flow():
                # Add QE approval only if MR is still open
                if self._sd is not None:
                    self._sd.add_qe_approval()
                else:
                    logger.info("Shipment MR already merged, skipping QE approval step")

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
                
                # Launch background process for metadata checking using subprocess for true independence
                # Create a command to run the background checker as a separate process
                cmd = [
                    sys.executable, 
                    "-c", 
                    f"import sys; sys.path.insert(0, '{os.path.dirname(os.path.dirname(os.path.dirname(__file__)))}'); from oar.core.operators import ApprovalOperator; from oar.core.configstore import ConfigStore; cs = ConfigStore('{self._am._cs.release}'); op = ApprovalOperator(cs); op._background_metadata_checker('{minor_release}')"
                ]
                
                # Create environment with current environment - explicitly include OAR_SLACK_* variables
                # if they are available to ensure background process can send notifications to the correct thread
                env = os.environ.copy()
                
                # Explicitly pass Slack context environment variables if they exist
                # This ensures the background process can send notifications to the correct thread
                slack_channel = os.environ.get('OAR_SLACK_CHANNEL')
                slack_thread = os.environ.get('OAR_SLACK_THREAD')
                
                if slack_channel:
                    env['OAR_SLACK_CHANNEL'] = slack_channel
                if slack_thread:
                    env['OAR_SLACK_THREAD'] = slack_thread
                    
                logger.info(f"Environment for background process - OAR_SLACK_CHANNEL: {slack_channel}, OAR_SLACK_THREAD: {slack_thread}")
                
                # Start the process with start_new_session=True for true independence
                # This creates a completely detached process that won't become a zombie
                # Redirect stdout/stderr to log files for debugging
                log_dir = os.path.join(tempfile.gettempdir(), "oar_logs")
                os.makedirs(log_dir, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = os.path.join(log_dir, f"metadata_checker_{minor_release}_{timestamp}.log")

                with open(log_file, 'w') as f:
                    f.write(f"Background metadata checker process started at {datetime.datetime.now()}\n")
                    f.write(f"Command: {' '.join(cmd)}\n")
                    f.write(f"Release: {minor_release}\n")
                    f.write("-" * 80 + "\n")

                # Open log file for subprocess and close in parent immediately after fork
                # This prevents parent process shutdown from affecting the detached subprocess
                # See: OCPERT-209
                log_fd = os.open(log_file, os.O_WRONLY | os.O_APPEND)
                try:
                    process = subprocess.Popen(
                        cmd,
                        start_new_session=True,
                        env=env,
                        stdout=log_fd,
                        stderr=subprocess.STDOUT,  # Combine stderr with stdout
                        stdin=subprocess.DEVNULL,
                        close_fds=True  # Close all FDs in parent after fork
                    )
                finally:
                    # Close file descriptor in parent immediately
                    # Subprocess still has it open via inherited FD
                    os.close(log_fd)
                
                logger.info(f"Background metadata checker process started (PID: {process.pid}) - running independently after parent exit")
                logger.info(f"Process output redirected to: {log_file}")
                
                # The process is now completely detached and won't become a zombie
                # We don't need to wait for it or terminate it
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


class ReleaseShipmentOperator:
    """Handles checking if a release is fully shipped (Errata or Konflux flow)"""

    def __init__(self, cs: ConfigStore):
        self._cs = cs
        self._am = AdvisoryManager(cs)

        # Try to initialize ShipmentData
        # For already shipped Konflux releases, MR is merged and ShipmentData will raise exception
        self._sd = None
        self._sd_init_error = None
        try:
            self._sd = ShipmentData(cs)
        except ShipmentDataException as e:
            # Store the error - "state is not open" means the MR is merged (shipped)
            self._sd_init_error = str(e)
            logger.info(f"ShipmentData initialization failed: {str(e)}")

    def is_release_shipped(self) -> dict:
        """
        Check if a release is fully shipped.

        For Konflux flow:
        - Shipment MR must be either merged OR prod-release pipeline succeeded
        - rpm advisory must be in REL_PREP or higher state
        - rhcos advisory must be in REL_PREP or higher state

        For Errata flow:
        - All advisories (from ConfigStore) must be in REL_PREP or higher state

        Returns:
            dict: Status information with keys:
                - shipped (bool): Whether release is fully shipped
                - flow_type (str): "errata" or "konflux"
                - details (dict): Detailed status for each component
        """
        try:
            if self._cs.is_konflux_flow():
                return self._check_konflux_shipped()
            else:
                return self._check_errata_shipped()
        except Exception as e:
            logger.error(f"Failed to check release shipment status: {str(e)}")
            raise

    def _check_advisories_shipped(self, details: dict) -> bool:
        """Check if all advisories are shipped

        Gets all advisories from ConfigStore and checks if their state is REL_PREP or higher.
        For Konflux: returns rpm and rhcos advisories
        For Errata: returns all advisories (extras, image, metadata, rpm, rhcos)

        Args:
            details (dict): Dictionary to store advisory status details

        Returns:
            bool: True if all advisories are shipped, False otherwise
        """
        all_shipped = True

        try:
            advisories_map = self._cs.get_advisories()

            for impetus, errata_id in advisories_map.items():
                try:
                    ad = Advisory(errata_id=errata_id, impetus=impetus)
                    ad_state = ad.get_state()
                    details[f"{impetus}_advisory"] = ad_state

                    # Check if advisory is in REL_PREP or higher state
                    # REL_PREP or higher includes: REL_PREP, PUSH_READY, IN_PUSH, SHIPPED_LIVE
                    if ad_state not in [AD_STATUS_REL_PREP, AD_STATUS_PUSH_READY, AD_STATUS_IN_PUSH, AD_STATUS_SHIPPED_LIVE]:
                        all_shipped = False
                        logger.warning(f"Advisory {errata_id} ({impetus}) is in state {ad_state}, not ready for ship")
                except Exception as e:
                    logger.warning(f"Failed to check {impetus} advisory: {str(e)}")
                    details[f"{impetus}_advisory"] = f"error: {str(e)}"
                    all_shipped = False

        except Exception as e:
            logger.warning(f"Failed to get advisories from ConfigStore: {str(e)}")
            details["advisories_error"] = str(e)
            all_shipped = False

        return all_shipped

    def _check_konflux_shipped(self) -> dict:
        """Check shipment status for Konflux flow

        Checks if either:
        - prod-release pipeline succeeded, OR
        - shipment MR is in merged state
        Plus all advisories (rpm and rhcos) in REL_PREP or higher state
        """
        logger.info("Checking Konflux flow release shipment status")

        details = {}
        all_shipped = True

        # If ShipmentData initialization failed, check why
        if self._sd is None:
            if self._sd_init_error and "state is not open" in self._sd_init_error:
                # MR is not open = merged, which means shipped!
                details["shipment_mr_status"] = "merged"
                logger.info("ShipmentData not available - MR is merged (shipped)")
            else:
                # Some other error
                details["shipment_mr_status"] = f"error: {self._sd_init_error}"
                logger.warning(f"ShipmentData not available due to error: {self._sd_init_error}")
                all_shipped = False
        else:
            # ShipmentData available, check prod release success OR shipment MR merged status
            shipment_ready = False
            try:
                prod_success = self._sd.is_prod_release_success()
                details["prod_release"] = "success" if prod_success else "not yet"
                if prod_success:
                    shipment_ready = True
            except Exception as e:
                logger.warning(f"Failed to check prod release: {str(e)}")
                details["prod_release"] = f"error: {str(e)}"

            # Also check if MR is merged
            try:
                mr_merged = self._sd.is_mr_merged()
                details["shipment_mr_merged"] = "yes" if mr_merged else "no"
                if mr_merged:
                    shipment_ready = True
            except Exception as e:
                logger.warning(f"Failed to check MR merged status: {str(e)}")
                details["shipment_mr_merged"] = f"error: {str(e)}"

            if not shipment_ready:
                all_shipped = False

        # Check all advisories status
        advisories_shipped = self._check_advisories_shipped(details)
        if not advisories_shipped:
            all_shipped = False

        return {
            "shipped": all_shipped,
            "flow_type": "konflux",
            "details": details
        }

    def _check_errata_shipped(self) -> dict:
        """Check shipment status for Errata flow

        Checks if all advisories are in REL_PREP or higher state
        """
        logger.info("Checking Errata flow release shipment status")

        details = {}

        # Check all advisories status
        all_shipped = self._check_advisories_shipped(details)

        return {
            "shipped": all_shipped,
            "flow_type": "errata",
            "details": details
        }
