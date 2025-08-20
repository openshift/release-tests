class ConfigStoreException(BaseException):
    """Exception class to raise error in ConfigStore"""


class WorksheetException(BaseException):
    """Exception class to raise error in WorksheetManager"""


class WorksheetExistsException(WorksheetException):
    """Exception class to raise worksheet already exists error"""


class JiraException(BaseException):
    """Exception class to raise error in JiraManager"""


class JiraUnauthorizedException(JiraException):
    """Exception class to raise error in JiraManager when got 403 unauthorized"""


class AdvisoryException(BaseException):
    """Exception class to raise error in AdvisoryManager"""


class NotificationException(BaseException):
    """Exception class to raise error in notificationManager"""


class JenkinsException(BaseException):
    """Exception class to raise error in JenkinsHelper"""


class GitLabMergeRequestException(BaseException):
    """Exception class to raise error in GitLabMergeRequest"""


class GitLabServerException(BaseException):
    """Exception class to raise error in GitLabServer"""


class ShipmentDataException(BaseException):
    """Exception class to raise error in ShipmentData"""

class GitException(BaseException):
    """Exception class to raise error in GitHelper"""
