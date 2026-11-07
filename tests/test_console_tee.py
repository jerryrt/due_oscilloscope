"""Passive console tee. No board; fake ports only."""
import os
import random

import pytest

import transport

PLATFORM_SEAM_EXEMPT = "the tee wraps fake ports and touches no OS branch; open_raw's real Port is monkeypatched out"


class FakePort:
    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.closed = False
        self.extra = 7

    def read(self, n):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def _lines(path):
    with open(path, "rb") as fh:
        return fh.read().splitlines()


def test_tee_returns_identical_bytes_and_logs_them(tmp_path):
    rng = random.Random(1)
    chunks = [b"", b"hello\r\n", b"\x00\xff\x80", b"", b"x" * 300,
              bytes(rng.randrange(256) for _ in range(64))]
    log = transport.RotatingLog(str(tmp_path / "c.log"))
    tee = transport.TeePort(FakePort(chunks), log)
    got = [tee.read(1) for _ in chunks]
    assert got == chunks
    lines = _lines(tmp_path / "c.log")
    nonempty = [c for c in chunks if c]
    assert len(lines) == len(nonempty)
    for line, want in zip(lines, nonempty):
        ts, text = line.split(b" ", 1)
        assert float(ts) > 1e9
        assert text == want.decode("utf-8", "replace").encode("unicode_escape")
    assert tee.extra == 7           # delegation
    tee.close()
    assert tee._port.closed


def test_rotation_bounds_size(tmp_path):
    p = str(tmp_path / "c.log")
    log = transport.RotatingLog(p, max_bytes=500)
    for _ in range(200):
        log.write(b"0123456789" * 3)
    log.close()
    assert os.path.getsize(p) <= 500
    assert os.path.getsize(p + ".1") <= 500
    assert not os.path.exists(p + ".2")


def test_failing_log_never_breaks_reads(tmp_path, capsys):
    bad = str(tmp_path / "nodir" / "c.log")
    log = transport.RotatingLog(bad)
    assert log.dead
    tee = transport.TeePort(FakePort([b"abc", b"def"]), log)
    assert tee.read(10) == b"abc" and tee.read(10) == b"def"
    assert capsys.readouterr().err.count("disabled") == 1


def test_write_failure_midstream_disables_once(tmp_path, capsys):
    log = transport.RotatingLog(str(tmp_path / "c.log"))
    log._fh.close()                 # the next write raises ValueError
    tee = transport.TeePort(FakePort([b"a", b"b"]), log)
    assert tee.read(1) == b"a" and tee.read(1) == b"b"
    assert log.dead
    assert capsys.readouterr().err.count("disabled") == 1


@pytest.fixture
def fake_port(monkeypatch):
    monkeypatch.setattr(transport, "Port", lambda d, b, t: FakePort())


def test_disabled_returns_plain_port(monkeypatch, fake_port, capsys):
    monkeypatch.delenv(transport.CONSOLE_LOG_ENV, raising=False)
    assert type(transport.open_raw("x", 1, console=True)) is FakePort
    monkeypatch.setenv(transport.CONSOLE_LOG_ENV, "")
    assert type(transport.open_raw("x", 1, console=True)) is FakePort
    assert capsys.readouterr().err == ""    # no log was even attempted


def test_enabled_only_for_console(monkeypatch, fake_port, tmp_path):
    monkeypatch.setenv(transport.CONSOLE_LOG_ENV, str(tmp_path / "c.log"))
    assert type(transport.open_raw("x", 1)) is FakePort
    assert isinstance(transport.open_raw("x", 1, console=True), transport.TeePort)


def test_unwritable_env_path_falls_back_to_plain(monkeypatch, fake_port, tmp_path):
    monkeypatch.setenv(transport.CONSOLE_LOG_ENV, str(tmp_path / "no" / "c.log"))
    assert type(transport.open_raw("x", 1, console=True)) is FakePort
