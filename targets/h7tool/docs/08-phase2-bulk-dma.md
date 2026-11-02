# Phase 2: bulk IN by internal DMA (image5a)

`fw/image5/main.c`. The OTG_HS core runs in internal DMA mode
(`GAHBCFG = DMAEN | HBSTLEN INCR4 *(check: field value taken from the
databook, not from stock, which never uses DMA)*). Endpoint 0 is served by
DMA too (setup packets land in a 24-byte buffer, descriptors are copied to
D2 SRAM first because DMA cannot read DTCM). The stream function's bulk IN
endpoint (EP2, 512-byte packets, 512-word TX FIFO) sends 64 KiB transfers, each
16 version-4 frames, from two buffers in D2 SRAM at 0x30001000 and 0x30011000,
alternating. The payload is written once (sample i = i); between transfers
the CPU rewrites only the 16 frame headers (sequence, timestamp, header CRC,
the shared `frame_crc32`). Streaming starts when the host raises DTR on the
first CDC function and stops when it drops it. Caches are off. FIFO layout in
words (952 available per GHWCFG3): RX 256, TX0 16, TX1 8, TX2 512, TX3 8,
TX4 128.

## Host check
`tools/h7_stream_check.py` reads the port and checks magic, version, header CRC,
sequence continuity and the payload; `tools/test_stream_check.py` holds seven
tests that corrupt a byte of header or payload, drop a frame, mislabel the
version, restart a run and feed nothing, each of which must be detected.
`tools/h7_usb_probe.py stats` reads the device's own counters.

## Measured, linux-x1, 2026-11-02 (host: cdc_acm read of the tty)
| run | duration | bytes | rate | frames | gaps / bad CRC / bad payload |
|---|---|---|---|---|---|
| 1 (first after enumeration) | 5 s | 201,484,288 | 40.30 MB/s | 49,190 | 0 / 0 / 0 |
| 2 | 20 s | 807,548,928 | 40.38 MB/s | 197,155 | 0 / 0 / 0 |
| 3 | 20 s | 806,275,072 | 40.31 MB/s | 196,844 | 0 / 0 / 0 |
| 4 | 20 s | 806,965,248 | 40.35 MB/s | 197,013 | 0 / 0 / 0 |
| 5 | 20 s | 807,431,168 | 40.37 MB/s | 197,126 | 0 / 0 / 0 |

Each run was a fresh open (a stop and a start on the device). The figure is
what the host received through the tty; whether the device or the host limits
it is not established, and the transfers are re-armed from a polled loop at
HSI 64 MHz, so it is not yet a ceiling. For scale only: the Due's measured
inbound figure is 30-33 MB/s (CLAUDE.md), a different link and framing.

## The checker can fail on the live path
`-DFAULT_SKIP_SEQ` (image5x) skips a sequence number every 5000 frames. The
checker, run live against it: 9 gaps in 49,187 frames, exit status 1. Its
first capture also began mid-frame and skipped 2048 bytes, which it counts as
a resync and so reports unclean - conservative, and seen on the first open
after enumeration.

## What went wrong on the way
EP0 OUT was re-armed only after a "transfer complete" interrupt. The core
also ends a control transfer with a status-phase interrupt and disables the
endpoint, so later SETUP packets were lost: the first descriptor reads worked
and then every request timed out for 5 s (cdc_acm bound each function 5 s
late, `lsusb -v` took 15 s). Re-arming whenever EP0 OUT is not enabled fixed
it. The image is built with `RUN_MS=300000` for bench work.

## Not covered
Interrupt-driven operation, OUT endpoints, the control function's endpoints,
transfers larger than 64 KiB, a PLL above HSI, cache-enabled operation,
suspend/resume and host reset while streaming, other hosts.
