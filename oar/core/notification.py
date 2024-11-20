import os
import re
import smtplib
import logging
import oar.core.util as util
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from oar.core.configstore import ConfigStore
from oar.core.exceptions import NotificationException
from oar.core.worksheet import TestReport
from oar.core.jira import JiraManager
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


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

    def share_ownership_change_result(
        self, updated_ads, abnormal_ads, updated_subtasks, new_owner
    ):
        """
        Send notification for take ownership result

        Args:
            updated_ads ([]): updated advisory list
            abnormal_ads ([]): advisory list that state is not QE
            updated_subtasks ([]): updated jira subtasks
            new_owner ([]): email address of the new owner

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
            jira_issues ([]): jira issue list

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

    def share_new_cve_tracker_bugs(self, cve_tracker_bugs):
        """
        Send slack message to ART team with new CVE tracker bugs

        Args:
            cve_tracker_bugs ([]): list of new CVE tracker bug

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

    def share_dropped_and_must_verify_bugs(self, dropped_bugs, must_verify_bugs):
        """
        Send slack message to QE release lead with dropped and must verified bugs

        Args:
            dropped_bugs ([]): list of dropped bugs
            must_verified_bugs ([]): list of must verify bugs, could be [Critical/Blocker/Customer Case]

        Raises:
            NotificationException: error when sending message
        """
        try:
            slack_msg = self.mh.get_slack_message_for_dropped_and_must_verify_bugs(
                dropped_bugs, must_verify_bugs
            )
            if len(slack_msg):
                self.sc.post_message(
                    self.cs.get_slack_channel_from_contact(
                        "qe-release"), slack_msg
                )
        except Exception as e:
            raise NotificationException(
                "share dropped and must verified bugs failed"
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

    def get_slack_message_for_ownership_change(
        self, updated_ads, abnormal_ads, updated_subtasks, new_owner
    ):
        """
        manipulate slack message for ownership change

        Args:
            updated_ads ([]): updated advisory list
            abnormal_ads ([]): advisory list that state is not QE
            updated_subtasks ([]): updated jira subtasks
            new_owner ([]): email address of the new owner
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
            jira_issues ([]): jira issue list

        Returns:
            str: slack message
        """
        has_onqa_issue = False
        message = f"[{self.cs.release}] Please pay attention to following ON_QA bugs, let's verify them ASAP, thanks for the cooperation\n"
        for key in jira_issues:
            issue = self.jm.get_issue(key)
            if issue.is_on_qa():
                message += (
                    self._to_link(util.get_jira_link(key), key)
                    + " "
                    + self.sc.get_user_id_by_email(issue.get_qa_contact())
                    + "\n"
                )
                has_onqa_issue = True

        return message if has_onqa_issue else ""

    def get_slack_message_for_abnormal_advisory(self, abnormal_ads):
        """
        manipulate slack message for abnormal advisories, raise this issue with ART team

        Args:
            abnormal_ads ([]): advisory list

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
            cve_tracker_bugs ([]): list of new CVE tracker bugs

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

    def get_slack_message_for_dropped_and_must_verify_bugs(
        self, dropped_bugs, must_verify_bugs
    ):
        """
        manipulate slack message for dropped bugs and must verify bugs

        Args:
            dropped_bugs ([]): list of dropped bugs
            must_verify_bugs ([]): list of must verify bugs

        Returns:
            str: slack message
        """
        gid = self.sc.get_group_id_by_name(
            self.cs.get_slack_user_group_from_contact(
                "qe-release", util.get_y_release(self.cs.release)
            )
        )

        message = ""
        if len(dropped_bugs):
            message = f"[{self.cs.release}] Hello {gid}, following bugs are dropped from advisories\n"
            for bug in dropped_bugs:
                message += self._to_link(util.get_jira_link(bug), bug) + "\n"

        if len(must_verify_bugs):
            message += "\n" if len(message) else ""
            message += f"[{self.cs.release}] Hello {gid}, following bugs are Critical/CVE Tracker/Customer Case, must be verified, if any of them can be dropped, do it manually, thanks\n"
            for bug in must_verify_bugs:
                message += self._to_link(util.get_jira_link(bug), bug) + "\n"

        return message

    def get_slack_message_for_docs_and_prodsec_approval(self, doc_appr, prodsec_appr):
        """
        manipulate slack message for docs and prodsec approval

        Args:
            doc_appr ([]): list of no doc approved advisories
            prodsec_appr ([]): list of no product security approved advisories

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
