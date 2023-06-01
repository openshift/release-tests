import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from oar.core.config_store import ConfigStore
from oar.core.exceptions import NotificationException
from oar.core.worksheet_mgr import TestReport
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    NotifiationManager will be used to notificate messages via email or slack.
    """

    def __init__(self, cs: ConfigStore):
        if cs:
            self.cs = cs
        else:
            raise NotificationException("argument config store is required")

        self.mc = MailClient(
            self.cs.get_email_contact("trt"), self.cs.get_google_app_passwd()
        )
        self.sc = SlackClient(self.cs.get_slack_bot_token())
        self.mh = MessageHelper(self.cs)

    def share_new_report(self, report: TestReport):
        try:
            # Send email
            mail_subject = self.cs.release + " z-stream errata test status"
            mail_content = self.mh.get_mail_content_for_new_report(report)
            self.mc.send_email(
                self.cs.get_email_contact("qe"), mail_subject, mail_content
            )
            # Send slack message
            slack_msg = self.mh.get_slack_message_for_new_report(report)
            self.sc.post_message(
                self.cs.get_slack_channel_from_contact("qe"), slack_msg
            )
        except Exception as e:
            raise NotificationException("share new report failed") from e


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

        logger.info("login email with google app password")
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
            message["To"] = to_addrs
            message["Subject"] = subject
            message.attach(MIMEText(content, "plain"))
            text = message.as_string()
            # Send email
            senderrs = self.session.sendmail(
                message["From"], message["To"].split(","), text
            )
            if len(senderrs):
                logger.warn(f"someone in the to_list is rejected: {senderrs}")
        except smtplib.SMTPException as se:  # catch all the exceptions here
            raise NotificationException("send email failed") from se
        finally:
            self.session.quit()


class SlackClient:
    def __init__(self, bot_token):
        if not bot_token:
            raise NotificationException("slack bot token is not available")
        self.client = WebClient(token=bot_token)

    def post_message(self, channel, msg):
        """
        Send slack message
        """
        try:
            self.client.chat_postMessage(channel=channel, text=msg)
        except SlackApiError as e:
            raise NotificationException("send slack message failed") from e

    def get_user_id_by_email(self, email):
        """
        Query slack user id by email address

        Args:
            email (str): valid email address

        Returns:
            str: slack user id
        """
        try:
            resp = self.client.api_call(
                api_method="users.lookupByEmail", params={"email": email}
            )
            userid = resp["user"]["id"]
        except SlackApiError as e:
            raise NotificationException(
                f"query user id by email <{email}> error"
            ) from e

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
        try:
            resp = self.client.api_call("usergroups.list")
            if resp.data:
                for group in resp.data["usergroups"]:
                    gname = group["handle"]
                    gid = group["id"]
                    if gname == name:
                        ret_id = gid
                        break
        except SlackApiError as e:
            raise NotificationException(f"query group id by name {name} error") from e

        if not ret_id:
            raise NotificationException(f"cannot find slack group id by name {name}")

        return "<!subteam^%s>" % ret_id


class MessageHelper:
    """
    Provide message needed info
    """

    def __init__(self, cs: ConfigStore):
        self.cs = cs
        self.sc = SlackClient(self.cs.get_slack_bot_token())

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
            self.cs.get_slack_user_group_from_contact("qe")
        )
        linked_text = self._to_link(report.get_url(), "test report")
        return f"Hello {gid}, new {linked_text} is generated for {self.cs.release}"

    def _to_link(self, link, text):
        """
        private func to generate linked text

        Args:
            link (str): link url
            text (str): text

        Returns:
            str: slack linked text
        """
        return f"<{link}|{text}>"
