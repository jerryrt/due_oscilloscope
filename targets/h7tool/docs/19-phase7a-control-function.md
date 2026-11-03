# Phase 7a: the control function (image12a, build 14)

The second CDC function now carries the project's control frames (`DUEC`, version 4, CRC; `lib/due_shared/src/ctl_wire.h`)
on EP4 (bulk 512, DMA) with EP3 (interrupt) present and NAKing. The dispatcher is `fw/ctl_h7.c`: portable C with no registers, its
hooks implemented in the image. It does not use the shared `ctl.c`, which hardcodes the Due's frame version into IDENTITY and
whose tree is not edited for a second target; it reuses the shared header (layout, opcodes, error codes) and `crc32.c`, so there is
one definition of the frame and `host/control.py` parses the replies unchanged.

## Opcodes
| opcode | meaning |
|---|---|
| 0x0001 PING | dev_us, dev_ms, seq (as on the Due) |
| 0x0002 IDENTITY | track `H`, ctl version 4, **frame version 4**, firmware 0.1.0, frame 4096 bytes / 2032 samples, `mck_hz` = 200 MHz (the timer base every rate descends from, nominal), `adc_clock_hz` = 25 MHz (the ADC's effective clock as measured, docs/10; the register says 50), build `h7-build-N` |
| 0x0003 CAPABILITY | the opcodes this build dispatches (the Due's list format) |
| 0x0020 COUNTERS | the Due's 15-word record, filled as: dev_us; bytes_in = playback bytes consumed; produced = acquisition frames; consumed = frames sent; underruns = playback underruns; endtx = frames sent; partial = playback short packets; occ_min = playback minimum occupancy; run_us; the rest 0 (no ISR, spans or drain polls on this target) |
| 0x0040 CONFIG | empty body reads; 16 bytes set: ADC period (>= 80 ticks), DAC period (>= 40), channel mask 1-3, gain code per channel (0-7), coupling bits, DAC zero code. Refused with `CTL_ERR_BUSY` while running, `CTL_ERR_LENGTH` out of range |
| 0x0041 RUN | 1 start / 0 stop acquisition; acquisition runs while DTR is up OR a RUN is set |
| 0x0042 PLAY | cmd 1 (with prime units 1-8) / 0 playback |
| 0x0043 STATUS | 72 bytes: running, playing, timer, channels, both periods and every acquisition and playback counter |
| 0x0044 BOOTLOADER | body: the four bytes `BOOT`. Stops everything, replies u8 1, and 20 ms later restarts into the stock boot loader (image 13 and later). Any other body is LENGTH and does nothing; an image without the path answers OPCODE (image 12) or BUSY (a weak default in the dispatcher) |
A Due answers `CTL_ERR_OPCODE` to the 0x40 range, which is what a host should see. Not implemented here (and so absent from the
capability list): GEN, OCCUPANCY, RATE_TRACE, STREAM_STATS, LOAD, BENCH, TEMP and the heartbeat.

## Tests
- `tests/test_h7_ctl.py` compiles `ctl_h7.c` on the host with stub hooks and drives it with `host/control.py`'s own encoder and decoder:
  identity, capability, counters, config round trip, range and busy, status size, and a bad CRC, version, length, opcode and non-frame
  all refused and never acted on. Removing the CRC check fails one. Without a host C compiler these SKIP; a skip is not a pass.
  It found a real bug on the way: the IDENTITY reply is 42 bytes and only 40 were cleared, so two bytes of stack leaked into the build string.
- `tools/h7_ctl_check.py` on the unit, with the unchanged `Control`: identity, capabilities, counters, config set, refusals, then 2 s of
  acquisition from a control RUN with the stream port's DTR **down** (3,998,976 samples per channel at 2 Msps), config refused while
  running, RUN 0 stops it. All passed on build 14.

## Not covered yet
The host stack: the daemon still cannot start this unit (it needs a console and the Due's VID/PID and rate model), the GUI decodes a
12-bit tag, and `measure.py`'s identity regex accepts only tracks A-C (docs/20, stage 7b). The control channel under load (a control
request while playback and acquisition both run at full rate) is untested.

## Leaving the boot loader is a host command (image 13)

Images up to 12 returned to the boot loader on a timer (`RUN_MS`, 30 minutes on the bench image) so that a fault could not strand the unit.
Image 13 has no timer by default (`RUN_MS` = 0; `-DRUN_MS=n` restores it) and returns when asked: control opcode 0x0044 with the body `BOOT`
(`tools/h7_to_bootloader.py`, no root), or the vendor request OUT 0x7F as before. `tools/h7_flash_wait.sh` tries the control opcode first and
falls back to the vendor request for older images. What no longer protects a bench: a hung image does not come back by itself, and recovering one
is the stock boot-loader enable sequence at the unit. The timer's first visible effect was a unit that stopped answering 30 minutes after a
flash and looked like a crash.

## Image 14: the stream endpoint is stopped and re-armed reliably

Image 13 ended a run by disabling the stream's IN endpoint with a wait that was an iteration count and gave up silently. When the host was not
polling at that instant the disable stayed pending and landed on the next run's first transfer: `ep_busy` stayed set, the unit kept acquiring
and sent nothing (`sent` 0, `lost` climbing), and a start produced no frames. Image 14 quiesces the endpoint against the clock at the end and the
start of a run, flushes its FIFO, and sends a transfer again when it was disabled instead of completing. Measured by alternating the two images,
200 start/stop cycles each, twice: **starts with no frames 15 of 400 on image 13, 1 of 400 on image 14** (Fisher exact p about 0.0002).
Not fixed, and not changed by it: about 1 run in 70 (4 of 400 and 7 of 400, no difference) starts with the previous run's last frame where its
own seq 0 belongs, so a run reads `[30, 1, 2, ...]`; a host flush and a TX FIFO flush did not remove it *(cause not found)*.
