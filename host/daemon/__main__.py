"""Run the daemon.

    python3 -m daemon --fake            # no hardware, for GUI work
    python3 -m daemon --file cap.due    # replay a recording
    python3 -m daemon                   # the real board

Opening the control port resets the board over NRSTB, so the real mode
opens it once, here, and holds it for the daemon's life.

`--file` is the reader for what `record.start` writes. It is a source
like the other two rather than a mode of the front end, so that a
recording is analysed by the same trigger, measurements and export as a
live bench - and so that a bench without a board, or without the board
that took the capture, can still look at it. See `docs/daemon-api.md`.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon import device as devmod            # noqa: E402
from daemon import server as srvmod            # noqa: E402
import pacing


def open_hardware(kind, *, h7_found=None, open_h7=None, open_due=None):
    """The device for `--device`. h7 and due open exactly what they name; auto takes an attached H7 and otherwise the Due.

    The H7 is looked for first and by USB id alone, which opens nothing, so choosing it never touches a Due's ports - the
    daemon owns whichever port it opens and a second process cannot share one. The three callables are the seams a test breaks.
    """
    if h7_found is None:
        import ports
        h7_found = ports.find_h7
    if open_h7 is None:
        from daemon import h7device
        open_h7 = h7device.H7Device.open
    if open_due is None:
        def open_due():
            import measure
            return devmod.BoardDevice(measure.Board(settle=3.0))
    if kind == "due":
        return open_due()
    paths = h7_found()
    if kind == "h7":
        return open_h7(paths)                 # refuses with its own message when paths is None
    return open_h7(paths) if paths else open_due()


def main(argv=None):
    ap = argparse.ArgumentParser(description="due_oscilloscope daemon")
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address; default all interfaces, which "
                         "assumes a trusted network")
    ap.add_argument("--port", type=int, default=srvmod.DEFAULT_PORT)
    ap.add_argument("--fake", action="store_true",
                    help="serve synthetic frames instead of a board")
    ap.add_argument("--fake-h7", action="store_true",
                    help="serve a simulated H7 target (the real control dispatcher "
                         "compiled for the host; needs a host C compiler)")
    ap.add_argument("--device", choices=("auto", "due", "h7"), default="auto",
                    help="which hardware to open: an attached H7 target, a Due, or (auto) the H7 if one is attached "
                         "and the Due otherwise")
    ap.add_argument("--pace", action="store_true",
                    help="with --fake, produce frames at the claimed rate")
    ap.add_argument("--file", metavar="PATH",
                    help="replay a recording written by record.start "
                         "instead of talking to a board")
    ap.add_argument("--replay-loop", action="store_true",
                    help="with --file, start the recording again at its end")
    ap.add_argument("--replay-speed", type=float, default=1.0,
                    help="with --file, multiply the recorded frame timing; "
                         "1.0 replays at the rate it was captured at")
    ap.add_argument("--replay-fast", action="store_true",
                    help="with --file, hand frames over as fast as they are "
                         "read. Quick for a scripted client; wrong for the "
                         "GUI, whose ring is sized in seconds")
    ap.add_argument("--gc", action="store_true",
                    help="leave the cycle collector running; by default the "
                         "daemon disables it, since the streaming path "
                         "makes no cycles and refcounting frees promptly")
    args = ap.parse_args(argv)

    if sum(map(bool, (args.fake, args.file, args.fake_h7))) > 1:
        ap.error("--fake, --fake-h7 and --file are different sources; pick one")

    if args.fake_h7:
        from daemon import h7sim
        if not h7sim.available():
            print("--fake-h7 needs a host C compiler (gcc or cc) to build the simulated unit", file=sys.stderr)
            return 2
        dev = h7sim.make_sim_device(pace=True)
    elif args.fake:
        dev = devmod.FakeDevice(pace=args.pace)
    elif args.file:
        # Constructed here rather than lazily, so a missing file, an
        # unreadable sidecar or a frame geometry this build cannot read
        # is reported before anything binds a port and a client
        # connects to a daemon that will never produce a frame.
        try:
            dev = devmod.FileDevice(args.file, pace=not args.replay_fast,
                                    loop=args.replay_loop,
                                    speed=args.replay_speed)
        except devmod.DeviceError as e:
            # Every refusal from FileDevice already names the file,
            # so prefixing it again would say the path three times.
            print(str(e), file=sys.stderr)
            return 2
    else:
        try:
            dev = open_hardware(args.device)
        except devmod.DeviceError as e:
            print(str(e), file=sys.stderr)
            return 2

    srv = srvmod.Server(dev, host=args.host, port=args.port,
                        tune_gc=not args.gc).start()
    print(f"daemon on {srv.host}:{srv.port}  device={dev.describe()}")

    def _terminate(signum, frame):
        raise KeyboardInterrupt
    # SIGTERM is how a launcher or a test harness stops a daemon, and by default it ends the process with the device still open:
    # a unit that reads DTR as "start" (the H7) is then left running. Turn it into the Ctrl-C path so the device is closed.
    signal.signal(signal.SIGTERM, _terminate)
    try:
        while True:
            pacing.pause(pacing.SETTLE)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
        try:
            dev.close()
        except Exception as e:                       # noqa: BLE001
            print(f"closing the device: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
