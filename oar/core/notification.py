import logging
import re
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import oar.core.util as util
from oar.core.configstore import ConfigStore
from oar.core.exceptions import NotificationException, JiraUnauthorizedException
from oar.core.jira import JiraManager
from oar.core.worksheet import TestReport
from oar.core.ldap import LdapHelper

logger = logging.getLogger(__name__)

class NotificationManager:
    """
    NotificationManager is used to send notification messages via email or slack.
    """

    def __init__(self, cs: ConfigStore):
        if cs:
            self.cs = cs
        else:
            raise NotificationException("argument config store is required")

        # self.mc = MailClient(
        #     self.cs.get_email_contact("trt"), self.cs.get_google_app_passwd()
        # )
        self.sc = SlackClient(self.cs.get_slack_bot_token())
        self.mh = MessageHelper(self.cs)

    def share_new_report(self, report: TestReport):
        """
        Send email and slack message for new report info

        Args:
            report (TestReport): newly created test report

        Raises:
            NotificationException: error when share this info
        """
        try:
            # Send email
            # mail_subject = self.cs.release + " z-stream errata test status"
            # mail_content = self.mh.get_mail_content_for_new_report(report)
            # self.mc.send_email(
            #     self.cs.get_email_contact("qe"), mail_subject, mail_content
            # )
            # Send slack message
            slack_msg = self.mh.get_slack_message_for_new_report(report)
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
            )
        except Exception as e:
            raise NotificationException("share new report failed") from e

    def share_new_statebox(self, statebox_url: str, release: str):
        """
        Send Slack message for newly created StateBox

        Args:
            statebox_url (str): GitHub URL to StateBox file
            release (str): Release version

        Raises:
            NotificationException: error when share this info
        """
        try:
            slack_msg = self.mh.get_slack_message_for_new_statebox(statebox_url, release)
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
            )
        except Exception as e:
            raise NotificationException("share new statebox failed") from e

    def share_ownership_change_result(
        self, updated_ads, abnormal_ads, updated_subtasks, new_owner
    ):
        """
        Send notification for take ownership result

        Args:
            updated_ads (list): updated advisory list
            abnormal_ads (list): advisory list that state is not QE
            updated_subtasks (list): updated jira subtasks
            new_owner (list): email address of the new owner

        Raises:
            NotificationException: error when share this info
        """

        try:
            # Send slack message only
            slack_msg = self.mh.get_slack_message_for_ownership_change(
                updated_ads, abnormal_ads, updated_subtasks, new_owner
            )
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
            )
            if len(abnormal_ads):
                slack_msg = self.mh.get_slack_message_for_abnormal_advisory(
                    abnormal_ads
                )
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact("art"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share ownership change result failed") from e

    def share_bugs_to_be_verified(self, jira_issues):
        """
        Send slack message to all QA Contacts, ask them to verify ON_QA bugs

        Args:
            jira_issues (list): jira issue list

        Raises:
            NotificationException: error when share this info
        """
        try:
            slack_msg = self.mh.get_slack_message_for_bug_verification(
                jira_issues)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-forum"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share bugs to be verified failed") from e

    def share_high_severity_bugs(self, jira_issues):
        """
        Send Slack message to all high severity issue QA Contacts, ask them to confirm dropping them from the release

        Args:
            jira_issues (list): high severity jira issue list

        Raises:
            NotificationException: error when share this info
        """
        try:
            slack_msg = self.mh.get_slack_message_for_high_severity_bugs(
                jira_issues)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-forum"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share high severity bugs failed") from e

    def share_new_cve_tracker_bugs(self, cve_tracker_bugs):
        """
        Send slack message to ART team with new CVE tracker bugs

        Args:
            cve_tracker_bugs (list): list of new CVE tracker bug

        Raises:
            NotificationException: error when checking new CVE tracker bugs
        """
        try:
            slack_msg = self.mh.get_slack_message_for_cve_tracker_bugs(
                cve_tracker_bugs)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact("art"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share missed CVE tracker bugs failed") from e

    def share_unhealthy_advisories(self, unhealthy_advisories):
        """
        Send slack message to ART team with unhealthy advisories

        Args:
            list: unhealthy_advisories

        Raises:
            NotificationException: error when sharing unhealthy advisories
        """
        try:
            slack_msg = self.mh.get_slack_message_for_unhealthy_advisories(
                unhealthy_advisories)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share unhealthy advisories failed") from e

    def share_dropped_bugs(self, dropped_bugs):
        """
        Send Slack message for dropped bugs notification

        Args:
            dropped_bugs (list[str]): list of dropped bug IDs

        Raises:
            NotificationException: error when sending dropped bugs notification
        """

        try:
            slack_msg = self.mh.get_slack_message_for_dropped_bugs(dropped_bugs)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-release"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share dropped bugs failed"
            ) from e
    
    
    def share_dropped_and_high_severity_bugs(self, dropped_bugs, high_severity_bugs):
        """
        Send Slack message to QE release lead with dropped and high severity bugs

        Args:
            dropped_bugs (list[str]): list of dropped bugs
            high_severity_bugs (list[str]): list of high severity bugs, could be [Critical/Blocker/Customer Case/CVE]

        Raises:
            NotificationException: error when sending message
        """
        try:
            slack_msg = self.mh.get_slack_message_for_dropped_and_high_severity_bugs(
                dropped_bugs, high_severity_bugs
            )
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-release"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share dropped and high severity bugs failed"
            ) from e

    def share_doc_prodsec_approval_result(self, doc_appr, prodsec_appr):
        """
        send notification for request doc or security approval
        """
        try:
            slack_msg = self.mh.get_slack_message_for_docs_and_prodsec_approval(
                doc_appr, prodsec_appr
            )
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "approver"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share doc and prodsec approval failed") from e

    def share_jenkins_build_url(self, job_name, build_url):
        """
        share notification for new jenkins build info
        """
        try:
            slack_msg = self.mh.get_slack_message_for_jenkins_build(
                job_name, build_url)
            if len(slack_msg):
                self.sc.post_message(self.cs.get_slack_channel_from_contact(
                    "qe-release"), slack_msg)
        except Exception as e:
            raise NotificationException(
                "share jenkins build url failed") from e

    def share_greenwave_cvp_failures(self, jira_key):
        """
        Share greenwave cvp failures

        Args:
            jira_key(str): jira to be shared
        """
        try:
            slack_msg = self.mh.get_slack_message_for_failed_cvp(jira_key)
            self.sc.post_message(self.cs.get_slack_channel_from_contact(
                "qe-release"), slack_msg)
        except Exception as e:
            raise NotificationException(
                "share greenwave cvp failures failed") from e

    def share_shipment_mr(self, mr, new_owner):
        """
        Share shipment merge requests info via Slack

        Args:
            mr (str): Shipment merge request URL
            new_owner (str): Email of new owner

        Raises:
            NotificationException: error when sharing shipment MR
        """
        try:
            slack_msg = self.mh.get_slack_message_for_shipment_mr(mr, new_owner)
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
            )
        except Exception as e:
            raise NotificationException("share shipment MR failed") from e

    def share_shipment_mr_and_ad_info(self, mr, updated_ads, abnormal_ads, updated_subtasks, new_owner):
        """
        Share shipment merge request and advisory info via Slack

        Args:
            mr (str): Shipment merge request URL
            updated_ads (list): Updated advisory list
            abnormal_ads (list): Advisory list that state is not QE
            updated_subtasks (list): Updated jira subtasks
            new_owner (str): Email of new owner

        Raises:
            NotificationException: error when sharing info
        """
        try:
            slack_msg = self.mh.get_slack_message_for_shipment_mr_and_ad_info(
                mr, updated_ads, abnormal_ads, updated_subtasks, new_owner
            )
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe-release"), slack_msg
            )
            if len(abnormal_ads):
                slack_msg = self.mh.get_slack_message_for_abnormal_advisory(
                    abnormal_ads
                )
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact("art"), slack_msg
                )
        except Exception as e:
            raise NotificationException("share shipment MR and AD info failed") from e
        
    def share_unverified_cve_issues_to_managers(self, unverified_cve_issues):
        """
        Share unverified CVE issues to managers of QA contacts

        Args:
            unverified_cve_issues (list[JiraIssue]): unverified cve jira issues list

        Raises:
            NotificationException: error when sharing unverified CVE issues failed
        """
        try:
            slack_msg = self.mh.get_slack_message_for_unverified_cve_issues_to_managers(
                unverified_cve_issues)
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-forum"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share unverified CVE issues to managers failed") from e

    def share_release_approval_completion(self, release: str, success: bool, error: str = None, log_messages: list = None):
        """
        Share release approval completion notification
        
        Always sends notification to default QE release channel. If Slack context is available 
        in environment variables, also sends full logs to specific thread.
        
        Args:
            release (str): The release version (e.g., "4.19.0")
            success (bool): Whether the approval was successful
            error (str): Error message if any
            log_messages (list): List of log messages to send (when Slack context available)
            
        Raises:
            NotificationException: error when sending notification
        """
        try:
            # Get Slack context from environment variables
            slack_channel = os.environ.get('OAR_SLACK_CHANNEL')
            slack_thread = os.environ.get('OAR_SLACK_THREAD')
            
            # Get release lead user group
            y_release = util.get_y_release(release)
            gid = self.sc.get_group_id_by_name(
                self.cs.get_slack_user_group_from_contact("qe-release", y_release)
            )
            
            # Create summary message for default channel
            if success:
                summary_message = f"Hello {gid}, Release approval completed for {release}. Payload metadata URL is now accessible and advisories have been moved to REL_PREP."
            elif error:
                summary_message = f"Hello {gid}, Release approval failed for {release}. Error: {error}"
            else:
                summary_message = f"Hello {gid}, Release approval timeout for {release}. Payload metadata URL still not accessible"
            
            # Always send to default channel
            default_channel = self.cs.get_slack_channel_from_contact("qe-release")
            self.sc.post_message(default_channel, summary_message)
            logger.info(f"Sent completion notification to default channel {default_channel}")
            
            # If Slack context is available, also send notification to specific thread
            if slack_channel and slack_thread:
                if log_messages:
                    # Send full log messages (which include the summary)
                    log_content = "\n".join(log_messages)
                    # Use utility function to split large messages
                    message_chunks = util.split_large_message(log_content)
                    for chunk in message_chunks:
                        self.sc.client.chat_postMessage(
                            channel=slack_channel,
                            thread_ts=slack_thread,
                            text=f"```{chunk}```"
                        )
                    
                    logger.info(f"Also sent full logs to thread {slack_thread} in channel {slack_channel}")
                else:
                    # Send summary message to thread when logs are not available
                    self.sc.client.chat_postMessage(
                        channel=slack_channel,
                        thread_ts=slack_thread,
                        text=summary_message
                    )
                    logger.info(f"Sent summary to thread {slack_thread} in channel {slack_channel} (no logs available)")
                
        except Exception as e:
            raise NotificationException("share release approval completion failed") from e

class MailClient:
    """
    Wrapper of email to send email easily
    """

    def __init__(self, from_addr, google_app_passwd):
        self.from_addr = from_addr
        if not self.from_addr:
            raise NotificationException("cannot find sender address")
        self.google_app_passwd = google_app_passwd
        if not self.google_app_passwd:
            raise NotificationException(
                "cannot find google app password from env var GOOGLE_APP_PASSWD"
            )

        try:
            self.session = smtplib.SMTP_SSL("smtp.gmail.com:465")
            self.session.login(self.from_addr, self.google_app_passwd)
        except smtplib.SMTPAuthenticationError as sa:
            raise NotificationException("login gmail failed") from sa

    def send_email(self, to_addrs, subject, content):
        """
        Send message to gmail
        """
        try:
            message = MIMEMultipart()
            message["Subject"] = subject
            message.attach(MIMEText(content, "plain"))
            # Send email
            senderrs = self.session.sendmail(
                self.from_addr, to_addrs.split(","), message.as_string()
            )
            if len(senderrs):
                logger.warning(
                    f"someone in the to_list is rejected: {senderrs}")
        except smtplib.SMTPException as se:  # catch all the exceptions here
            raise NotificationException("send email failed") from se
        finally:
            self.session.quit()

        logger.info(f"sent email to {to_addrs} with subject: <{subject}>")


class SlackClient:
    def __init__(self, bot_token):
        if not bot_token:
            raise NotificationException("slack bot token is not available")
        self.client = WebClient(token=bot_token)
        self.cache_dict = dict()

    def post_message(self, channel, msg):
        """
        Send slack message
        """
        try:
            self.client.chat_postMessage(channel=channel, text=msg)
        except SlackApiError as e:
            raise NotificationException("send slack message failed") from e

        logger.info(f"sent slack message to <{channel}>")

    def get_user_id_by_email(self, email):
        """
        Query slack user id by email address

        Args:
            email (str): valid email address

        Returns:
            str: slack user id
        """
        email = self.transform_email(email)
        userid = None
        if email in self.cache_dict:
            userid = self.cache_dict.get(email)
            logger.debug(f"Slack user id of {email} is retrieved from runtime cache")
        else:
            try:
                resp = self.client.api_call(
                    api_method="users.lookupByEmail", params={"email": email}
                )
                userid = resp["user"]["id"]
                self.cache_dict[email] = userid
                logger.debug(f"Slack user id of {email} is added to runtime cache")
            except SlackApiError as e:
                logger.warning(f"cannot get slack user id for <{email}>: {e}")
                return email

        return "<@%s>" % userid

    def get_group_id_by_name(self, name):
        """
        Query slack group id by group name

        Args:
            group_name (str): slack group name

        Returns:
            group id: slack group id
        """
        ret_id = ""
        if name in self.cache_dict:
            ret_id = self.cache_dict.get(name)
            logger.debug(f"Slack group id of {name} is retrieved from runtime cache")
        else:
            try:
                resp = self.client.api_call("usergroups.list")
                if resp.data:
                    for group in resp.data["usergroups"]:
                        gname = group["handle"]
                        gid = group["id"]
                        if gname == name:
                            ret_id = gid
                            self.cache_dict[name] = ret_id
                            logger.debug(f"Slack group id of {name} is added to runtime cache")
                            break
            except SlackApiError as e:
                raise NotificationException(
                    f"query group id by name {name} error") from e

        if not ret_id:
            raise NotificationException(
                f"cannot find slack group id by name {name}")

        return "<!subteam^%s>" % ret_id

    def transform_email(self, email):
        '''
        Email id in JIRA profile is not same as slack profile,
        e.g. in JIRA it's xxx+jira, in slack it's xxx
        '''
        at_index = email.find('@')
        before_at = email[:at_index]
        if re.search(r'\+\w+', before_at):
            cleaned_part = re.sub(r'\+\w+', '', before_at)
            return cleaned_part + email[at_index:]
        else:
            return email


class MessageHelper:
    """
    Provide message needed info
    """

    def __init__(self, cs: ConfigStore):
        self.cs = cs
        self.sc = SlackClient(self.cs.get_slack_bot_token())
        self.jm = JiraManager(cs)
        self.ldap = LdapHelper()

    def get_mail_content_for_new_report(self, report: TestReport):
        """
        manipulate mail text content for newly generated report

        Args:
            report (TestReport): new test report

        Returns:
            str: mail content
        """
        mail_content = (
            "Hello QE team,\n"
            "The "
            + self.cs.release
            + " z-stream release test status will be tracked in the following document:\n"
            + report.get_url()
        )
        return mail_content

    def get_slack_message_for_new_report(self, report: TestReport):
        """
        manipulate slack message for newly generated report

        Args:
            report (TestReport): new test report

        Returns:
            str: slack message for new test report
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )
        linked_text = self._to_link(report.get_url(), "test report")
        return f"Hello {gid}, new {linked_text} is generated for {self.cs.release}"

    def get_slack_message_for_new_statebox(self, statebox_url: str, release: str):
        """
        Generate Slack message for newly created StateBox

        Args:
            statebox_url (str): GitHub URL to StateBox file
            release (str): Release version

        Returns:
            str: Slack message for new StateBox
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(release)
            )
        )
        linked_text = self._to_link(statebox_url, "StateBox")
        return f"Hello {gid}, new {linked_text} is created for {release} release tracking"

    def get_slack_message_for_ownership_change(
        self, updated_ads, abnormal_ads, updated_subtasks, new_owner
    ):
        """
        manipulate slack message for ownership change

        Args:
            updated_ads (list): updated advisory list
            abnormal_ads (list): advisory list that state is not QE
            updated_subtasks (list): updated jira subtasks
            new_owner (list): email address of the new owner
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = f"Hello {gid}, owner of [{self.cs.release}] advisories and jira subtasks are changed to {new_owner}\n"
        message += "Updated advisories:\n"
        for ad in updated_ads:
            message += self._to_link(util.get_advisory_link(ad), ad) + " "
        message += "\n"
        message += "Updated jira subtasks:\n"
        for key in updated_subtasks:
            message += self._to_link(util.get_jira_link(key), key) + " "

        if len(abnormal_ads):
            message += "\n"
            message += "Found some abnormal advisories that state is not QE\n"
            for ad in abnormal_ads:
                message += self._to_link(util.get_advisory_link(ad), ad) + " "

        return message

    def get_slack_message_for_bug_verification(self, jira_issues):
        """
        manipulate slack message for bug verification

        Args:
            jira_issues (list): jira issue list

        Returns:
            str: Slack message
        """
        message = "Please pay attention to following ON_QA bugs, let's verify them ASAP, thanks for your cooperation"
        return self.__get_slack_message_for_jira_issues(jira_issues, message)
    
    def get_slack_message_for_unverified_cve_issues_to_managers(self, unverified_cve_issues):
        """
        Get Slack message for unverified CVE issues to managers of QA contacts

        Args:
            unverified_cve_issues (list[JiraIssue]): unverified cve jira issues list

        Returns:
            str: Slack message for unverified CVE issues to managers of QA contacts
        """

        message = "The following issues must be verified in this release. As the managers of the assigned QA contacts who have not yet verified these Jiras, could you please prioritize their verification or reassign them to other available QA contacts?"
        
        if len(unverified_cve_issues):
            slack_message = f"[{self.cs.release}] {message}\n"
            for issue in unverified_cve_issues:
                qa_contact_email = issue.get_qa_contact()
                manager_email = self.ldap.get_manager_email(qa_contact_email)
                key = issue.get_key()
                if manager_email:
                    user_id = self.sc.get_user_id_by_email(manager_email)
                else:
                    logger.warning(f"Manager email was not found for user {qa_contact_email}")
                    user_id = ""
                slack_message += (self._to_link(util.get_jira_link(key), key)
                                        + " "
                                        + user_id
                                        + "\n"
                                )
            return slack_message
        else:
            return ""

    def get_slack_message_for_high_severity_bugs(self, jira_issues):
        """
        Get Slack message for high severity bug verification

        Args:
            jira_issues (list): high severity jira issue list

        Returns:
            str: Slack message
        """
        message = "The following bugs should be verified in this release. Please confirm whether they can be dropped or if you will verify them soon. Note that CVE issues still require verification. Thank you for your cooperation"
        return self.__get_slack_message_for_jira_issues(jira_issues, message)

    def __get_slack_message_for_jira_issues(self, jira_issues, message):
        """
        Get Slack message for given jira issues and message

        Args:
            jira_issues (list): jira issue list
            message (str): message to be included alongside the jira list

        Returns:
            str: Slack message
        """
        has_onqa_issue = False
        slack_message = f"[{self.cs.release}] {message}\n"
        for key in jira_issues:
            try:
                issue = self.jm.get_issue(key)
            except JiraUnauthorizedException:
                logger.error(f"jira token does not have permission to access security bugs {key}, ignore and continue")
                continue

            if issue.is_on_qa():
                if issue.is_cve_tracker():
                    cve_warning = " This is a CVE bug and must be verified."
                else:
                    cve_warning = ""
                slack_message += (
                        self._to_link(util.get_jira_link(key), key)
                        + " "
                        + self.sc.get_user_id_by_email(issue.get_qa_contact())
                        + cve_warning + "\n"
                )
                has_onqa_issue = True
        return slack_message if has_onqa_issue else ""

    def get_slack_message_for_abnormal_advisory(self, abnormal_ads):
        """
        manipulate slack message for abnormal advisories, raise this issue with ART team

        Args:
            abnormal_ads (list): advisory list

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact_by_id("art")
        )

        message = f"Hello {gid}, Can you help to check following [{self.cs.release}] advisories, issue: state is NEW_FILES, thanks\n"
        for ad in abnormal_ads:
            message += self._to_link(util.get_advisory_link(ad), ad) + " "
        message += "\n"

        return message

    def get_slack_message_for_cve_tracker_bugs(self, cve_tracker_bugs):
        """
        manipulate slack message for new CVE tracker bugs

        Args:
            cve_tracker_bugs (list): list of new CVE tracker bugs

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact_by_id("art")
        )

        message = f"Hello {gid}, Found new CVE tracker bugs not attached on advisories, could you take a look, thanks\n"
        for bug in cve_tracker_bugs:
            message += self._to_link(util.get_jira_link(bug), bug) + " "
        message += "\n"

        return message

    def get_slack_message_for_unhealthy_advisories(self, unhealthy_advisories):
        """
        manipulate slack message for unhealthy advisories

        Args:
            list: unhealthy advisories

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = f"Hello {gid}, Found unhealthy advisories, please check if this is a known issue before ping artist in channel #forum-ocp-release, thanks\n"

        for ua in unhealthy_advisories:
            message += f"Advisory {util.get_advisory_link(ua['errata_id'])} has grade {ua['ad_grade']} with unhealthy builds:\n"
            for ub in ua["unhealthy_builds"]:
                message += f"{ub['nvr']} build for architecture {ub['arch']} has grade {ub['grade']}\n"

        return message

    
    def get_slack_message_for_dropped_bugs(self, dropped_bugs):
        """
        Generate a Slack notification message for bugs that have been dropped from advisories and shipment data.

        This method creates a formatted message that notifies the QE release lead and documentation team
        about bugs that have been removed from the current release. The message includes Jira links to
        each dropped bug for easy reference.

        Args:
            dropped_bugs (list[str]): List of Jira issue keys that have been dropped from the release

        Returns:
            str: Formatted Slack message with links to all dropped bugs, or empty string if no bugs were dropped

        Note:
            The message is only generated if there are dropped bugs to report. If the dropped_bugs list
            is empty, an empty string is returned.
        """

        release_lead_gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        docs_team_gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact("approver", "doc_id")
        )

        message = ""
        if len(dropped_bugs):
            message = f"[{self.cs.release}] Hello {release_lead_gid} {docs_team_gid}, following bugs are dropped from advisories and shipment data\n"
            for bug in dropped_bugs:
                message += self._to_link(util.get_jira_link(bug), bug) + "\n"
        
        return message

    
    def get_slack_message_for_dropped_and_high_severity_bugs(
        self, dropped_bugs, high_severity_bugs
    ):
        """
        Get Slack message for dropped bugs and high severity bugs

        Args:
            dropped_bugs (list[str]): list of dropped bugs
            high_severity_bugs (list[str]): list of high severity bugs

        Returns:
            str: Slack message
        """
        release_lead_gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        docs_team_gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact("approver", "doc_id")
        )

        message = ""
        if len(dropped_bugs):
            message = f"[{self.cs.release}] Hello {release_lead_gid} {docs_team_gid}, following bugs are dropped from advisories and shipment data\n"
            for bug in dropped_bugs:
                message += self._to_link(util.get_jira_link(bug), bug) + "\n"

        if len(high_severity_bugs):
            message += "\n" if len(message) else ""
            message += f"[{self.cs.release}] Hello {release_lead_gid}, following bugs are Critical/Blocker/Customer Case/CVE Tracker, if any of them can be dropped, do it manually. CVE can not be dropped. Thanks\n"
            for bug in high_severity_bugs:
                message += self._to_link(util.get_jira_link(bug), bug) + "\n"

        return message

    def get_slack_message_for_docs_and_prodsec_approval(self, doc_appr, prodsec_appr):
        """
        manipulate slack message for docs and prodsec approval

        Args:
            doc_appr (list): list of no doc approved advisories
            prodsec_appr (list): list of no product security approved advisories

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact("approver", "doc_id")
        )
        userid = []
        email_contact = self.cs.get_prodsec_id().split(",")
        if len(email_contact) > 1:
            for email in email_contact:
                userid.append(self.sc.get_user_id_by_email(email))
        else:
            userid = email_contact
        userid = " ".join(userid)
        message = ""
        if len(doc_appr):
            logger.info(f"send message for doc approval")
            message = f"[{self.cs.release}] Hello {gid}, Could you approve doc for advisories:{doc_appr}, thanks!"
        if len(prodsec_appr):
            logger.info(f"send message for Prodsec approval")
            message += f"\n[{self.cs.release}] Hello {userid}, Could you approve Prodsec for advisories:{prodsec_appr}, thanks!"
        return message

    def get_slack_message_for_jenkins_build(self, job_name, build_info):
        """
        manipulate slack message for jenkins build

        Args:
            job_name (str): jenkins job name
            build_url (str): jenkins build url

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = ""
        if build_info.startswith("http"):
            message += f"[{self.cs.release}] Hello {gid}, triggered jenkins build for job [{job_name}], url is {build_info}"
        else:
            message += f"[{self.cs.release}] Hello {gid}, {build_info}"

        return message

    def get_slack_message_for_failed_cvp(self, jira_key):
        """
        Get Slack message for failed Greenwave CVP tests

        Args:
         jira_key(str): jira to be added as part of the message

        Returns: Slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )
        message = f"[{self.cs.release}] Hello {gid}, there are Greenwave CVP failures in advisories. Please contact CVP team. Use the following jira for reference: {util.get_jira_link(jira_key)}."

        return message

    def get_slack_message_for_shipment_mr(self, mr, new_owner):
        """
        Get Slack message for shipment merge request

        Args:
            mr (str): Shipment merge request URL
            new_owner (str): Email of new owner

        Returns:
            str: Slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = f"[{self.cs.release}] Hello {gid}, QE release lead has been transferred to {new_owner}\n"
        message += "Shipment merge requests:\n"
        message += self._to_link(mr, mr) + "\n"

        return message

    def get_slack_message_for_shipment_mr_and_ad_info(
        self, mr, updated_ads, abnormal_ads, updated_subtasks, new_owner
    ):
        """
        Get Slack message combining shipment merge requests and advisory info

        Args:
            mr (str): Shipment merge request URL
            updated_ads (list): Updated advisory list
            abnormal_ads (list): Advisory list that state is not QE
            updated_subtasks (list): Updated jira subtasks
            new_owner (str): Email of new owner

        Returns:
            str: Slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = f"[{self.cs.release}] Hello {gid}, owner of advisories and jira subtasks are changed to {new_owner}\n"
        
        if mr:
            message += f"Shipment merge request: {self._to_link(mr, mr)}\n"

        message += "Updated advisories:\n"
        for ad in updated_ads:
            message += self._to_link(util.get_advisory_link(ad), ad) + " "
        message += "\n"
        
        if updated_subtasks:
            message += "Updated jira subtasks:\n"
            for key in updated_subtasks:
                message += self._to_link(util.get_jira_link(key), key) + " "

        if len(abnormal_ads):
            message += "\n"
            message += "Found some abnormal advisories that state is not QE\n"
            for ad in abnormal_ads:
                message += self._to_link(util.get_advisory_link(ad), ad) + " "

        return message

    def _to_link(self, link, text):
        """
        private func to generate linked text

        Args:
            link (str): link url
            text (str): text

        Returns:
            linked_text: slack linked text
        """
        return f"<{link}|{text}>"
