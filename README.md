# h7tool_baremetal - pilot: our own bare-metal firmware on the H7-TOOL

Pilot project, kept beside (not inside) `due_oscilloscope`. Goal: build, flash,
identify and replace our own image on the H7-TOOL, with **no new features**.
The stock boot loader (v2.06, 0x08000000..0x0801FFFF) is never touched.

Procedures, memory map and recovery: `../h7tool_usb_control/14-firmware-update-procedures.md`.
Backups of stock firmware: `../h7tool_backup/`.

## Rules
- Never write below 0x08020000. Image <= 1,310,720 bytes, linked at 0x08020000.
- Reserve DTCM word 0x20000000 (boot request). No SWD probe: recovery is S/OK held at plug-in.
- Do not change option bytes / read-out protection. Do not touch eMMC, QSPI or the 250M module's RP2040.
- Mark anything not read from a document or measured as *(check)*.
- `reference/` is a local copy of the public armfly V1.49 source (MIT, 2021), not committed.
- The H7 is the Due session's voltage reference. Tell that session before it is flashed and after stock is restored.

## Layout
- `docs/`      inventory and findings
- `scripts/`   host-side tools (image checker, wrappers around ../h7tool_usb_control/scripts)
- `reference/` public source copy (ignored)
