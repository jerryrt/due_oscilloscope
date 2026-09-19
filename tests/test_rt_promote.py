"""`rt.promote()`: the note it returns must be true on this host.

Needs no board. `promote()` reports and never raises, which is right -
a measurement has to run identically with and without the promotion, or
the promotion becomes an unmeasured variable. The cost is that every
failure is silent: a renamed symbol, a wrong ctypes signature or an
early return leaves the thread at normal priority and the run simply
jitters more. This project's most expensive error is a host-side
artifact read as the device's, so the promotion is exactly the kind of
thing that must not be able to lie.

So this does not check that a string comes back. It reads what the OS
actually applied to that thread and holds the note to it. The branch it
can check is this host's own, which is why the module carries the
`platform` marker: the container is always Linux and cannot answer for
Windows or macOS.
"""
import ctypes
import os
import re
import sys
import threading

import pytest

import rt

# The container is always Linux, so this module's answers are the host's
# own. See docs/testing.md.
pytestmark = pytest.mark.platform

LINUX = sys.platform.startswith("linux")
DARWIN = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"


def _in_a_thread(fn):
    """Run `fn` in a fresh thread and return its result.

    Never on the main thread: `promote()` acts on the caller, and a
    pytest process left in the real-time band would outrank whatever it
    runs next. A thread that exits takes its policy with it.
    """
    out = {}

    def run():
        try:
            out["value"] = fn()
        except BaseException as exc:            # reported, not raised here
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=30)
    assert not t.is_alive(), "promote() did not return within 30 s"
    if "error" in out:
        raise out["error"]
    return out["value"]


def _linux_facts():
    note = rt.promote()
    policy = os.sched_getscheduler(0)
    prio = os.sched_getparam(0).sched_priority
    nice = os.getpriority(os.PRIO_PROCESS, 0)
    return note, policy, prio, nice


def _darwin_qos_readback(lib):
    """The thread's QoS class, or `None` where libSystem exposes no getter."""
    try:
        fn = lib.pthread_get_qos_class_np
    except AttributeError:
        try:
            fn = lib.pthread_get_qos_class_self_np
        except AttributeError:
            return None
    cls = ctypes.c_uint()
    rel = ctypes.c_int()
    try:
        fn.restype = ctypes.c_int
        if fn.__name__.endswith("self_np"):
            fn.argtypes = [ctypes.POINTER(ctypes.c_uint),
                           ctypes.POINTER(ctypes.c_int)]
            ok = fn(ctypes.byref(cls), ctypes.byref(rel)) == 0
        else:
            lib.pthread_self.restype = ctypes.c_void_p
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
                           ctypes.POINTER(ctypes.c_int)]
            ok = fn(lib.pthread_self(), ctypes.byref(cls),
                    ctypes.byref(rel)) == 0
    except (AttributeError, OSError):
        return None
    return cls.value if ok else None


def _darwin_band(lib):
    """`thread_policy_get`'s view of this thread's time-constraint policy.

    Returns `(kr, get_default, period_ms, computation_ms, constraint_ms)`,
    the milliseconds converted out of `mach_absolute_time` units by the
    host's own timebase. `get_default` is the field that says whether the
    thread carries a policy of its own: 1 means the kernel handed back the
    default because nothing was ever set on this thread.
    """
    count = ctypes.sizeof(rt._time_constraint) // 4
    lib.pthread_self.restype = ctypes.c_void_p
    lib.pthread_mach_thread_np.argtypes = [ctypes.c_void_p]
    lib.pthread_mach_thread_np.restype = ctypes.c_uint32
    lib.thread_policy_get.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(rt._time_constraint),
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_int)]
    lib.thread_policy_get.restype = ctypes.c_int
    lib.mach_timebase_info.argtypes = [ctypes.POINTER(rt._timebase)]

    tb = rt._timebase()
    lib.mach_timebase_info(ctypes.byref(tb))
    pol = rt._time_constraint()
    cnt = ctypes.c_uint32(count)
    default = ctypes.c_int(0)
    kr = lib.thread_policy_get(
        lib.pthread_mach_thread_np(lib.pthread_self()),
        rt.THREAD_TIME_CONSTRAINT_POLICY,
        ctypes.byref(pol), ctypes.byref(cnt), ctypes.byref(default))

    def ms(units):
        return units * tb.numer / tb.denom / 1e6

    return (kr, default.value,
            ms(pol.period), ms(pol.computation), ms(pol.constraint))


def _darwin_facts():
    """What the QoS call and the band each do, in the order `promote()` does.

    `qos_alone` is read after setting the class and before the band, which
    is the only point at which it can be observed at all - see the test.
    """
    lib = ctypes.CDLL(None, use_errno=True)
    before = _darwin_band(lib)
    try:
        fn = lib.pthread_set_qos_class_self_np
        fn.argtypes = [ctypes.c_uint, ctypes.c_int]
        fn.restype = ctypes.c_int
        qos_alone = (_darwin_qos_readback(lib)
                     if fn(rt.QOS_CLASS_USER_INTERACTIVE, 0) == 0 else None)
    except (AttributeError, OSError):
        qos_alone = None
    note = rt.promote()
    return note, before, _darwin_band(lib), qos_alone, _darwin_qos_readback(lib)


def _windows_timer_100ns():
    """The timer resolution in force, in 100 ns units.

    `timeBeginPeriod(1)` is the part of the Windows note that neither
    `GetThreadPriority` nor `GetPriorityClass` can see, and `rt.py` calls
    it the part that matters here: the default 15.6 ms tick is longer
    than the playback ring holds at the higher rates.
    `NtQueryTimerResolution` reports what the process is actually
    running under.
    """
    ntdll = ctypes.WinDLL("ntdll")
    minimum = ctypes.c_ulong()
    maximum = ctypes.c_ulong()
    current = ctypes.c_ulong()
    status = ntdll.NtQueryTimerResolution(ctypes.byref(minimum),
                                          ctypes.byref(maximum),
                                          ctypes.byref(current))
    assert status == 0, (
        f"NtQueryTimerResolution failed, 0x{status & 0xffffffff:08x}")
    return current.value


def _windows_facts():
    note = rt.promote()
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentThread.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetThreadPriority.argtypes = [wintypes.HANDLE]
    k32.GetThreadPriority.restype = ctypes.c_int
    k32.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k32.GetPriorityClass.restype = wintypes.DWORD
    return (note,
            k32.GetThreadPriority(k32.GetCurrentThread()),
            k32.GetPriorityClass(k32.GetCurrentProcess()),
            _windows_timer_100ns())


def test_the_note_is_never_empty():
    note = _in_a_thread(rt.promote)
    assert isinstance(note, str) and note.strip(), repr(note)


@pytest.mark.skipif(not LINUX, reason="SCHED_FIFO and nice are Linux's here")
def test_on_linux_the_note_matches_what_the_scheduler_applied():
    note, policy, prio, nice = _in_a_thread(_linux_facts)

    if "sched=fifo:" in note:
        claimed = int(note.split("sched=fifo:")[1].split()[0].rstrip(","))
        assert policy == os.SCHED_FIFO, (
            f"note claims {note!r} but sched_getscheduler says {policy}")
        assert prio == claimed, (
            f"note claims priority {claimed} and the thread has {prio}")
    elif "nice=-10" in note:
        assert policy == os.SCHED_OTHER, (
            f"note claims a nice fallback and the policy is {policy}")
        assert nice == -10, f"note claims nice=-10 and the thread has {nice}"
    else:
        assert note.startswith("no promotion"), note
        assert policy == os.SCHED_OTHER, (
            f"note claims nothing was applied and the policy is {policy}")
        assert nice >= 0, (
            f"note claims nothing was applied and nice is {nice}")


@pytest.mark.skipif(not DARWIN, reason="the Mach band is macOS's")
def test_on_macos_the_note_matches_the_band_the_kernel_applied():
    """The band is what `promote()` is for, and it is what is readable.

    **A QoS class is true at the moment it is set and unobservable once
    the band is applied**, so the note's two halves cannot both be read
    back at the end. Measured on mac-bench: setting the class alone reads
    0x21, and after `thread_policy_set` the same thread reads 0x0 - the
    time-constraint policy replaces the classification rather than
    failing. Asserting the QoS class after `promote()` therefore fails on
    a host where the promotion worked perfectly, which is why this reads
    the band instead. Do not "fix" it back.

    `computation` is not held to the request: it is asked for as 0.5 ms
    here and the kernel reports 1.25 ms. Recorded as measured and
    unexplained; the assertion is only that the kernel did not give back
    less than was asked for.
    """
    note, before, after, qos_alone, qos_after = _in_a_thread(_darwin_facts)

    if qos_alone is not None:
        assert qos_alone == rt.QOS_CLASS_USER_INTERACTIVE, (
            f"pthread_set_qos_class_self_np returned 0 and the thread "
            f"reads 0x{qos_alone:x} before any band is applied")

    if "time-constraint" not in note:
        assert note.startswith("no promotion") or "qos=" in note, note
        assert after[1] == 1, (
            f"note claims no band and thread_policy_get says the thread "
            f"carries one: {after}")
        return

    claimed = [float(v) for v in
               note.split("time-constraint ")[1].split(" ms")[0].split("/")]
    kr, default, period, computation, constraint = after

    assert before[1] == 1, (
        f"this thread already carried a time-constraint policy before "
        f"promote(), so the test cannot tell what promote() did: {before}")
    assert kr == 0, f"thread_policy_get failed with {kr} after promote()"
    assert default == 0, (
        f"note claims {note!r} and thread_policy_get returns the default "
        f"policy, so nothing was applied to this thread")
    assert period == pytest.approx(claimed[0], rel=1e-3), (
        f"note claims period {claimed[0]} ms and the kernel holds {period}")
    assert constraint == pytest.approx(claimed[2], rel=1e-3), (
        f"note claims constraint {claimed[2]} ms and the kernel holds "
        f"{constraint}")
    assert computation >= claimed[1] * (1 - 1e-3), (
        f"note claims computation {claimed[1]} ms and the kernel holds "
        f"{computation}, which is less than was asked for")
    assert qos_after != rt.QOS_CLASS_USER_INTERACTIVE or qos_after is None, (
        f"the band no longer clears the QoS class on this macOS: the "
        f"thread still reads 0x{qos_after:x}. That is not a defect - it "
        f"is the premise of this test changing, and the docstring and "
        f"docs/testing.md have to change with it")


@pytest.mark.skipif(not WINDOWS, reason="priority classes are Windows'")
def test_on_windows_the_note_matches_the_thread_and_process():
    """Every claim in the note, against what Windows applied.

    The timer claim is the one the two priority calls cannot reach, and
    it is checked for what it says rather than for what caused it:
    `timeBeginPeriod` is process-wide and any program on the host can
    raise the resolution, so this asserts the process runs at least as
    fine as the note claims. On `windows-desk` the resolution reads
    10,000 (1.0000 ms) both before and after `promote()`, so attributing
    it to this call would be a claim the measurement does not support.

    The note is also honest about a privilege it did not get:
    `rt.py` asks for `REALTIME_PRIORITY_CLASS` (0x100) and reports
    `class=0x80`, which is `HIGH_PRIORITY_CLASS` - Windows downgrades it
    without `SeIncreaseBasePriorityPrivilege`, and the note carries what
    `GetPriorityClass` returns rather than what was asked for.
    """
    note, thread_prio, klass, timer_100ns = _in_a_thread(_windows_facts)
    if "thread=time-critical" in note:
        assert thread_prio == rt.THREAD_PRIORITY_TIME_CRITICAL, (
            f"note claims time-critical and GetThreadPriority says "
            f"{thread_prio}")
    if "class=0x" in note:
        claimed = int(note.split("class=0x")[1].split(",")[0].strip(), 16)
        assert klass == claimed, (
            f"note claims class 0x{claimed:x} and the process has 0x{klass:x}")
    if "timer=" in note:
        m = re.search(r"timer=([0-9]*\.?[0-9]+)ms", note)
        assert m, (
            f"the note claims a timer resolution it does not state: {note!r}")
        claimed_ms = float(m.group(1))
        assert timer_100ns <= claimed_ms * 10_000, (
            f"note claims timer={claimed_ms}ms and the process is running "
            f"at {timer_100ns / 10_000:.4f} ms "
            f"(NtQueryTimerResolution: {timer_100ns})")
    if note.startswith("no promotion"):
        assert thread_prio != rt.THREAD_PRIORITY_TIME_CRITICAL, note


@pytest.mark.skipif(not LINUX, reason="reads the main thread's own policy")
def test_promotion_stays_on_the_thread_that_asked():
    """Per-thread is the whole design: the feeder is promoted and the
    process is not. Windows is excluded because SetPriorityClass is
    process-wide there by construction, and the note says so."""
    before = os.sched_getscheduler(0)
    _in_a_thread(rt.promote)
    assert os.sched_getscheduler(0) == before, (
        "promote() changed the calling thread's policy from another thread")


def test_an_unknown_platform_is_reported_and_nothing_is_attempted(monkeypatch):
    """The fall-through branch, checkable on every bench."""
    monkeypatch.setattr(sys, "platform", "sunos5")
    note = _in_a_thread(rt.promote)
    assert note == "no promotion (unknown platform sunos5)", note
