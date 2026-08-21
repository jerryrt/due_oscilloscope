#!/usr/bin/env bash
#
# Flash a bare-metal .bin to the Due over the programming port.
#
# The Due enters SAM-BA mode when the programming port is opened at 1200
# baud: the 16U2 sees the baud change and asserts ERASE then RESET. That
# baud rate is a control signal here, not a data rate.
#
# The programming port's CDC belongs to the 16U2, which is not itself
# reset, so the device node survives the touch. Only a short settle is
# needed.
#
# usage: tools/flash.sh [BIN] [PORT]

set -euo pipefail

BIN="${1:-build/baremetal_bringup.bin}"
PORT="${2:-/dev/cu.usbmodem141301}"
BOSSAC="${BOSSAC:-$HOME/Library/Arduino15/packages/arduino/tools/bossac/1.6.1-arduino/bossac}"

[ -f "$BIN" ]     || { echo "no such binary: $BIN" >&2; exit 1; }
[ -x "$BOSSAC" ]  || { echo "bossac not found: $BOSSAC" >&2; exit 1; }
[ -e "$PORT" ]    || { echo "no such port: $PORT" >&2; exit 1; }

echo "==> 1200-baud touch on $PORT (erase + reset)"
python3 - "$PORT" <<'PY'
import fcntl, os, struct, sys, termios, time

dev = sys.argv[1]
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    a = termios.tcgetattr(fd)
    a[4] = a[5] = termios.B1200
    termios.tcsetattr(fd, termios.TCSANOW, a)
    # The baud change alone is not enough. The 16U2 triggers erase+reset
    # on seeing 1200 baud followed by DTR going low, which is what the
    # Arduino tooling does before closing the port.
    fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_DTR))
    time.sleep(0.1)
finally:
    os.close(fd)

# Wait for the node to settle. The programming port CDC belongs to the
# 16U2, which is not itself reset, so it normally persists.
for _ in range(40):
    if os.path.exists(dev):
        break
    time.sleep(0.1)
time.sleep(1.0)
PY

echo "==> bossac: writing $BIN"
"$BOSSAC" -i -d --port="$(basename "$PORT")" -U false -e -w -v -b "$BIN" -R
