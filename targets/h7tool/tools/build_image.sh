#!/bin/sh
# Build one bring-up image: tools/build_image.sh fw/image4 image4a
# Host arm-none-eabi-gcc (the pilot images were never container builds);
# the compiler version is printed so the log carries it. Output is checked
# by check_image.py before it may be flashed.
set -e
D=$1; N=$2; shift 2
arm-none-eabi-gcc --version | head -1
arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -Os -Wall -Wextra -ffreestanding -nostdlib \
	-T "$D/link.ld" "$@" -Wl,--gc-sections -Wl,-Map,"$D/$N.map" -o "$D/$N.elf" "$D/main.c"
arm-none-eabi-objcopy -O binary "$D/$N.elf" "$D/$N.bin"
python3 "$(dirname "$0")/check_image.py" "$D/$N.bin"
