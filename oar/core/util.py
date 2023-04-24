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
    if version is None:
        raise ValueError("argument version is required")
    strs = version.split(".")
    if len(strs) > 2:
        return "%s.%s" % (strs[0], strs[1])
    else:
        raise ValueError(f"invalid release version {version}")
