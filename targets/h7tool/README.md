# H7-TOOL target - our own bare-metal firmware on the H7-TOOL

A hardware *target* of this repository, not a fourth Due track: different chip,
board and wire format (frame version 4, `lib/wire/frame16.h`). It began as a
pilot repo (`h7tool_baremetal`) whose history was joined here. The pilot goal
(build, flash, identify and replace our own image) is done; the scope work
follows the phases in `docs/06-plan.md`.
The stock boot loader (v2.06, 0x08000000..0x0801FFFF) is never touched.

Procedures, memory map and recovery: `../../../h7tool_usb_control/14-firmware-update-procedures.md`.
Backups of stock firmware: `../../../h7tool_backup/`.

## Rules
- Never write below 0x08020000. Image <= 1,310,720 bytes, linked at 0x08020000.
- Reserve DTCM word 0x20000000 (boot request). No SWD probe: recovery is S/OK held at plug-in.
- Do not change option bytes / read-out protection. Do not touch eMMC or QSPI. The 250M module's RP2040 is read-only to us (its flash is backed up and a restore file exists, `docs/24`); writing it needs the owner's decision.
- Mark anything not read from a document or measured as *(check)*.
- `reference/` is a local copy of the public armfly V1.49 source (MIT, 2021), not committed.
- The sibling folders `h7tool_usb_control`, `h7tool_backup` and `h7tool_docs` live beside the repo, outside it.

## Layout
- `docs/`      inventory and findings
- `tools/`   host-side tools (image checker, wrappers around ../../../h7tool_usb_control/scripts)
- `reference/` public source copy (ignored)
