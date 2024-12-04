import logging


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


def init_logging(log_level=logging.INFO):
    logging.basicConfig(
        # format="%(module)s: %(asctime)s: %(levelname)s: %(message)s",
        format="%(asctime)s: %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        level=log_level,
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
    return "https://errata.devel.redhat.com/advisory/%s" % advisory

def is_grade_healthy(grade):
    return grade in ("A", "B")
