"""The metric pipeline's portability, which is a property worth a test.

`tools/metrics.py` produces the report this project quotes, and the
reason it can be re-run on another bench is that it needs **no
instrument**: the ADC is the instrument, the board is opened directly,
and nothing imports `host/scope.py` or touches USBTMC.

That is easy to lose. One `import` added for one convenience turns a
report anybody can reproduce into one that only the desk with a DS1102E
on it can, and nothing would fail on this desk to say so - the scope is
plugged in here. So the check runs in a subprocess and asserts the
absence, the same shape as the GUI suite's "importing `gui.stream` must
not pull in PySide6".
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _in_subprocess(code):
    """Import in a clean interpreter: this one has already imported the
    world, so `sys.modules` here proves nothing."""
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


def test_the_metric_pipeline_needs_no_instrument():
    """The property that lets another bench reproduce the report."""
    got = _in_subprocess(
        "import sys; sys.path.insert(0,'host'); sys.path.insert(0,'tools');"
        "import metrics;"
        "bad=[m for m in ('scope','usb','usb1','libusb_package')"
        " if m in sys.modules];"
        "print(','.join(bad))")
    assert got == "", (
        f"tools/metrics.py pulled in {got}. The report is quotable on any "
        f"bench precisely because it needs no instrument; an import that "
        f"reaches for one takes that away silently, because the scope is "
        f"attached on the desk where this was written.")


def test_the_pipeline_reports_firmware_and_not_a_daemon():
    """Scope is one program on purpose. A report qualified by two
    version sets invites the reader to wonder which one a figure
    depended on."""
    got = _in_subprocess(
        "import sys; sys.path.insert(0,'host'); sys.path.insert(0,'tools');"
        "import metrics, inspect;"
        "src=inspect.getsource(metrics.render);"
        "print('daemon_rev' in src or 'daemon_code_rev' in src)")
    assert got == "False"


def test_provenance_requires_the_firmware_commit():
    """`fw_version` is bumped by hand and says what somebody intended.
    Two benches reported 0.2.0 four hours and three DAC commits apart."""
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov
    assert "fw_repo_rev" in prov.REQUIRED
    assert "bench" in prov.REQUIRED
    # And an empty one is refused rather than recorded.
    assert "fw_repo_rev" in prov.missing({"track": "b"})


def test_an_unlogged_flash_cannot_produce_a_report(tmp_path, monkeypatch):
    """A board flashed by something that does not log has unknown
    provenance, and that is a refusal rather than a blank field."""
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov
    monkeypatch.setattr(prov, "FLASH_LOG", str(tmp_path / "nothing.jsonl"))
    fw = prov.firmware("Aug 27 2026 16:14:27")
    assert fw == {"fw_provenance": "unlogged"}
    assert "fw_repo_rev" in prov.missing(fw)
