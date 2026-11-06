"""The build image's recipe: that it can be built from nothing, and that
an image built from a different recipe is refused.

No docker, no network: the Dockerfile is read as text, `image-id.sh
recipe` runs on copies of it, and `run.sh` runs against a stub `docker`
that answers only the questions it asks.

The failure each test guards is silent. A trust-root install pinned to
the live archive builds for weeks and then stops resolving; an image
older than its Dockerfile runs and certifies inputs the commit no longer
states.
"""
import json
import os
import re
import shutil
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER = os.path.join(REPO, "docker")


def _text(name):
    with open(os.path.join(DOCKER, name), encoding="utf-8") as fh:
        return fh.read()


def _run_step():
    """The Dockerfile's first RUN, which installs the apt packages."""
    text = _text("Dockerfile")
    start = text.index("RUN set -eux; \\\n    apt-get update -qq;")
    return text[start:text.index("rm -rf /var/lib/apt/lists/*", start)]


# -- the trust-root bootstrap ----------------------------------------------

def test_bootstrap_installs_trust_roots_unpinned_before_the_snapshot():
    step = _run_step()
    first = step.index("apt-get install")
    snapshot = step.index("snapshot.ubuntu.com")
    head = step[first:snapshot]
    assert re.search(r"ca-certificates\s*;", head), head
    assert "=" not in head.split("ca-certificates")[0].split("install")[1]
    assert "CA_CERTIFICATES_VERSION" not in head


def test_pinned_trust_roots_come_from_the_snapshot_and_may_downgrade():
    step = _run_step()
    after = step[step.index("snapshot.ubuntu.com"):]
    install = after[after.index("install -y"):]
    assert "--allow-downgrades" in install.split("ca-certificates=")[0]
    assert '"ca-certificates=${CA_CERTIFICATES_VERSION}"' in install


def test_no_install_asks_the_live_archive_for_a_pinned_version():
    step = _run_step()
    before = step[:step.index("snapshot.ubuntu.com")]
    assert not re.search(r"\w=\$\{?\w", before.split("install -y")[1])


# -- the manifest ----------------------------------------------------------

def test_manifest_agrees_with_the_dockerfile():
    manifest = json.loads(_text("image-revisions.json"))
    assert isinstance(manifest["current"], int) and manifest["current"] >= 1
    assert re.search(r"ARG XPACK_VERSION=%s\b" % re.escape(manifest["xpack"]),
                     _text("Dockerfile"))
    assert manifest["legacy"] == "due-build:%s" % manifest["xpack"]


# -- the recipe hash -------------------------------------------------------

@pytest.fixture
def dockerdir(tmp_path):
    d = tmp_path / "docker"
    d.mkdir()
    for name in ("Dockerfile", "image-id.sh", "run.sh", "image-revisions.json"):
        shutil.copy(os.path.join(DOCKER, name), d / name)
    return d


def _recipe(d):
    out = subprocess.run(["bash", str(d / "image-id.sh"), "recipe"],
                         capture_output=True, text=True, check=True)
    assert re.fullmatch(r"[0-9a-f]{64}", out.stdout.strip())
    return out.stdout.strip()


def test_recipe_ignores_comments_and_blank_lines(dockerdir):
    before = _recipe(dockerdir)
    p = dockerdir / "Dockerfile"
    p.write_text("# a new comment\n\n" + p.read_text(encoding="utf-8") + "\n\n# trailing\n", encoding="utf-8")
    assert _recipe(dockerdir) == before


def test_recipe_moves_with_any_instruction(dockerdir):
    before = _recipe(dockerdir)
    p = dockerdir / "Dockerfile"
    p.write_text(p.read_text(encoding="utf-8").replace("--allow-downgrades", "--allow-downgrade"), encoding="utf-8")
    assert _recipe(dockerdir) != before


# -- run.sh's refusal ------------------------------------------------------

STUB = """#!/bin/bash
# stands in for docker: answers `image inspect` from files, accepts the rest
case "$*" in
  *'index .Config.Labels'*) cat "$STUB_DIR/label"; echo ;;
  *'{{.Id}}'*) echo sha256:feed ;;
  *RootFS*) echo layer ;;
  "image inspect"*) [ -e "$STUB_DIR/present" ] || exit 1 ;;
  *) exit 0 ;;
esac
"""


def _launch(dockerdir, tmp_path, image, label=None, present=True):
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    s = stub / "docker"
    s.write_text(STUB, encoding="utf-8")
    s.chmod(s.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "label").write_text(label or "", encoding="utf-8")
    if present:
        (state / "present").write_text("", encoding="utf-8")
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}",
               STUB_DIR=str(state), DUE_BUILD_IMAGE=image)
    return subprocess.run(["bash", str(dockerdir / "run.sh"), "true"],
                          capture_output=True, text=True, env=env, cwd=REPO)


def test_run_accepts_an_image_built_from_this_recipe(dockerdir, tmp_path):
    r = _launch(dockerdir, tmp_path, "due-build:x-r9", label=_recipe(dockerdir))
    assert r.returncode == 0, r.stderr


def test_run_refuses_an_image_from_another_recipe(dockerdir, tmp_path):
    r = _launch(dockerdir, tmp_path, "due-build:x-r9", label="0" * 64)
    assert r.returncode == 2
    assert "different Dockerfile" in r.stderr


def test_run_refuses_an_image_with_no_recipe_label(dockerdir, tmp_path):
    r = _launch(dockerdir, tmp_path, "due-build:x-r9", label="")
    assert r.returncode == 2


def test_run_accepts_the_grandfathered_image_by_name(dockerdir, tmp_path):
    legacy = json.loads(_text("image-revisions.json"))["legacy"]
    r = _launch(dockerdir, tmp_path, legacy, label="")
    assert r.returncode == 0, r.stderr


def test_run_refuses_a_missing_image(dockerdir, tmp_path):
    r = _launch(dockerdir, tmp_path, "due-build:x-r9", present=False)
    assert r.returncode == 2
    assert "no such image" in r.stderr
