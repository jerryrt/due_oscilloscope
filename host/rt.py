#!/usr/bin/env python3
"""
Real-time scheduling for time-sensitive I/O threads on macOS.

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
import sys

QOS_CLASS_USER_INTERACTIVE = 0x21
THREAD_TIME_CONSTRAINT_POLICY = 2


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
    if sys.platform != "darwin":
        return "no promotion (not macOS)"

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
