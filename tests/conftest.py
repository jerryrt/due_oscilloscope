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
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import measure  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(HERE, "baseline.json")

# The order the suite runs in, and the reason for it. Port discovery and
# the daemon's own tests need no board and cost three seconds, so they go
# first and fail before anything has been flashed - discovery first of
# all, because everything after it depends on naming the right node. Then a physical fault must be
# diagnosed before anything blames firmware for it, contract checks are
# cheap and catch regressions before the long streaming tests have
# started, and the transport benchmarks are the slowest thing here. The
# daemon's one hardware case runs last: it is the only test that wants
# the board in a state nothing else cares about.
FILE_ORDER = ["test_ports", "test_waveforms", "test_jitter",
              "test_daemon_protocol",
              "test_daemon_api", "test_link_health", "test_control",
              "test_load", "test_contract",
              "test_channels", "test_rates", "test_integrity",
              "test_transport", "test_daemon_hardware"]


def pytest_addoption(parser):
    g = parser.getgroup("due")
    g.addoption("--track", action="store", default="both",
                choices=("a", "b", "c", "both"),
                help="which firmware to test; default both. `c` is the "
                     "FreeRTOS build (issue #45) and is NOT in `both`: "
                     "it is opt-in until it passes, so a track still "
                     "growing its command surface cannot turn every "
                     "bench's suite red")
    g.addoption("--reflash", action="store_true",
                help="flash even when the board already runs the right track")
    g.addoption("--no-flash", action="store_true",
                help="never flash; fail if the wrong track is on the board")
    g.addoption("--no-build", action="store_true",
                help="flash the existing artefacts without rebuilding")
    g.addoption("--dso", action="store_true",
                help="require the bench oscilloscope; without it, tests "
                     "that need one skip when it is absent")
    g.addoption("--calibrate", action="store_true",
                help="record measurements into tests/baseline.json instead "
                     "of asserting against it")
    g.addoption("--seconds", action="store", type=float, default=None,
                help="override the streaming window for every measurement")
    g.addoption("--no-ceiling", action="store_true",
                help="do not fail the board-free tier for exceeding its "
                     "five-minute ceiling (issue #50); for a bench slower "
                     "than the one the constant was measured on")
    g.addoption("--require-board", action="store_true",
                help="fail rather than skip when the board is absent or "
                     "on the wrong track (issue #58). For measurement "
                     "harnesses that score runs by matching pytest's "
                     "summary: a skip matches no failure pattern, so it "
                     "scores as a pass and an arm that never executed "
                     "reads as green. Same shape as --dso for the scope")
    g.addoption("--mixed-instruments-ok", action="store_true",
                help="do not fail a session that read counters over both "
                     "the control channel and the console (issue #51). "
                     "For deliberately exercising the fallback; a session "
                     "that hits it by accident holds two populations of "
                     "measurements and should say so")


def pytest_configure(config):
    for m, desc in (
        ("board", "needs the board attached; applied automatically to "
                  "any test that resolves the board fixture"),
        ("smoke", "fast enough to run on every iteration"),
        ("slow", "tens of seconds; transport benchmarks"),
        ("awg", "drives the DAC"),
        ("scope", "drives the ADC"),
        ("dso", "needs the bench oscilloscope attached"),
        ("track_a", "Track A only"),
        ("track_b", "Track B only"),
    ):
        config.addinivalue_line("markers", f"{m}: {desc}")


def pytest_generate_tests(metafunc):
    if "track" in metafunc.fixturenames:
        opt = metafunc.config.getoption("--track")
        # `both` stays A and B deliberately - see --track's help.
        tracks = ["a", "b"] if opt == "both" else [opt]
        metafunc.parametrize("track", tracks, scope="session", indirect=True)


def pytest_collection_modifyitems(config, items):
    """Mark what needs the board, then run the files in FILE_ORDER.

    pytest already groups by a session-scoped parametrised fixture, but
    the grouping is what stops the suite reflashing between every test,
    so it is made explicit rather than relied on.

    **The `board` marker is applied here rather than written on each
    test, because a fixture cannot be forgotten and a marker can.**
    Issue #50 wants "the ones that would catch this change" to be
    selectable, and the first cut of that is board-free against
    board-required. A test needs the board exactly when it resolves the
    `board` fixture - directly or through any fixture that does - and
    `fixturenames` already knows, so asking it is exact where a
    hand-written marker would drift the first time a helper grew a
    dependency.

    Measured on mac-bench: 12 of 36 files hold every board test, and
    they are about 88% of the Track B clock. So `-m "not board"` is the
    fast loop the issue is asking for, and it needs no hardware at all.
    """
    for item in items:
        if "board" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.board)

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
def dso(request):
    """The bench oscilloscope. Skips without one; --dso makes absence
    fatal, for a bench where it is supposed to be attached and its
    absence is the bug.

    Session-scoped and here rather than in one test module, because more
    than one file needs it now and opening the instrument twice is a
    USBTMC claim conflict rather than a second handle.
    """
    import scope as scope_mod
    try:
        inst = scope_mod.open_scope()
    except Exception as e:                      # ScopeUnavailable, or pyusb
        if request.config.getoption("--dso"):
            pytest.fail(f"--dso given but no scope: {e}")
        pytest.skip(f"no bench scope: {e}")
    yield inst
    try:
        inst.averaging(None)
    finally:
        inst.close()


@pytest.fixture
def provenance(board, dso):
    """The conditions a measurement has to carry to mean anything.

    Fails the test rather than recording an unattributable number. That
    is deliberate and it is the whole point of the fixture: this project
    has twice had a figure outlive the thing it described - a version
    string that disagreed with its own numbers, and a recorded pass rate
    taken with instruments that no longer existed - and in both cases
    the number looked fine.
    """
    import provenance as prov
    p = prov.collect(board=board, inst=dso)
    gaps = prov.missing(p)
    assert not gaps, (
        f"refusing to record: provenance is missing {gaps}. A measurement "
        f"without its conditions is not a baseline point.")
    return p


@pytest.fixture(scope="session")
def board(request, track):
    """The board, with its control port held open for the session."""
    want = track
    b = None
    # Issue #58. An experiment harness scores runs by pattern-matching
    # pytest's summary line, and a skip is the outcome nobody writes a
    # pattern for: `*failed*` does not match "1 skipped", so a skipped
    # run scores as a pass. It has now cost two benches on one day -
    # ten green lines and zero tests executed on windows-desk, and ten
    # bisect steps on linux-x1, where a live control certified the
    # lever while the test arm was not executing at all.
    #
    # --require-board turns both board skips into failures. Same shape
    # as --dso above, which already does it for the scope. Measuring
    # code should pass it; the suite should not.
    #
    # WHAT IT DOES AND DOES NOT FIX, measured rather than assumed - a
    # fixture failure is an ERROR to pytest, not a failure:
    #
    #   without it   exit 0, "1 skipped in 4.04s"
    #   with it      exit 1, "1 error in 4.10s"
    #
    # So it fixes the EXIT CODE and not the text: a harness matching
    # `*failed*` mis-scores BOTH of those as a pass. This flag is
    # defence in depth and does not remove the need for the harness to
    # test positively - match "1 passed", or check the exit code. Do
    # not let it be quoted as making a text-matching harness safe.
    require = request.config.getoption("--require-board")
    try:
        b = measure.Board(settle=3.0)
    except measure.BoardError as e:
        if require:
            pytest.fail(f"--require-board given but no board: {e}")
        pytest.skip(f"no board: {e}")

    have, banner = measure.which_track(b)
    if have != want or request.config.getoption("--reflash"):
        if request.config.getoption("--no-flash"):
            b.close()
            if require:
                pytest.fail(f"--require-board given but board runs track "
                            f"{have}, wanted {want}, and --no-flash was given")
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


@pytest.fixture(scope="session")
def run_cache():
    """Board runs shared by tests that ask for identical parameters.

    Session-scoped because the runs it holds are the expensive thing in
    the suite, and function-scoped would defeat the point. See
    `helpers.shared_run` for when sharing is correct and when it is
    not.
    """
    return {}


# The board-free tier's ceiling, in seconds. Measured at 94.56 s and
# 95.49 s on mac-bench at b24ccdb for 441 tests, so this is 3x headroom
# rather than a number the tier is already pressed against.
BOARD_FREE_CEILING_S = 300.0


def pytest_sessionstart(session):
    session._due_t0 = time.time()


def pytest_sessionfinish(session, exitstatus):
    """Hold the board-free tier to five minutes, enforced not intended.

    Issue #50 exists because section 8 of docs/testing.md claimed a
    five-minute budget as an *intention* and it had drifted to fifteen
    without anything noticing. An intention that nothing checks is how
    that happens, so this checks.

    **Only the board-free tier is enforced here, and that is deliberate
    rather than timid.** The full suite is ~88% board tests, several of
    which are irreducibly slow because they are measuring something slow
    - test_rates.py's 22 distinct rates cost 105-108 s on two benches
    with nothing to share - and the issue's own constraint says such a
    test gets marked and kept out of the default run, never weakened.
    Putting a ceiling on the full suite would mean hitting a number by
    moving tests out of it, which is the same thing with worse
    bookkeeping. Whether the full suite gets one, and at what, is on
    #50 for the owner.

    A failing ceiling is reported as a session failure rather than a
    warning because a warning is what section 8 already was.
    `--no-ceiling` exists for a bench slower than this one, so the
    escape is deliberate and visible rather than a quiet edit to the
    constant.
    """
    if getattr(session.config.option, "no_ceiling", False):
        return
    t0 = getattr(session, "_due_t0", None)
    if t0 is None or session.testscollected == 0:
        return
    # Board tests set their own pace and are not what this bounds.
    if any("board" in getattr(i, "fixturenames", ())
           for i in getattr(session, "items", ())):
        return
    elapsed = time.time() - t0
    if elapsed > BOARD_FREE_CEILING_S:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                f"board-free tier took {elapsed:.1f}s against a "
                f"{BOARD_FREE_CEILING_S:.0f}s ceiling (issue #50). This is "
                f"the per-change loop; if it is genuinely this slow now, "
                f"move work out of it or raise the constant deliberately "
                f"- do not let it drift the way section 8 of "
                f"docs/testing.md did.", red=True)
        session.exitstatus = 1
    _check_one_instrument(session)


def _check_one_instrument(session):
    """Did this session measure with one instrument or two? Issue #51.

    `play_counters()` and `occupancy()` read over the control channel
    where there is one and fall back to `B` and `O` on the console.
    Control reads a counter in 146 us; the fallback costs 13.14 ms and
    15.40 ms of blocked main loop **taken while the sample path is
    running**, which is invariant 8. They are two experiments, not two
    tolerances of one.

    A link that drops mid-suite therefore leaves a run holding two
    populations with nothing marking the boundary. That is #51, it cost
    a whole session once, and the trigger here is an objective-0c
    `close()` wedge - which re-enumerates the native port and is
    *guaranteed* to drop the link, on the bench where 0c happens.

    **Why this is a session hook and not a test.** `test_control.py`
    already asserts `via == "control"`, but it runs seventh in
    `FILE_ORDER` and the wedge happens in the playback tests after it.
    Moving it is a reorder of a load-bearing list and is the owner's
    call on #51; asking the question again at the end is additive and
    is not.

    **The `ctlver=0` exemption falls out of the counters and needs no
    new state.** If `control` is above zero the link demonstrably
    existed this session, so a `console` read is a *drop*. If `control`
    is zero the board never had one - an image built before 2026-08-27,
    or a track without the opcode - and the console is not a downgrade,
    it is the only instrument. Only the first fails.

    Failing rather than warning, for the reason the ceiling above gives:
    a warning is what this already was. `_note_fallback()` raises a
    `RuntimeWarning` at the moment it happens, and #51 happened anyway.
    """
    if getattr(session.config.option, "mixed_instruments_ok", False):
        return
    reads = dict(measure.INSTRUMENT_READS)
    control, console = reads.get("control", 0), reads.get("console", 0)
    if not console:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if not control:
        # No control channel this session. Honest, and not a drop.
        if reporter is not None:
            reporter.write_line(
                f"instrument: {console} counter read(s) over the console, "
                f"none over the control channel - this board has no "
                f"control channel, so that is the only instrument and "
                f"not a downgrade (issue #51).")
        return
    if reporter is not None:
        reporter.write_line(
            f"instrument: this session read counters BOTH ways - "
            f"{control} over the control channel and {console} over the "
            f"console (issue #51). The link dropped mid-run, so these "
            f"figures are two populations with nothing marking the "
            f"boundary: the console reads cost 13-20 ms of blocked main "
            f"loop taken while the sample path was running, which is "
            f"invariant 8. Check `Board.ctl_why`. Re-run before "
            f"quoting any number from it; --mixed-instruments-ok if the "
            f"fallback was the point.", red=True)
    session.exitstatus = 1
