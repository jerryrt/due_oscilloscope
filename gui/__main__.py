"""Run the front end.

    python -m gui                     # connect to a daemon already running
    python -m gui --spawn-fake        # start one with no hardware, and connect

The daemon is stdlib only, so the second form runs it on this same
interpreter - no second environment to install for a demo.
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
    args = ap.parse_args(argv)

    child = None
    if args.spawn_fake:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        child = subprocess.Popen(
            [sys.executable, "-m", "daemon", "--fake", "--pace",
             "--host", args.host, "--port", str(args.port)],
            cwd=os.path.join(root, "host"))
        time.sleep(0.8)

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
