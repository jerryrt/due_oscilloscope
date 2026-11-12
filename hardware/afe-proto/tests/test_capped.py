import sys

import pytest

from simtools import capped

pytestmark = pytest.mark.skipif(not capped.available(), reason="needs systemd user scopes with a memory cap")

ALLOC = "import sys; b = bytearray(int(sys.argv[1])); print('ok')"


def test_job_under_the_cap_runs_and_reports_its_peak():
    r = capped.run([sys.executable, "-c", ALLOC, str(150_000_000)], mem="1G", timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout and not r.cap_killed
    assert 140e6 < r.peak_rss_bytes < 400e6, r.peak_rss_bytes


def test_job_over_the_cap_is_killed_not_swapped():
    r = capped.run([sys.executable, "-c", ALLOC, str(600_000_000)], mem="200M", timeout=60)
    assert r.cap_killed and r.returncode == capped.CAP_KILLED and "ok" not in r.stdout


def test_timeout_is_reported_and_bounded():
    r = capped.run([sys.executable, "-c", "import time; time.sleep(60)"], mem="200M", timeout=2)
    assert r.timed_out and r.returncode == capped.TIMED_OUT and r.wall_s < 15


def test_a_failing_job_keeps_its_own_exit_code():
    r = capped.run([sys.executable, "-c", "raise SystemExit(3)"], mem="200M", timeout=30)
    assert r.returncode == 3 and not r.cap_killed and not r.timed_out


def test_a_shell_string_is_refused():
    with pytest.raises(TypeError):
        capped.run("echo hi")


def test_a_missing_summary_is_an_error_not_a_pass(monkeypatch, tmp_path):
    fake = tmp_path / "capped.sh"
    fake.write_text("#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(capped, "CAPPED_SH", fake)
    with pytest.raises(RuntimeError):
        capped.run(["true"])
