#!/usr/bin/env python3
"""
Real-time scheduling for time-sensitive I/O threads.

Linux offers SCHED_FIFO and Windows a real-time priority class; the
macOS equivalents are per-thread and two-layered. The QoS class keeps a
thread out of timer coalescing and background demotion, and the Mach
THREAD_TIME_CONSTRAINT policy is the actual real-time band - the one
CoreAudio's I/O threads run in - which tells the scheduler this thread
needs `computation` time out of every `period`, finished within
`constraint`. Neither needs privileges, and ctypes keeps this
stdlib-only, which the host tools require.

Failure is reported, never raised: a measurement must run identically
with and without the promotion, or the promotion itself becomes an
unmeasured variable. Callers print what actually stuck.
"""

import ctypes
import os
import sys

QOS_CLASS_USER_INTERACTIVE = 0x21
THREAD_TIME_CONSTRAINT_POLICY = 2

REALTIME_PRIORITY_CLASS = 0x00000100
THREAD_PRIORITY_TIME_CRITICAL = 15

# Linux real-time priority. Low in the RT band on purpose: this thread
# tops up a queue every few milliseconds and must not outrank the kernel
# threads that actually move the USB traffic it depends on.
LINUX_FIFO_PRIORITY = 10


def _promote_linux():
    """SCHED_FIFO on the calling thread.

    The finest-grained of the three. os.sched_setscheduler(0, ...) acts
    on the calling *thread* - Linux schedules tasks, not processes - so
    this promotes the feeder without touching anything else, which is
    what macOS's per-thread time-constraint policy also does and what
    Windows cannot express.

    Needs CAP_SYS_NICE, or an rtprio limit in limits.conf. Refusal is
    reported rather than raised, like every other path here: a
    measurement must run identically with and without the promotion, or
    the promotion becomes an unmeasured variable. Falling back to a
    negative nice value is still worth having - it will not meet a
    deadline but it does keep the thread off the back of the runqueue.

    Exercised under WSL2 (kernel 5.15), both branches: unprivileged it
    refuses and degrades, privileged it returns sched=fifo:10 with
    sched_getscheduler reporting 1. **Never run on a native Linux host,
    and never with a board attached** - WSL2 has no native USB, so
    nothing here says what the promotion is worth in the only place it
    matters, which is holding a feed schedule against a real device.
    Native Linux is tier 1 deferred; treat its first run as bring-up.
    """
    try:
        param = os.sched_param(LINUX_FIFO_PRIORITY)
        os.sched_setscheduler(0, os.SCHED_FIFO, param)
        return f"sched=fifo:{LINUX_FIFO_PRIORITY}"
    except (AttributeError, OSError) as exc:
        # Bind the reason to a name of its own: Python unbinds the
        # `except ... as` variable when the block ends, so reporting it
        # from the fallback below would raise NameError on exactly the
        # path that is meant to degrade gracefully.
        why = exc

    try:
        os.nice(-10)
        return f"no rt ({why}); nice=-10"
    except OSError:
        return (f"no promotion ({why}); grant CAP_SYS_NICE or set an "
                f"rtprio limit to use SCHED_FIFO")


def _promote_windows():
    """Raise the process class and the calling thread, and ask for a
    1 ms timer.

    REALTIME_PRIORITY_CLASS is downgraded to HIGH without
    SeIncreaseBasePriorityPrivilege, which is the usual case and is not
    an error worth failing on. The default scheduler tick is 15.6 ms -
    longer than the playback ring holds at the higher rates - so
    timeBeginPeriod(1) matters more here than the priority does.

    **argtypes are not optional.** ctypes defaults every return to
    c_int, which truncates the 64-bit HANDLE from GetCurrentProcess;
    without these the calls fail silently and return success-looking
    zeros. That cost a measurement that read as "priority makes no
    difference" when nothing had been applied at all.

    Measured on Windows 11 against this board: promotion changes the
    playback underrun counts by less than run-to-run noise. It is here
    for parity and for hosts that need it, not because it fixed
    anything.
    """
    import ctypes
    from ctypes import wintypes

    got = []
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentThread.restype = wintypes.HANDLE
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.SetPriorityClass.restype = wintypes.BOOL
        k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k32.SetThreadPriority.restype = wintypes.BOOL
        k32.GetPriorityClass.argtypes = [wintypes.HANDLE]
        k32.GetPriorityClass.restype = wintypes.DWORD

        proc = k32.GetCurrentProcess()
        if k32.SetPriorityClass(proc, REALTIME_PRIORITY_CLASS):
            got.append("class=0x%x" % k32.GetPriorityClass(proc))
        if k32.SetThreadPriority(k32.GetCurrentThread(),
                                 THREAD_PRIORITY_TIME_CRITICAL):
            got.append("thread=time-critical")
    except (OSError, AttributeError) as e:
        return f"no promotion ({e})"

    try:
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
        got.append("timer=1ms")
    except (OSError, AttributeError):
        pass

    return ", ".join(got) if got else "no promotion (all calls refused)"


class _timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


class _time_constraint(ctypes.Structure):
    _fields_ = [("period", ctypes.c_uint32),
                ("computation", ctypes.c_uint32),
                ("constraint", ctypes.c_uint32),
                ("preemptible", ctypes.c_int)]


def promote(period_ms=5.0, computation_ms=0.5, constraint_ms=2.5):
    """
    Promote the calling thread. Returns a string describing what was
    actually applied, for the caller to report next to its results.

    The defaults fit the streaming loops here: a writer that must top up
    the kernel queue every few milliseconds with well under a
    millisecond of actual work.
    """
    if sys.platform == "win32":
        return _promote_windows()
    if sys.platform.startswith("linux"):
        return _promote_linux()
    if sys.platform != "darwin":
        return f"no promotion (unknown platform {sys.platform})"

    got = []
    lib = ctypes.CDLL(None, use_errno=True)

    try:
        fn = lib.pthread_set_qos_class_self_np
        fn.argtypes = [ctypes.c_uint, ctypes.c_int]
        fn.restype = ctypes.c_int
        if fn(QOS_CLASS_USER_INTERACTIVE, 0) == 0:
            got.append("qos=user-interactive")
    except AttributeError:
        pass

    try:
        lib.mach_timebase_info.argtypes = [ctypes.POINTER(_timebase)]
        lib.pthread_self.restype = ctypes.c_void_p
        lib.pthread_mach_thread_np.argtypes = [ctypes.c_void_p]
        lib.pthread_mach_thread_np.restype = ctypes.c_uint32
        lib.thread_policy_set.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32,
            ctypes.POINTER(_time_constraint), ctypes.c_uint32]
        lib.thread_policy_set.restype = ctypes.c_int

        tb = _timebase()
        lib.mach_timebase_info(ctypes.byref(tb))

        def abs_units(ms):
            # mach_absolute_time units: ns * denom / numer
            return int(ms * 1e6 * tb.denom / tb.numer)

        pol = _time_constraint(abs_units(period_ms),
                               abs_units(computation_ms),
                               abs_units(constraint_ms), 1)
        port = lib.pthread_mach_thread_np(lib.pthread_self())
        kr = lib.thread_policy_set(port, THREAD_TIME_CONSTRAINT_POLICY,
                                   ctypes.byref(pol),
                                   ctypes.sizeof(pol) // 4)
        if kr == 0:
            got.append(f"time-constraint {period_ms:g}/{computation_ms:g}"
                       f"/{constraint_ms:g} ms")
    except AttributeError:
        pass

    return ", ".join(got) if got else "no promotion available"


if __name__ == "__main__":
    print(promote())
