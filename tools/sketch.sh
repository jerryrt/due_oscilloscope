#!/usr/bin/env bash
#
# Build Track A with the build properties it cannot run without.
#
# Two of them, and each is silent when it is missing:
#
#   build.f_cpu=78000000L   MCK is 78 MHz here, not the 84 boards.txt
#                           declares. micros() divides by this, so a
#                           wrong value makes every measured rate wrong
#                           by 7.7% and nothing complains.
#
#   build.ldscript=...      linker/arduino_due_x_sram1.ld, which pins
#                           the ADC capture ring to SRAM bank 1. Without
#                           it the ring lands in .bss in bank 0 and
#                           contends with the USB DMA for the same bus
#                           matrix slave; it still links and still runs.
#
# platform.txt links with "-T{build.variant.path}/{build.ldscript}", so
# the script path is resolved relative to the *installed variant
# directory* rather than to the sketch or the repository. That is why
# the path is computed here instead of written down: it is a chain of
# "../" out of ~/Library/Arduino15 and back, and it is different on
# every machine.
#
# usage: tools/sketch.sh [compile|upload] [PORT]
#        tools/sketch.sh                      # compile

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKETCH="$REPO/sketches/bringup"
FQBN="arduino:sam:arduino_due_x_dbg"
ACTION="${1:-compile}"
shift || true

if [ "$ACTION" = "upload" ]; then
	PORT="${1:-$(python3 "$REPO/host/ports.py" | awk '/control/{print $3}')}"
	exec arduino-cli upload --fqbn "$FQBN" -p "$PORT" "$SKETCH"
fi

# The variant directory arduino-cli will actually use, asked for rather
# than assumed: it moves with the installed core version.
VARIANT="$(arduino-cli board details --fqbn "$FQBN" --show-properties \
           | sed -n 's/^build\.variant\.path=//p' | tail -1)"
if [ -z "$VARIANT" ]; then
	echo "tools/sketch.sh: could not read build.variant.path for $FQBN" >&2
	exit 1
fi

LDSCRIPT="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
            "$REPO/linker/arduino_due_x_sram1.ld" "$VARIANT")"

exec arduino-cli compile --fqbn "$FQBN" \
	--build-property build.f_cpu=78000000L \
	--build-property "build.ldscript=$LDSCRIPT" \
	"$@" "$SKETCH"
