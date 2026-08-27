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
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon import device as devmod            # noqa: E402
from daemon import server as srvmod            # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="due_oscilloscope daemon")
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address; default all interfaces, which "
                         "assumes a trusted network")
    ap.add_argument("--port", type=int, default=srvmod.DEFAULT_PORT)
    ap.add_argument("--fake", action="store_true",
                    help="serve synthetic frames instead of a board")
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

    if args.fake and args.file:
        ap.error("--fake and --file are two different sources; pick one")

    if args.fake:
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
        import measure
        board = measure.Board(settle=3.0)
        dev = devmod.BoardDevice(board)

    srv = srvmod.Server(dev, host=args.host, port=args.port,
                        tune_gc=not args.gc).start()
    print(f"daemon on {srv.host}:{srv.port}  device={dev.describe()}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
