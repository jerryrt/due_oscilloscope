#!/usr/bin/env python3
"""Release checks and checksums (docs/versioning.md).

    release.py check vX.Y.Z     refuse unless the tag is a semantic version, every component says it, the tag is free, and the tree is clean
    release.py sums DIR         write DIR/SHA256SUMS over the images and build-env.json found under DIR

`check` prints one line per condition and exits 1 if any fails. It reads the version from the tree and never types one.
"""
import argparse
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import version                                                  # noqa: E402


def conditions(tag, root=ROOT, git=None):
    """[(ok, text)] for releasing `tag`. `git(*args)` returns stdout or raises; injected so a test needs no repository."""
    git = git or (lambda *a: subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True).stdout)
    out = []
    want = tag[1:] if tag.startswith("v") else None
    out.append((bool(want and version.SEMVER.match(want)), f"{tag!r} is vX.Y.Z"))
    for name, got in (("Due firmware (fw_version.h)", version.project_version(root)), ("H7 firmware (ctl_h7.c)", version.h7_version(root))):
        out.append((got is not None and got == want, f"{name} says {got}, the tag says {want}"))
    try:
        existing = git("tag", "--list", tag).strip()
        out.append((not existing, "the tag is free" if not existing else f"{tag} already exists"))
        dirty = git("status", "--porcelain").strip()
        out.append((not dirty, "the tree is clean" if not dirty else "the tree has uncommitted changes"))
    except (OSError, subprocess.CalledProcessError) as e:
        out.append((False, f"git could not answer: {e}"))
    return out


def sums(directory):
    """Write SHA256SUMS in `directory` over every .bin and build-env.json beneath it; returns the lines. Raises if there is nothing to sum."""
    rows = []
    for base, _dirs, files in sorted(os.walk(directory)):
        for f in sorted(files):
            if f.endswith(".bin") or f == "build-env.json":
                p = os.path.join(base, f)
                with open(p, "rb") as fh:
                    rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {os.path.relpath(p, directory)}")
    if not rows:
        raise SystemExit(f"nothing to sum under {directory}: no .bin or build-env.json")
    with open(os.path.join(directory, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("tag")
    sub.add_parser("sums").add_argument("directory")
    a = ap.parse_args(argv)
    if a.cmd == "sums":
        print("\n".join(sums(a.directory)))
        return 0
    res = conditions(a.tag)
    for ok, text in res:
        print(("ok   " if ok else "FAIL ") + text)
    return 0 if all(ok for ok, _ in res) else 1


if __name__ == "__main__":
    sys.exit(main())
