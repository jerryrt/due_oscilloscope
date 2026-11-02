#!/bin/sh
# Flash a USB-less test image from the stock app, with no key press.
#   stock app --(FC6 0xFF7F=2)--> boot loader --(raw write)--> test image
# The test image must return itself to the boot loader (fw/image2 does).
# Restore stock afterwards with h7_bl_flash.py and the V2.33 file in ../../../h7tool_backup (outside this repo).
set -e
U=$(dirname "$0")/../../../../h7tool_usb_control/scripts
python3 "$U/h7_update.py" "$1" --yes >/dev/null 2>&1 || true   # its final wait times out; expected
for i in $(seq 1 20); do lsblk -o LABEL 2>/dev/null | grep -q H7-TOOL_IAP && break; sleep 1; done
sleep 2
sudo -n python3 "$U/h7_bl_flash.py" "$1" --yes
