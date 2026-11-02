#!/bin/sh
# Flash an image onto a unit that is in (or will return to) the boot loader,
# then wait for the image to enumerate as 1209:0001 and for cdc_acm to bind
# both functions. Usage: h7_flash_wait.sh image.bin
set -e
U=$(dirname "$0")/../../../../h7tool_usb_control/scripts
for i in $(seq 1 330); do lsusb -d 0483:5720 >/dev/null 2>&1 && break; sleep 1; done
sleep 3
for t in 1 2 3; do sudo -n python3 "$U/h7_bl_flash.py" "$1" --yes && break; sleep 3; done
for i in $(seq 1 40); do lsusb -d 1209:0001 >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do [ "$(ls /sys/bus/usb/devices/*/ 2>/dev/null | grep -c ttyACM)" -ge 0 ] && ls /dev/ttyACM4 >/dev/null 2>&1 && break; sleep 1; done
echo enumerated
