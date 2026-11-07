#!/usr/bin/env python3
"""Passively log the Due's programming-port console until Ctrl-C.

For idle periods, so a HardFault register dump is not lost for want of a
reader. Opens with DTR left alone (opening with it toggled resets the
board) and never writes to the port.

WARNING: do NOT run this at the same time as a measurement tool. Two
readers on one tty split the bytes between them and both lose data.

    python3 tools/uart_log.py [--dev PATH] [--out console.log]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import ports            # noqa: E402
import transport        # noqa: E402

WARNING = ("WARNING: do not run alongside a measurement tool - two readers "
           "on one tty split the bytes between them.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dev", help="programming port (default: VID/PID 2341:003D)")
    ap.add_argument("--out", default="console.log")
    ap.add_argument("--max-bytes", type=int, default=transport.CONSOLE_LOG_MAX)
    a = ap.parse_args(argv)
    print(WARNING, file=sys.stderr)
    dev = a.dev or ports.find_all_ports()[0]
    if not dev:
        print("no programming port (2341:003D) found", file=sys.stderr)
        return 1
    log = transport.RotatingLog(a.out, a.max_bytes)
    if log.dead:
        return 1
    port = transport.open_raw(dev, 115200, dtr=False)
    print(f"logging {dev} -> {a.out} (Ctrl-C to stop)", file=sys.stderr)
    try:
        while not log.dead:
            if transport.wait_any([port], 0.5):
                log.write(port.read(4096))
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
