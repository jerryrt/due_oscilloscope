#!/bin/sh
# Flash an image onto a unit that is in the boot loader or running one of our images, then wait for
# the image to enumerate as 1209:0001. A running image of ours is sent back to the boot loader with
# the vendor request OUT 0x7F (images from image11 on); an older image returns on its own timer.
# Usage: h7_flash_wait.sh image.bin
set -e
D=$(dirname "$0"); U=$D/../../../../h7tool_usb_control/scripts
if lsusb -d 1209:0001 >/dev/null 2>&1; then
	sudo -n python3 "$D/h7_usb_probe.py" bootloader >/dev/null 2>&1 || true
fi
for i in $(seq 1 330); do lsusb -d 0483:5720 >/dev/null 2>&1 && break; sleep 1; done
lsusb -d 0483:5720 >/dev/null 2>&1 || { echo "unit never reached the boot loader"; exit 1; }
sleep 3
ok=0
for t in 1 2 3 4 5; do sudo -n python3 "$U/h7_bl_flash.py" "$1" --yes && { ok=1; break; }; sleep 3; done
[ $ok = 1 ] || { echo "flash failed"; exit 1; }
for i in $(seq 1 40); do lsusb -d 1209:0001 >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do ls /dev/ttyACM4 >/dev/null 2>&1 && break; sleep 1; done
echo enumerated
