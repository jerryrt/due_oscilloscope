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
    disagrees with --track. --reflash forces it. A flash puts the
    container's image of the track on the board, from `docker/out/`, and
    builds nothing; a missing image, or one that does not carry this
    tree's commit, is an error naming the container command, never a
    skip.

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
import ports
import measure  # noqa: E402
import pacing  # noqa: E402

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
                help="which firmware to test; default both (A and B). `c` "
                     "is the FreeRTOS build and is not in `both`, only "
                     "because a third flash and a third run cost more "
                     "than they add: it links Track B's drivers, so its "
                     "totals are not an oracle result")
    g.addoption("--reflash", action="store_true",
                help="flash even when the board already runs the right track")
    g.addoption("--no-flash", action="store_true",
                help="never flash; fail if the wrong track is on the board")
    g.addoption("--dso", action="store_true",
                help="require the bench oscilloscope; without it, tests "
                     "that need one skip when it is absent")
    g.addoption("--calibrate", action="store_true",
                help="record measurements into tests/baseline.json instead "
                     "of asserting against it")
    g.addoption("--seconds", action="store", type=float, default=None,
                help="override the streaming window for every measurement")
    g.addoption("--pacing-report", action="store_true",
                help="record every time.sleep by call site and print where "
                     "the run's waiting went, by pacing level (host/pacing.py)"
                     ". The measurement the delay levels are set from")
    g.addoption("--no-ceiling", action="store_true",
                help="do not fail the run for exceeding the time budget "
                     "of the groups it selected (issue #86, BUDGET_S in "
                     "conftest); for a bench that is being measured "
                     "rather than gated")
    g.addoption("--require-board", action="store_true",
                help="fail rather than skip when the board is absent or "
                     "on the wrong track (issue #58). For measurement "
                     "harnesses that score runs by matching pytest's "
                     "summary: a skip matches no failure pattern, so it "
                     "scores as a pass and an arm that never executed "
                     "reads as green. Same shape as --dso for the scope")
    g.addoption("--require-h7", action="store_true",
                help="fail rather than skip when a test needs a running H7 and none is (absent, or in the "
                     "boot loader). The H7's counterpart of --require-board, for the same reason: a skip scores as a pass "
                     "in a harness that matches pytest's summary text")
    g.addoption("--mixed-instruments-ok", action="store_true",
                help="do not fail a session that read counters over both "
                     "the control channel and the console (issue #51). "
                     "For deliberately exercising a reintroduced console "
                     "fallback; a session that hits it by accident holds "
                     "two populations of measurements and should say so")


_SLEEP_SITES = {}


def _trace_sleeps():
    """Replace time.sleep with a recorder; --pacing-report only."""
    import time as _time
    real = _time.sleep

    def traced(seconds):
        f = sys._getframe(1)
        while f.f_back is not None and f.f_code.co_filename.endswith("pacing.py"):
            f = f.f_back            # attribute a level's sleep to its caller
        site = "%s:%d" % (os.path.relpath(f.f_code.co_filename, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), f.f_lineno)
        t0 = _time.perf_counter()
        real(seconds)
        rec = _SLEEP_SITES.setdefault(site, [0, 0.0])
        rec[0] += 1
        rec[1] += _time.perf_counter() - t0
    _time.sleep = traced


def pytest_report_header(config):
    """What is attached, read without opening a port, so the first lines say which tiers can execute on this bench."""
    import devices
    try:
        return devices.header_lines(ports.census())
    except Exception as e:                      # noqa: BLE001 - a header must never stop a run
        return [f"devices: could not be read ({type(e).__name__}: {e})"]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    import devices
    skipped = [getattr(r, "longrepr", ("", 0, ""))[2] for r in terminalreporter.stats.get("skipped", [])]
    for line in devices.summary_lines(skipped):
        terminalreporter.write_line(line)
    if not config.getoption("--pacing-report"):
        return
    w = terminalreporter.write_line
    w("")
    w("pacing report: where the waiting went (host/pacing.py)")
    total = sum(v[1] for v in _SLEEP_SITES.values())
    w("  slept %.1f s over %d calls at %d sites"
      % (total, sum(v[0] for v in _SLEEP_SITES.values()), len(_SLEEP_SITES)))
    for name, (n, sec) in sorted(pacing.report().items(), key=lambda kv: -kv[1][1]):
        w("  %-7s %7d calls %8.1f s requested" % (name, n, sec))
    for name, (n, mean, peak) in sorted(pacing.observations().items()):
        w("  observed %-22s n=%d mean %.3f max %.3f" % (name, n, mean, peak))
    stages = pacing.phases()
    if stages:
        w("  stages (pacing.Marks): runs, total s, s per run")
        for name, (n, sec) in sorted(stages.items(), key=lambda kv: -kv[1][1]):
            w("    %-26s %5d %8.1f %7.2f" % (name, n, sec, sec / n))
    for site, (n, sec) in sorted(_SLEEP_SITES.items(), key=lambda kv: -kv[1][1])[:15]:
        w("  %8.1f s %7d x %s" % (sec, n, site))


def pytest_configure(config):
    if config.getoption("--pacing-report"):
        _trace_sleeps()
    for m, desc in (
        ("board", "needs the board attached; applied automatically to "
                  "any test that resolves the board fixture"),
        ("due", "needs a Due; applied automatically with `board` to any test that resolves the board fixture"),
        ("h7", "needs a running H7 target; applied automatically (with `board`, so the container's gate never selects it) to "
               "any test that resolves the h7_unit fixture"),
        ("smoke", "fast enough to run on every iteration"),
        ("slow", "tens of seconds; transport benchmarks"),
        ("awg", "drives the DAC"),
        ("scope", "drives the ADC"),
        ("dso", "needs the bench oscilloscope attached"),
        ("track_a", "Track A only"),
        ("track_b", "Track B only"),
        ("disruptive", "restarts or faults the board on purpose. Sorted LAST "
                       "within its track by pytest_collection_modifyitems, so "
                       "no other test runs on a board it has just restarted"),
        ("platform", "depends on this host's own OS branch - "
                     "transport/rt/ports - which the container, always "
                     "Linux, cannot cover. Run natively on every host"),
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
            item.add_marker(pytest.mark.due)
        if "h7_unit" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.board)      # hardware: the board-free gate must never select it
            item.add_marker(pytest.mark.h7)

    def key(item):
        mod = item.module.__name__.rsplit(".", 1)[-1]
        try:
            fileno = FILE_ORDER.index(mod)
        except ValueError:
            fileno = len(FILE_ORDER)
        trk = ""
        if hasattr(item, "callspec"):
            trk = str(item.callspec.params.get("track", ""))
        # A test that restarts the board on purpose goes after every
        # other test of its track: the session shares one board, and a
        # fault re-enumerates USB under whatever runs next.
        disruptive = 1 if item.get_closest_marker("disruptive") else 0
        return (trk, disruptive, fileno)

    items.sort(key=key)


@pytest.fixture(scope="session")
def track(request):
    return request.param


@pytest.fixture(scope="session")
def baseline():
    with open(BASELINE_PATH, encoding="utf-8") as f:
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
        with open(out, "w", encoding="utf-8") as f:
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
        measure.flash(want)
        b = measure.Board(settle=3.0)
        have, banner = measure.which_track(b)
        if have != want:
            b.close()
            pytest.fail(f"flashed track {want} but the board reports {have!r}")

    b.stop()
    b.drain_console(pacing.GLANCE)
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


# ONE TIME BUDGET PER MARKER GROUP, in seconds, and a run is judged
# against the SUM of the budgets of the groups it selected.
#
# A budget protects the per-change loop; it is not a correctness verdict
# and has never caught a code defect. What it has caught, twice, is a
# bench that had stopped being the bench it was - a 240 s probe timeout
# paid twice on mac-bench, and an sshfs mount that made that tier a
# 306-376 s range at one commit. So each number is the SLOWEST bench's
# reproducible figure with a margin: wide enough that hardware never
# trips it, tight enough that a fixed wait of the size already met does,
# on every bench. One number per group rather than one per bench,
# because a red must mean the same thing everywhere.
#
#   gate      360  windows-desk 255-264 s, mac-bench 187-231, linux-x1
#                  137-143 in the container. +36% over the slowest; a
#                  240 s hang fires on all three (377/471/503), one
#                  313 s thermal outlier does not.
#   platform   30  4.3 / 2.3 / 0.5 s natively, nineteen sub-second tests;
#                  only a stuck OS call - ctypes, Mach, SetThreadPriority
#                  - can reach it, and that is timeout-scale.
#   board    None  not re-timed since the container round; no budget
#                  until a second run on the slowest bench exists. None
#                  contributes nothing to a sum, so a board run is judged
#                  on whatever else it selected.
#
# The single 300 s ceiling this replaces judged one number over a mixed
# set and was red on two benches with zero failing tests, which is how
# a budget becomes a number everyone reads past. Owner's ruling on the
# three, 2026-09-20. Change a number deliberately: tests/test_budgets.py
# pins them so a drift is an edit, not an accident.
BUDGET_S = {"gate": 360.0, "platform": 30.0, "board": None}


def group_of(item):
    """Which budget group a collected item belongs to.

    `board` wins over `platform` because a board test that also depends
    on the host's OS branch is paced by the board; everything unmarked is
    the gate, which is the selection docker/run-ci.sh runs.
    """
    if item.get_closest_marker("board"):
        return "board"
    if item.get_closest_marker("platform"):
        return "platform"
    return "gate"


def budget_for(groups):
    """The budget a run is judged against: the sum over the groups it
    selected, or None when none of them carries one."""
    known = [BUDGET_S[g] for g in groups if BUDGET_S.get(g) is not None]
    return sum(known) if known else None


def pytest_sessionstart(session):
    session._due_t0 = time.time()


def pytest_sessionfinish(session, exitstatus):
    """Hold each tier to its budget, enforced not intended.

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
    groups = sorted({group_of(i) for i in getattr(session, "items", ())})
    budget = budget_for(groups)
    if budget is not None:
        elapsed = time.time() - t0
        if elapsed > budget:
            reporter = session.config.pluginmanager.get_plugin(
                "terminalreporter")
            if reporter is not None:
                reporter.write_line(
                    f"the run took {elapsed:.1f}s against a {budget:.0f}s "
                    f"budget for {', '.join(groups)} (issue #86). This "
                    f"protects the per-change loop: if the tier is "
                    f"genuinely this slow now, move work out of it or "
                    f"change the constant in tests/conftest.py "
                    f"deliberately - do not let it drift the way section "
                    f"8 of docs/testing.md once did.", red=True)
            session.exitstatus = 1
    _check_one_instrument(session)


def _check_one_instrument(session):
    """Did any counter read come off printf? Issue #51, and now q3.

    `play_counters()` and `occupancy()` read over the control channel
    and **raise** when there is none. They used to substitute `B` and
    `O` instead, and the substitution was silent: control reads a
    counter in 146 us, the console costs 13.14 ms and 15.40 ms of
    blocked main loop **taken while the sample path is running**, which
    is invariant 8. They are two experiments, not two tolerances of one,
    and a link that dropped mid-suite left a run holding two populations
    with nothing marking the boundary. That cost a whole session once.

    **This is now a tripwire rather than a detector, and that is worth
    saying plainly.** With the fallback deleted nothing in the working
    path increments `console`, so in a healthy tree this hook cannot
    fire. What it catches is the fallback being *reintroduced* - by a
    new helper that scrapes `B` and counts itself as a counter read, or
    by someone restoring the old two-halves shape. It is cheap, it is
    exact, and it fails the run rather than warning, because a warning
    is what this already was: the deleted `_note_fallback()` raised a
    `RuntimeWarning` at the moment it happened and #51 happened anyway.

    A guard that cannot fail is worse than no guard, so this one was
    broken on purpose before it was trusted -
    `test_instrument_guard.py` drives `INSTRUMENT_READS` to each of the
    four states and asserts what this hook does with them, which is the
    only reason to believe the branches below still work now that the
    world stopped producing the input.

    **The `ctlver=0` branch is kept and is now unreachable from this
    codebase.** It described a board that never had a control channel -
    an image built before 2026-08-27, or a track without the opcode -
    for which the console was the only instrument and not a downgrade.
    No track is in that state: all three carry a control channel and
    report ctlver=4. It stays because it costs one branch and it is the
    correct answer if a pre-2026-08-27 image is ever put on a bench.
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


@pytest.fixture(scope="session")
def h7_unit(request):
    """A running H7: its (stream, control) ports, or a skip that names why not (a failure under --require-h7).

    Discovery opens nothing. A unit in the boot loader is a different reason from an absent one and the skip says which, because the remedy
    differs (flash an image, or plug it in).
    """
    import devices
    action, reason = devices.h7_decision(ports.h7_state(), request.config.getoption("--require-h7"))
    if action == "fail":
        pytest.fail(reason)
    if action == "skip":
        pytest.skip(reason)
    return ports.find_h7()
