"""
Harness for the on-hardware test suite.

Every test here talks to a real Arduino Due over two USB ports. There is
no simulator and no mock: the failures this suite exists to catch -
silent trigger overruns, spliced sample data, a link that retransmits -
have no software model to run against.

Two things shape the design:

  * Opening the control port asserts NRSTB and resets the board, which
    also re-enumerates the native port under a possibly new name. Paying
    that per test costs about 15 s each. The Board is session scoped and
    holds the port open, which turns it into roughly half a second.

  * Flashing is the slowest and least reliable step, so the suite asks
    the board which firmware it is running and flashes only when that
    disagrees with --track. --reflash forces it.

Run it from the project venv:

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest tests -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import measure  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(HERE, "baseline.json")

# The order the suite runs in, and the reason for it. The daemon's own
# tests need no board and cost three seconds, so they go first and fail
# before anything has been flashed. Then a physical fault must be
# diagnosed before anything blames firmware for it, contract checks are
# cheap and catch regressions before the long streaming tests have
# started, and the transport benchmarks are the slowest thing here. The
# daemon's one hardware case runs last: it is the only test that wants
# the board in a state nothing else cares about.
FILE_ORDER = ["test_jitter", "test_daemon_protocol", "test_daemon_api",
              "test_link_health", "test_contract", "test_channels",
              "test_rates", "test_integrity", "test_transport",
              "test_daemon_hardware"]


def pytest_addoption(parser):
    g = parser.getgroup("due")
    g.addoption("--track", action="store", default="both",
                choices=("a", "b", "both"),
                help="which firmware to test; default both")
    g.addoption("--reflash", action="store_true",
                help="flash even when the board already runs the right track")
    g.addoption("--no-flash", action="store_true",
                help="never flash; fail if the wrong track is on the board")
    g.addoption("--no-build", action="store_true",
                help="flash the existing artefacts without rebuilding")
    g.addoption("--calibrate", action="store_true",
                help="record measurements into tests/baseline.json instead "
                     "of asserting against it")
    g.addoption("--seconds", action="store", type=float, default=None,
                help="override the streaming window for every measurement")


def pytest_configure(config):
    for m, desc in (
        ("smoke", "fast enough to run on every iteration"),
        ("slow", "tens of seconds; transport benchmarks"),
        ("awg", "drives the DAC"),
        ("scope", "drives the ADC"),
        ("track_a", "Track A only"),
        ("track_b", "Track B only"),
    ):
        config.addinivalue_line("markers", f"{m}: {desc}")


def pytest_generate_tests(metafunc):
    if "track" in metafunc.fixturenames:
        opt = metafunc.config.getoption("--track")
        tracks = ["a", "b"] if opt == "both" else [opt]
        metafunc.parametrize("track", tracks, scope="session", indirect=True)


def pytest_collection_modifyitems(config, items):
    """Run the files in FILE_ORDER, and keep each track's tests together.

    pytest already groups by a session-scoped parametrised fixture, but
    the grouping is what stops the suite reflashing between every test,
    so it is made explicit rather than relied on.
    """
    def key(item):
        mod = item.module.__name__.rsplit(".", 1)[-1]
        try:
            fileno = FILE_ORDER.index(mod)
        except ValueError:
            fileno = len(FILE_ORDER)
        trk = ""
        if hasattr(item, "callspec"):
            trk = str(item.callspec.params.get("track", ""))
        return (trk, fileno)

    items.sort(key=key)


@pytest.fixture(scope="session")
def track(request):
    return request.param


@pytest.fixture(scope="session")
def baseline():
    with open(BASELINE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def calibration(request):
    """Collects measurements when --calibrate is given, and writes them
    beside the committed baseline for a human to promote.

    Written to a separate file on purpose: baseline.json is a record of
    one board's measured behaviour and belongs under review, not
    overwritten by whatever the last run happened to see.
    """
    data = {}
    yield data
    if request.config.getoption("--calibrate") and data:
        out = os.path.join(HERE, "baseline.measured.json")
        with open(out, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"\ncalibration written to {out}")


@pytest.fixture(scope="session")
def board(request, track):
    """The board, with its control port held open for the session."""
    want = track
    b = None
    try:
        b = measure.Board(settle=3.0)
    except measure.BoardError as e:
        pytest.skip(f"no board: {e}")

    have, banner = measure.which_track(b)
    if have != want or request.config.getoption("--reflash"):
        if request.config.getoption("--no-flash"):
            b.close()
            pytest.skip(f"board runs track {have}, wanted {want}, "
                        f"and --no-flash was given")
        b.close()
        measure.flash(want, build=not request.config.getoption("--no-build"))
        b = measure.Board(settle=3.0)
        have, banner = measure.which_track(b)
        if have != want:
            b.close()
            pytest.fail(f"flashed track {want} but the board reports {have!r}")

    b.stop()
    b.drain_console(0.5)
    yield b
    try:
        b.stop()
    finally:
        b.close()


@pytest.fixture(autouse=True)
def quiesce(request):
    """Stop whatever the last test left running.

    Every measurement here starts a stream on the device and every one
    of them stops it, but a failing assertion can leave one running, and
    a device still streaming into the kernel buffer is precisely the
    stale data that once got read as a live capture.
    """
    if "board" not in request.fixturenames:
        yield
        return
    b = request.getfixturevalue("board")
    b.stop()
    b.poll_console()
    yield
    b.stop()
    b.poll_console()


@pytest.fixture
def seconds(request):
    """Streaming window, overridable for a quick pass."""
    return request.config.getoption("--seconds")
