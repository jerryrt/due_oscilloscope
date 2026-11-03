"""The project's version, read from the one place it is typed (docs/versioning.md).

`lib/due_shared/src/fw_version.h` holds MAJOR, MINOR and PATCH; the Due firmware reports them in its identity and a release tag is `v` plus them.
Nothing here types a number: a copy in a second file is the disagreement that file was made to prevent. The H7 target's own constants are read
the same way so a release can check that every component says the same thing.
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_HEADER = os.path.join("lib", "due_shared", "src", "fw_version.h")
H7_SOURCE = os.path.join("targets", "h7tool", "fw", "ctl_h7.c")


def _triple(relpath, prefix, root=REPO):
    """'X.Y.Z' from `#define <prefix>_MAJOR/MINOR/PATCH <n>` in a file of the tree, or None when the file or a field is missing."""
    try:
        with open(os.path.join(root, relpath), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    got = [re.search(rf"^#define\s+{prefix}_{part}\s+(\d+)\s*$", text, re.M) for part in ("MAJOR", "MINOR", "PATCH")]
    return ".".join(m.group(1) for m in got) if all(got) else None


def project_version(root=REPO):
    return _triple(PROJECT_HEADER, "FW_VERSION", root)


def h7_version(root=REPO):
    return _triple(H7_SOURCE, "H7_FW", root)


SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def tag_for(version):
    return f"v{version}"
