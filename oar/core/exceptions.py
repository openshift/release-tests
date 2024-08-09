class ConfigStoreException(BaseException):
    """Exception class to raise error in ConfigStore"""


class WorksheetException(BaseException):
    """Exception class to raise error in WorksheetManager"""


class WorksheetExistsException(WorksheetException):
    """Exception class to raise workhseet already exists error"""


class JiraException(BaseException):
    """Exception class to raise error in JiraManager"""


class JiraUnauthorizedException(JiraException):
    """Exception class to raise error in JiraManager when got 403 unauthorized"""


class AdvisoryException(BaseException):
    """Exception class to raise error in AdvisoryManager"""


class NotificationException(BaseException):
    """Exception class to raise error in notificationManager"""


class JenkinsHelperException(BaseException):
    """Exception class to raise error in JenkinsHelper"""
