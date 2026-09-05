"""Run the front end.

    python -m gui                     # connect to a daemon already running
    python -m gui --spawn-fake        # start one with no hardware, and connect
    python -m gui --spawn-file cap.due   # replay a recording, and connect

The fake and file sources import nothing outside stdlib, so the
spawning forms run the daemon on this same interpreter - no second
environment to install for a demo.

Which source the daemon serves is the daemon's argument rather than a
control in this window, because the daemon owns the device and a front
end that could swap it underneath a running recorder would be the one
thing `docs/frontend.md` says the split exists to prevent. Replaying a
capture is therefore a daemon you start, exactly like a board is.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from PySide6 import QtWidgets

from .app import MainWindow


def main(argv=None):
    ap = argparse.ArgumentParser(description="due_oscilloscope front end")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=45454)
    ap.add_argument("--spawn-fake", action="store_true",
                    help="start a synthetic daemon and connect to it")
    ap.add_argument("--spawn-file", metavar="PATH",
                    help="start a daemon replaying this recording, and "
                         "connect to it")
    ap.add_argument("--replay-loop", action="store_true",
                    help="with --spawn-file, start the recording again "
                         "at its end")
    args = ap.parse_args(argv)

    if args.spawn_fake and args.spawn_file:
        ap.error("--spawn-fake and --spawn-file are two different sources; "
                 "pick one")

    child = None
    argv_daemon = None
    if args.spawn_fake:
        argv_daemon = ["--fake", "--pace"]
    elif args.spawn_file:
        # An absolute path, because the daemon is started with its cwd
        # in host/ and a relative one would resolve somewhere the user
        # was not looking.
        argv_daemon = ["--file", os.path.abspath(args.spawn_file)]
        if args.replay_loop:
            argv_daemon.append("--replay-loop")
    if argv_daemon is not None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        child = subprocess.Popen(
            [sys.executable, "-m", "daemon"] + argv_daemon +
            ["--host", args.host, "--port", str(args.port)],
            cwd=os.path.join(root, "host"))
        time.sleep(0.8)
        if child.poll() is not None:
            # The daemon refuses an unreadable recording before it binds
            # a port, and its message is the useful one. Saying "could
            # not reach a daemon" over the top of it would hide the
            # reason behind the symptom.
            print(f"daemon exited with {child.returncode}; not connecting",
                  file=sys.stderr)
            return child.returncode

    app = QtWidgets.QApplication(sys.argv[:1])
    win = MainWindow(host=args.host, port=args.port)
    win.show()
    win.connect_to_daemon()
    try:
        return app.exec()
    finally:
        if child is not None:
            child.terminate()
            child.wait(5)


if __name__ == "__main__":
    sys.exit(main())
