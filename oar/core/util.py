import logging
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
