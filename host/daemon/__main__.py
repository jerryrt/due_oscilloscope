"""Run the daemon.

    python3 -m daemon --fake            # no hardware, for GUI work
    python3 -m daemon                   # the real board

Opening the control port resets the board over NRSTB, so the real mode
opens it once, here, and holds it for the daemon's life.
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
    ap.add_argument("--gc", action="store_true",
                    help="leave the cycle collector running; by default the "
                         "daemon disables it, since the streaming path "
                         "makes no cycles and refcounting frees promptly")
    args = ap.parse_args(argv)

    if args.fake:
        dev = devmod.FakeDevice(pace=args.pace)
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
