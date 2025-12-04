import logging
import requests
import warnings
import re
import subprocess
import json
from datetime import datetime, timezone
from semver.version import Version
from urllib.parse import urlparse
from subprocess import CalledProcessError
from requests.exceptions import RequestException

from oar.core.const import LOG_FORMAT, LOG_DATE_FORMAT, TASK_DISPLAY_NAMES

logger = logging.getLogger(__name__)

def is_valid_z_release(version):
    strs = version.split(".")
    if len(strs) != 3:
        return False

    valid = True
    for v in strs:
        if not v.isdigit():
            valid = False
            break

    return valid

def get_y_release(version):
    strs = version.split(".")
    if len(strs) > 2:
        return "%s.%s" % (strs[0], strs[1])

    return None

def validate_release_version(version):
    try:
        Version.parse(version)
        return True
    except ValueError:
        return False

def get_current_timestamp() -> str:
    """
    Get current UTC timestamp in standardized LOG_DATE_FORMAT.

    Returns timestamps in format: YYYY-MM-DDTHH:MM:SSZ
    This ensures consistency across all OAR components (logs, StateBox, etc.)

    Returns:
        Timestamp string in LOG_DATE_FORMAT (e.g., "2025-11-28T06:19:44Z")
    """
    return datetime.now(timezone.utc).strftime(LOG_DATE_FORMAT)

def log_task_status(task: str, status: str):
    """
    Log task status change in format expected by cli_result_callback.

    The cli_result_callback parses the last line of command output looking for
    status markers ([Pass], [Fail], [In Progress]) to automatically update StateBox.

    Args:
        task: Task constant (e.g., TASK_CHECK_CVE_TRACKER_BUG from const.py)
        status: Task status - must be one of: "Pass", "Fail", "In Progress"

    Example:
        >>> from oar.core.const import TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_PASS
        >>> log_task_status(TASK_CHECK_CVE_TRACKER_BUG, TASK_STATUS_PASS)
        # Logs: "task [Check CVE Tracker Bug] status is changed to [Pass]"
    """
    display_name = TASK_DISPLAY_NAMES.get(task, task)  # Fallback to task itself if not in mapping
    logger.info(f"task [{display_name}] status is changed to [{status}]")

def get_release_key(version):
    version_info = Version.parse(version)
    if version_info.prerelease:
        prerelease = version_info.prerelease
        if prerelease.startswith("ec") or prerelease.startswith("rc"):
            return prerelease
    return version

def init_logging(log_level=logging.INFO):
    logging.basicConfig(
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=log_level,
    )

    # Suppress specific SSL patching warning
    warnings.filterwarnings(
        "ignore",
        message="Failed to patch SSL settings for unverified requests",
        category=UserWarning,
        module="pip_system_certs.wrapt_requests"
    )

    loggers = logging.Logger.manager.loggerDict
    for k in loggers.keys():
        if "requests" in k or "urllib3" in k or "gssapi" in k:
            logger = logging.getLogger(k)
            logger.setLevel(logging.WARNING)
        if "requests_kerberos" in k:
            logger = logging.getLogger(k)
            logger.setLevel(logging.CRITICAL)

def get_jira_link(key):
    return "%s/browse/%s" % ("https://issues.redhat.com", key)


def get_advisory_link(advisory):
    return f"{get_advisory_domain_url()}/advisory/{advisory}"

def get_advisory_domain_url():
    return "https://errata.devel.redhat.com"

def is_grade_healthy(grade):
    return grade in ("A", "B")

def is_valid_email(email):
    """Validate email format using regex pattern.
    Args:
        email (str): Email address to validate
    Returns:
        bool: True if email is valid, False otherwise
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))

def parse_mr_url(url: str) -> tuple:
    """Parse MR URL to extract project and MR ID
    
    Args:
        url: MR URL in format https://gitlab.cee.redhat.com/namespace/project/-/merge_requests/123
        
    Returns:
        tuple: (project_path, mr_id)
        
    Raises:
        ValueError: If URL is invalid
    """
    parsed = urlparse(url)
    if not parsed.netloc or not parsed.path:
        raise ValueError("Invalid MR URL")
        
    # Extract project path (namespace/project)
    path_parts = parsed.path.split('/-/merge_requests/')
    if len(path_parts) != 2:
        raise ValueError("Invalid MR URL format")
        
    project_path = path_parts[0].strip('/')
    mr_id = int(path_parts[1].split('/')[0])
    
    return (project_path, mr_id)

def get_ocp_test_result_url(release: str) -> str:
    """
    Return OCP test result url for specified release

    Args:
        release (str): Release or candidate nighly version

    Returns:
        str: OCP test result release url
    """
    return f"https://github.com/openshift/release-tests/blob/record/_releases/ocp-test-result-{release}-amd64.json"

def get_qe_sippy_main_view_url(release: str) -> str:
    """
    Return QE Sippy main view url for specified release

    Args:
        release (str): Release version

    Returns:
        str: QE Sippy main view release url
    """
    return f"{get_qe_sippy_url()}/main?view={get_y_release(release)}-qe-main"

def get_qe_sippy_auto_release_view_url(release: str) -> str:
    """
    Return QE Sippy auto release view url for specified release

    Args:
        release (str): Release version

    Returns:
        str: QE Sippy auto release view release url
    """
    return f"{get_qe_sippy_url()}/main?view={get_y_release(release)}-qe-auto-release"

def get_qe_sippy_url() -> str:
    """
    Return QE Sippy url

    Returns:
        str: QE Sippy url
    """
    return "https://qe-component-readiness.dptools.openshift.org/sippy-ng/component_readiness"

def split_large_message(message: str, max_size: int = 4000, chunk_size: int = 2500) -> list:
    """
    Split a large message into smaller chunks for platforms with message size limits.
    
    This is useful for Slack messages which have a 4000 character limit per message.
    
    Args:
        message: The message content to split
        max_size: Maximum allowed message size (default: 4000 for Slack)
        chunk_size: Size of each chunk (default: 2500 to allow for code formatting)
        
    Returns:
        list: List of message chunks
    """
    if len(message) <= max_size:
        return [message]
    
    chunks = []
    for i in range(0, len(message), chunk_size):
        chunk = message[i:i + chunk_size]
        chunks.append(chunk)
    
    return chunks

def is_payload_metadata_url_accessible(release: str) -> bool:
    """Check if the metadata URL for a given OCP release payload is accessible.
    
    This function verifies accessibility by:
    1. Getting the image pullspec from release stream API
    2. Checking if oc client is available
    3. Extracting metadata URL from release payload
    4. Verifying the metadata URL returns HTTP 200
    
    Args:
        release: The OCP Y-stream release version to check (e.g. "4.19")
        
    Returns:
        bool: True if metadata URL is accessible, False otherwise
        
    Raises:
        requests.exceptions.RequestException: If any HTTP request fails
        subprocess.CalledProcessError: If oc command execution fails
    """
    # get image pullspec from release stream 4-stable
    pullspec = None
    url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/latest?prefix={release}"
    resp = requests.get(url)
    if resp.ok:
        pullspec = resp.json()['pullSpec']
    else:
        logger.error(f"Can not get payload pullspec from release stream 4-stable, http error {resp.status_code}")
        return False
    
    # get metadata url from release payload
    # this logic replies on oc client, so need to check oc installation first.
    try:
        cmd = ['oc', 'version', '--client']
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (CalledProcessError, FileNotFoundError):
        logger.error("Cannot find oc client from localhost, please make sure it is installed")
        return False
    
    metadata_url = None
    try:
        cmd = ['oc', 'adm', 'release', 'info', pullspec, '-o', 'json']
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        metadata_url = json.loads(result.stdout).get('metadata').get('metadata').get('url')
    except CalledProcessError as cpe:
        logger.error(f"Execute oc command failed: {str(cpe)}")
        return False
    
    # check if the metadata url is accessible, expected is 200 ok
    logger.info(f"Checking accessiblity of metadata url {metadata_url}")
    try:
        accessible = requests.get(metadata_url, timeout=10).ok
        logger.info(f"The metadata url is {'accessible' if accessible else 'not accessible'}")
        return accessible
    except RequestException as e:
        logger.error(f"Failed to check metadata URL accessibility: {str(e)}")
        return False
