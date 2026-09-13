"""`tools/host_conditions.py` must collect without a board, and must not
invent a field it cannot measure.

It records what was true of the HOST when an arm ran - hub port, whether
the device nodes were recreated, load, uptime - because the #5 crossover
turned on a question nothing in this project recorded: did anything about
this session change between two arms? `mac-bench`'s control bounds drift
on their board and their host, and `windows-desk` pointed out that this
excludes neither handling nor a session difference on a different bench.

Two properties are worth a test and the rest is plumbing:

  * it opens no serial port. A conditions reader that perturbs the thing
    it is describing is useless, and it is meant to run immediately
    before and after a capture.
  * an unmeasurable field is absent or None, never guessed. `usb_path`
    is Linux sysfs and has no meaning elsewhere; a field that is
    sometimes a guess is worse than one that is sometimes missing,
    because only the second is visible to a reader.

Needs no board.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "host_conditions.py")
sys.path.insert(0, os.path.join(REPO, "tools"))

import host_conditions as hc  # noqa: E402


def test_it_collects_and_carries_the_fields_an_arm_needs():
    row = hc.collect()
    for k in ("t", "kernel", "platform", "python", "cpus", "repo_rev"):
        assert k in row, k
    # Every value must be JSON-serialisable, since it is written beside
    # rows that are.
    json.loads(json.dumps(row))


def test_it_opens_no_serial_port():
    """Run in a fresh interpreter with `serial` poisoned. If the tool
    reaches pyserial at all, this fails - which is the property that
    makes it safe to run beside a capture."""
    driver = (
        "import sys, types\n"
        "bad = types.ModuleType('serial')\n"
        "def boom(*a, **k):\n"
        "    raise AssertionError('host_conditions opened a port')\n"
        "bad.Serial = boom\n"
        "bad.__getattr__ = lambda n: boom\n"
        "sys.modules['serial'] = bad\n"
        f"sys.path.insert(0, {os.path.join(REPO, 'tools')!r})\n"
        "import host_conditions as hc\n"
        "row = hc.collect()\n"
        "print('OK', 'ports' in row or 'ports_error' in row)\n"
    )
    out = subprocess.run([sys.executable, "-c", driver], cwd=REPO,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-800:]
    assert "OK" in out.stdout


def test_an_unmeasurable_path_is_none_not_a_guess():
    assert hc.usb_path("/dev/definitely-not-a-tty-node") is None
    assert hc.node_ctime("/dev/definitely-not-a-tty-node") is None


@pytest.mark.skipif(sys.platform != "linux", reason="sysfs is Linux's")
def test_on_linux_a_real_tty_resolves_to_a_usb_path():
    """The positive control. Without it the test above passes on a tool
    that returns None for everything."""
    ttys = [f"/dev/{n}" for n in sorted(os.listdir("/sys/class/tty"))
            if n.startswith("ttyACM")]
    if not ttys:
        pytest.skip("no ttyACM node on this host")
    paths = [hc.usb_path(t) for t in ttys]
    assert any(p and p.startswith("usb") for p in paths), paths
    assert any(hc.node_ctime(t) for t in ttys)


def test_the_cli_appends_a_row(tmp_path):
    out = tmp_path / "cond.jsonl"
    r = subprocess.run([sys.executable, TOOL, "--json", str(out),
                        "--label", "unit-test"], cwd=REPO,
                       capture_output=True, text=True, check=True)
    assert out.exists()
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert len(rows) == 1 and rows[0]["label"] == "unit-test"
    # Appends rather than truncates: a second call keeps the first.
    subprocess.run([sys.executable, TOOL, "--json", str(out),
                    "--label", "second"], cwd=REPO, capture_output=True,
                   text=True, check=True)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert [r["label"] for r in rows] == ["unit-test", "second"]
