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

## Starting and stopping the stream: three faults, and where each belongs

A run that is started and stopped over the control channel, many times, showed two faults that single runs hid (about 1 start in 60 each), and fixing the first exposed a third. They were
first worked around and then traced to their causes with the unit's own registers; neither workaround is in the code.

**1. The run boundary is the host's, as it is for the Due.** The first frame of a run was sometimes a frame of the previous run (`[20, 1, 2, ...]`,
seq 0 missing). The unit's own send log showed it sent seq 0 first; the framer log showed a complete frame with the old header and device
timestamp, and the next run's magic `DUE0` inside it at offset 512. A unit may stop in the middle of a frame - the Due's stop aborts the frame in
flight on purpose (`stream_core_stop`, a bounded abort rather than a wait on a peer, invariant 7) - and the packet that reached the host can wait in the
kernel's read path until the next run's first bytes complete it. The Due's device never relies on a clean stop: `BoardDevice.start` opens the port afresh
and `drain_until_quiet`s before it commands the stream, with the shared reader held off until that is done. `H7Device` kept its port open for the daemon's
lifetime and drained nothing. It now does what the Due does: `SerialStream.reopen_and_drain` (a fresh port, then everything discarded until
`pacing.SILENCE` of quiet), the reader gated while it runs. Daemon-free, with the pipe left undrained, 600 of 600 starts were clean, which put the fault in
the host's run boundary. With the new boundary 0 stale first frames in 2,970 starts (image 14 and 17 together); before it, 4 of 400 on image 13 and 7 of 400 on image 14 in alternating runs.

**2. An IN-endpoint disable must not be written to an idle endpoint (firmware).** A start sometimes produced no frames: the unit acquired
(`frames` rising) and sent nothing (`sent` 0) with `DIEPCTL2` showing EPENA **and** EPDIS set, IN tokens arriving into an empty FIFO and a full transfer armed.
The stop path checked EPENA once, waited, then wrote EPDIS. A transfer that completed on its own in between had already cleared EPENA, and EPDIS written to an
idle endpoint is never cleared by the core, so the next transfer was armed with both set. Image 17 uses the core's procedure (Global IN NAK, wait for
GINAKEFF, look at EPENA again - nothing can complete now - EPDIS only if still set, wait for EPDISD, release the NAK), every wait against the clock and every
expiry counted. The race is visible in the counters: of the first 440 stops, 65 found a transfer in flight and 10 of those had finished by themselves before the disable
(2.1 % over the final 1,100 stops: 256 had a transfer in flight, 23 of those finished first, the rate of the stuck starts); no wait expired and no transfer was aborted. Starts with no frames: **0 in 1,100 on image 17**, against 11 in 990 on image 14 with the same host boundary and 15 in 400 on image 13 with the old one.
**3. Bulk OUT must be drained when no playback owns it (firmware).** The new run boundary closes the stream port at every start, and after a loop run the second
start never returned: the daemon's thread sat in `close()`. The host's write queue still held playback bytes, `play_stop` had disabled the OUT endpoint and nothing
re-armed it, so the unit took no OUT data and the close waited for a drain that could not come. This is the rule CLAUDE.md states for the Due - "a CDC device must
keep draining bulk OUT even when nothing uses it" - which the H7 image did not follow. Image 17 re-arms EP2 OUT on the unused play ring whenever playback is not
running and discards what arrives (one flag test per pass, no loop; `out_idle_units` counts it: 1,625 units over the eight real-unit runs that followed), and the OUT
endpoint is disabled by the same procedure as the IN one, since it has the same latent flaw and the drain keeps a transfer armed. 240 alternating loop and
capture starts: median latency 0.41 s, max 0.43 s, no failure; the gate asserts every start returns within 3 s.

Image 14 (committed) was a step on the way - a quiesce that still wrote EPDIS unconditionally - and is superseded; images 15 (a trace image) and 16 (a wait for the
frame in flight, which the Due deliberately does not do) were not kept. Image 17 is the one to flash.

How it was found, because the order matters: a count of failures per image proved nothing (rates swung from 0 to 18 in 300 between runs of one image), a
hypothesis that fitted (a frame aborted mid-transfer) was refuted by the trace (the stale starts followed stops with the endpoint idle - until the trace was
re-aligned one run, which showed they did follow a partial transfer), and what finished it was the timestamps in the framer's log and the endpoint registers at the
moment of the fault.
