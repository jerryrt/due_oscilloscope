#!/usr/bin/env python3
"""Fetch and verify the vendor SPICE models and datasheets the AFE uses.

Vendor files may not be redistributed (MC-6), so they are never committed.
This script puts them in hardware/afe-proto/models/ from the vendor's own
URL and pins every file by sha256. The list lives in models/manifest.json,
which is committed; the files it names are ignored by git.

    python3 -I hardware/afe-proto/tools/fetch_models.py           # fetch missing
    python3 -I hardware/afe-proto/tools/fetch_models.py --check   # verify only

Exit status: 0 every file verified, 1 a file missing or a hash mismatch,
2 a manifest, network or archive error.

A downloaded file is untrusted. It is written to a new temporary directory,
an archive is checked member by member (no absolute path, no '..', no
symlink) before anything is taken out of it, the one member wanted is
extracted into a new empty directory, and a file reaches models/ only after
its sha256 matches. A present file that fails its hash is reported and left
alone unless --replace is given, and even then it is replaced only by a
file that verified.

Stdlib only; run with `python3 -I` so nothing beside a download can be
imported.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS = HERE.parent / "models"
MAX_DOWNLOAD = 64 * 1024 * 1024  # bytes; the largest file listed is ~3.3 MB
USER_AGENT = "afe-model-fetch/1"  # generic, identifies no user
HEX = set("0123456789abcdef")


class FetchError(Exception):
    """A manifest, network or archive problem: exit 2."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def safe_relpath(name, what):
    """Return a PurePosixPath for a relative name with no '..', or raise."""
    if not name or "\\" in name or "\0" in name:
        raise FetchError(f"{what}: unsafe name {name!r}")
    p = PurePosixPath(name)
    if p.is_absolute() or name.startswith("/") or ".." in p.parts \
            or (len(p.parts[0]) >= 2 and p.parts[0][1] == ":"):
        raise FetchError(f"{what}: unsafe name {name!r}")
    return p


def check_hash_field(value, what):
    if not isinstance(value, str) or len(value) != 64 or set(value) - HEX:
        raise FetchError(f"{what}: sha256 is not 64 lower-case hex digits")


def load_manifest(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FetchError(f"manifest {path}: {e}")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise FetchError(f"manifest {path}: no 'files' list")
    seen = set()
    for i, e in enumerate(files):
        what = f"manifest entry {i}"
        for key in ("path", "sha256", "size"):
            if key not in e:
                raise FetchError(f"{what}: missing '{key}'")
        safe_relpath(e["path"], what)
        if e["path"] in seen:
            raise FetchError(f"{what}: duplicate path {e['path']}")
        seen.add(e["path"])
        check_hash_field(e["sha256"], f"{what} ({e['path']})")
        url = e.get("url")
        if url is not None and not url.startswith("https://"):
            raise FetchError(f"{what} ({e['path']}): url must be https or null")
        if "member" in e:
            safe_relpath(e["member"], f"{what} member")
            check_hash_field(e.get("archive_sha256"),
                             f"{what} ({e['path']}) archive_sha256")
    return files


def verify_present(models, files):
    """Return (ok, missing, bad) lists of manifest entries."""
    ok, missing, bad = [], [], []
    for e in files:
        p = models / e["path"]
        if not p.is_file() or p.is_symlink():
            missing.append(e)
            continue
        got = sha256_file(p)
        if got == e["sha256"]:
            ok.append(e)
        else:
            bad.append((e, got))
    return ok, missing, bad


def download(url, dest_dir):
    """Download url into a fresh file in dest_dir; return its path."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    out = Path(dest_dir) / "download"
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if not r.geturl().startswith("https://"):
                raise FetchError(f"{url}: redirected off https to {r.geturl()}")
            total = 0
            with open(out, "xb") as f:
                while True:
                    block = r.read(1 << 16)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_DOWNLOAD:
                        raise FetchError(f"{url}: larger than {MAX_DOWNLOAD} bytes")
                    f.write(block)
    except OSError as e:
        raise FetchError(f"{url}: {e}")
    return out


def check_archive(zf, origin):
    """Refuse the whole archive if any member name or type is unsafe."""
    for info in zf.infolist():
        safe_relpath(info.filename.rstrip("/") or info.filename,
                     f"{origin} member")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise FetchError(f"{origin}: member {info.filename!r} is a symlink")


def extract_member(archive, member, size, origin):
    """Extract one member into a new empty directory; return its path."""
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as e:
        raise FetchError(f"{origin}: not a zip archive ({e})")
    with zf:
        check_archive(zf, origin)
        try:
            info = zf.getinfo(member)
        except KeyError:
            raise FetchError(f"{origin}: no member {member!r}")
        if info.file_size != size:
            raise FetchError(f"{origin}: member {member!r} is {info.file_size}"
                             f" bytes, manifest says {size}")
        outdir = Path(tempfile.mkdtemp(prefix="member-",
                                       dir=Path(archive).parent))
        out = outdir / PurePosixPath(member).name
        with zf.open(info) as src, open(out, "xb") as dst:
            remaining = size + 1  # read one past to catch a lying header
            while remaining > 0:
                block = src.read(min(1 << 16, remaining))
                if not block:
                    break
                remaining -= len(block)
                dst.write(block)
        if out.stat().st_size != size:
            raise FetchError(f"{origin}: member {member!r} size mismatch")
    return out


def install(src, dest):
    """Copy a verified file next to dest, then rename it over dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + dest.name + ".", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as f, open(src, "rb") as s:
            shutil.copyfileobj(s, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def fetch(models, files, todo):
    """Fetch every entry in todo. Returns (mismatches, other failures)."""
    failures = 0
    mismatches = 0
    cache = {}  # url -> downloaded path, so one archive serves many entries
    with tempfile.TemporaryDirectory(prefix="afe-models-") as work:
        for e in todo:
            name = e["path"]
            url = e.get("url")
            if not url:
                print(f"NO URL    {name}: no vendor URL known; fetch by hand"
                      " and check its sha256")
                failures += 1
                continue
            try:
                if url not in cache:
                    d = tempfile.mkdtemp(prefix="dl-", dir=work)
                    print(f"download  {url}")
                    cache[url] = download(url, d)
                got = cache[url]
                if "member" in e:
                    a = sha256_file(got)
                    if a != e["archive_sha256"]:
                        # Not opened: an archive that is not the pinned one
                        # is not read at all.
                        print(f"MISMATCH  {name}: archive {url} sha256 {a},"
                              f" manifest pins {e['archive_sha256']};"
                              " not extracted")
                        mismatches += 1
                        continue
                    got = extract_member(got, e["member"], e["size"], url)
                h = sha256_file(got)
                if h != e["sha256"]:
                    print(f"MISMATCH  {name}: downloaded sha256 {h}, manifest"
                          f" pins {e['sha256']}; not installed")
                    mismatches += 1
                    continue
                install(got, models / name)
                print(f"installed {name}")
            except FetchError as err:
                print(f"ERROR     {name}: {err}; not installed")
                failures += 1
    return mismatches, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS,
                    help="where the files live (default: %(default)s)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="manifest to read (default: <models-dir>/manifest.json)")
    ap.add_argument("--check", action="store_true",
                    help="verify the files present; download nothing")
    ap.add_argument("--replace", action="store_true",
                    help="replace a present file that fails its hash, but"
                         " only with a download that verifies")
    args = ap.parse_args(argv)
    models = args.models_dir.resolve()
    manifest = args.manifest or models / "manifest.json"

    try:
        files = load_manifest(manifest)
    except FetchError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    ok, missing, bad = verify_present(models, files)
    for e in ok:
        print(f"ok        {e['path']}")
    for e, got in bad:
        print(f"MISMATCH  {e['path']}: sha256 {got}, manifest pins {e['sha256']}")
    for e in missing:
        print(f"missing   {e['path']}")

    if args.check:
        print(f"\n{len(ok)} ok, {len(bad)} mismatched, {len(missing)} missing"
              f" of {len(files)} ({manifest})")
        if bad:
            print("FAIL: hash mismatch; a file is not the one pinned")
        elif missing:
            print("FAIL: files missing; run without --check to fetch them")
        return 1 if bad or missing else 0

    todo = list(missing)
    if bad and args.replace:
        todo += [e for e, _ in bad]
    mismatches, failures = fetch(models, files, todo) if todo else (0, 0)
    if bad and not args.replace:
        print("FAIL: present files fail their hash and were left alone;"
              " --replace fetches verified copies over them")
        return 1
    if mismatches or failures:
        print(f"FAIL: {mismatches + failures} file(s) not installed"
              f" ({mismatches} hash mismatch)")
        return 1 if mismatches else 2
    print(f"\nall {len(files)} files verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
