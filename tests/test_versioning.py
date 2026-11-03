"""One semantic version for the project (docs/versioning.md, tools/release.py)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import release                                                  # noqa: E402
import version                                                  # noqa: E402

PLATFORM_SEAM_EXEMPT = "reads source files and runs fake git; no OS branch is reached"


def fake_git(tags="", status=""):
    return lambda *a: tags if a[0] == "tag" else status


def tree(tmp_path, project, h7):
    for rel, prefix, v in ((version.PROJECT_HEADER, "FW_VERSION", project), (version.H7_SOURCE, "H7_FW", h7)):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        ma, mi, pa = v.split(".")
        p.write_text(f"#define {prefix}_MAJOR {ma}\n#define {prefix}_MINOR {mi}\n#define {prefix}_PATCH {pa}\n", encoding="utf-8")
    return str(tmp_path)


def test_the_project_version_is_read_from_the_header_and_is_semver():
    v = version.project_version()
    assert v and version.SEMVER.match(v), v


def test_the_identity_the_firmware_reports_and_the_version_the_host_reports_are_one_number():
    """`fw=` in the identity is built from the same three fields the host reads; the doc-reference test holds the docs to it, this holds the host."""
    import re
    text = open(os.path.join(ROOT, version.PROJECT_HEADER), encoding="utf-8").read()
    parts = [re.search(rf"FW_VERSION_{p}\s+(\d+)", text).group(1) for p in ("MAJOR", "MINOR", "PATCH")]
    assert version.project_version() == ".".join(parts)


def test_a_release_needs_every_component_to_say_the_tag(tmp_path):
    ok = release.conditions("v0.3.0", tree(tmp_path, "0.3.0", "0.3.0"), fake_git())
    assert all(o for o, _ in ok), ok
    lag = release.conditions("v0.3.0", tree(tmp_path, "0.3.0", "0.1.0"), fake_git())
    assert [t for o, t in lag if not o] == ["H7 firmware (ctl_h7.c) says 0.1.0, the tag says 0.3.0"]


@pytest.mark.parametrize("tag", ["0.3.0", "v0.3", "vx.y.z", "v01.2.3"])
def test_a_tag_that_is_not_a_semantic_version_is_refused(tmp_path, tag):
    assert not release.conditions(tag, tree(tmp_path, "0.3.0", "0.3.0"), fake_git())[0][0]


def test_an_existing_tag_or_a_dirty_tree_is_refused(tmp_path):
    root = tree(tmp_path, "0.3.0", "0.3.0")
    assert not all(o for o, _ in release.conditions("v0.3.0", root, fake_git(tags="v0.3.0\n")))
    assert not all(o for o, _ in release.conditions("v0.3.0", root, fake_git(status=" M x\n")))


def test_sums_cover_the_images_and_refuse_an_empty_directory(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "a.bin").write_bytes(b"abc")
    (tmp_path / "build-env.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    rows = release.sums(str(tmp_path))
    assert len(rows) == 2 and any(r.startswith("ba7816bf") and r.endswith("build/a.bin") for r in rows) and "ignored" not in "".join(rows)    # sha256("abc")
    empty = tmp_path / "e"; empty.mkdir()
    with pytest.raises(SystemExit):
        release.sums(str(empty))
