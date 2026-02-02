class ConfigStoreException(Exception):
    """Exception class to raise error in ConfigStore"""


class WorksheetException(Exception):
    """Exception class to raise error in WorksheetManager"""


class WorksheetExistsException(WorksheetException):
    """Exception class to raise worksheet already exists error"""


class WorksheetNotFound(WorksheetException):
    """Exception class to raise worksheet not found error (expected for StateBox releases)"""


class JiraException(Exception):
    """Exception class to raise error in JiraManager"""


class JiraUnauthorizedException(JiraException):
    """Exception class to raise error in JiraManager when got 403 unauthorized"""


class AdvisoryException(Exception):
    """Exception class to raise error in AdvisoryManager"""


class NotificationException(Exception):
    """Exception class to raise error in notificationManager"""


class JenkinsHelperException(Exception):
    """Exception class to raise error in JenkinsHelper"""


class GitLabMergeRequestException(Exception):
    """Exception class to raise error in GitLabMergeRequest"""


class GitLabServerException(Exception):
    """Exception class to raise error in GitLabServer"""


class ShipmentDataException(Exception):
    """Exception class to raise error in ShipmentData"""

class GitException(Exception):
    """Exception class to raise error in GitHelper"""


class StateBoxException(Exception):
    """Exception class to raise error in StateBox"""
