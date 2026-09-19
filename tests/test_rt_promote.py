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


def _darwin_qos():
    note = rt.promote()
    lib = ctypes.CDLL(None, use_errno=True)
    try:
        fn = lib.pthread_get_qos_class_np
    except AttributeError:
        try:
            fn = lib.pthread_get_qos_class_self_np
        except AttributeError:
            return note, None
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
        return note, None
    return note, (cls.value if ok else None)


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
            k32.GetPriorityClass(k32.GetCurrentProcess()))


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


@pytest.mark.skipif(not DARWIN, reason="QoS classes are macOS's")
def test_on_macos_a_claimed_qos_class_is_the_one_the_thread_has():
    note, qos = _in_a_thread(_darwin_qos)
    if "qos=user-interactive" not in note:
        pytest.skip(f"no QoS claimed on this host: {note}")
    if qos is None:
        pytest.skip("this libSystem exposes no readable QoS getter")
    assert qos == rt.QOS_CLASS_USER_INTERACTIVE, (
        f"note claims user-interactive and the thread reads 0x{qos:x}")


@pytest.mark.skipif(not WINDOWS, reason="priority classes are Windows'")
def test_on_windows_the_note_matches_the_thread_and_process():
    note, thread_prio, klass = _in_a_thread(_windows_facts)
    if "thread=time-critical" in note:
        assert thread_prio == rt.THREAD_PRIORITY_TIME_CRITICAL, (
            f"note claims time-critical and GetThreadPriority says "
            f"{thread_prio}")
    if "class=0x" in note:
        claimed = int(note.split("class=0x")[1].split(",")[0].strip(), 16)
        assert klass == claimed, (
            f"note claims class 0x{claimed:x} and the process has 0x{klass:x}")
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
