import logging
from urllib.parse import urlparse
import warnings
import re
from semver.version import Version

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

def get_release_key(version):
    version_info = Version.parse(version)
    if version_info.prerelease:
        prerelease = version_info.prerelease
        if prerelease.startswith("ec") or prerelease.startswith("rc"):
            return prerelease
    return version

def init_logging(log_level=logging.INFO):
    logging.basicConfig(
        format="%(asctime)s: %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
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
