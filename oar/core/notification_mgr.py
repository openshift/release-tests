import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from oar.core.config_store import ConfigStore
from oar.core.exceptions import NotificationException
from oar.core.worksheet_mgr import TestReport
from oar.core.notification_mgr import MailClient, SlackClient
import logging

logger = logging.getLogger(__name__)

class NotificationManager:
    """
    NotifiationManager will be used to notificate messages via email or slack.
    """
    def __init__(self, cs: ConfigStore):
        if cs:
            self._cs = cs
        else:
            raise NotificationException("argument config store is required") 

        self.mc = MailClient(self._cs.get_email_contact("trt"), self._cs.get_google_app_passwd())
        self.sc = SlackClient()  
        self.mh = MessageHelper(self._cs)   

    def share_new_report(self, report: TestReport):
        try:
            #Send email
            mail_subject = self._cs.release+' z-stream errata test status'
            mail_content = self.mh.get_mail_content(report.get_url())
            self.mc.send_email(self._cs.get_email_contact("qe"), mail_subject, mail_content)
        except Exception as nm: 
            raise NotificationException("send email failed") from nm
        
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
            raise NotificationException("cannot find google app password from env var GOOGLE_APP_PASSWD")  
          
        logger.info("login email with google app password")
        try:
            self.session = smtplib.SMTP_SSL('smtp.gmail.com:465')
            self.session.login(self.from_addr, self.google_app_passwd)
        except smtplib.SMTPAuthenticationError as sa:
            raise NotificationException("login gmail failed") from sa

    def send_email(self, to_addrs, subject, content):
        '''
        Send message to gmail
        '''
        try:
            message = MIMEMultipart()
            message['To'] = to_addrs
            message['Subject'] = subject
            message.attach(MIMEText(content, 'plain'))         
            text = message.as_string()
            #Send email
            err = self.session.sendmail(message['From'], message['To'].split(","), text)
            print(err)  
            self.session.quit()
        except smtplib.SMTPException as se:  # catch all the exceptions here
            raise NotificationException("send email failed") from se

class SlackClient:
    def __init__(self):
        logger.info("Add slack client part")
      
class MessageHelper:
    """
    Provide message needed info          
    """
    def __init__(self, cs: ConfigStore):
        self._cs = cs   
        self.version = self._cs.release 

    def get_mail_content(self,sheet_url):
        mail_content = 'Hello QE team,\n''The '+ self.version +' Z- stream release test status will be tracked in the following document:\n' +sheet_url
        return mail_content

