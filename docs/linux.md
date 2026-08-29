# Native Linux: bring-up on `linux-x1`

`CLAUDE.md` carried native Linux as **tier 1, deferred** - "No host,
nothing measured. Not a claim until a Linux machine has a board on it" -
for the whole project. This is that machine. Everything here is
first-time-on-Linux unless it says otherwise, and it is written as
bring-up rather than as validation: a figure counts once it is taken,
not because the platform is nominally tier 1.

| | |
|---|---|
| Bench | `linux-x1` |
| Host | Ubuntu 26.04 LTS, kernel 7.0.0-30-generic, i5-8265U, 15 GiB |
| Python | 3.14.4 (suite), 3.13.13 via brew (GUI) |
| Toolchain | apt `arm-none-eabi-gcc` **14.2.1**, cmake 4.2.3, ninja 1.13.2 |
| Track A | arduino-cli 1.5.1, `arduino:sam` 1.6.12 |
| Wiring | `DAC0->A0, DAC1->A1, A2 bare` - **measured with `s`**, below |
| Board | Track B, `Due Scope B` / `B-01`, three nodes |

The wiring is the same cabling as `macos` and `windows-desk`, and is
**not** the DSO bench's. Declared in `bench.json`, which is gitignored
per `host/provenance.py`.

## Opening the programming port erases the board

The one finding that makes a Linux bench unusable until it is fixed, and
it is invisible unless you are watching `lsusb`.

`docs/hardware.md` says *"always `/dev/cu.*`, never `/dev/tty.*`"* and
scopes it to macOS. The reason is the callout node: `cu.*` does not touch
modem-control lines and `tty.*` does. **Linux has no callout node.**
`/dev/ttyACM0` is the only node and behaves like `tty.*`, because the tty
layer raises DTR and RTS in `tty_port_open()` before userspace sees the
fd.

On the Due those two lines are the 16U2's **RESET and ERASE**. So an
ordinary open of the programming port erases the flash and drops the
board into SAM-BA. Observed three times before it was understood: the
board ran Track B for 39 s, `ports.py` opened the console to ask what it
was, and it came back as `03eb:6124` with a blank chip and a silent
console - which reads exactly like a firmware that will not boot.

`dtr=False` does not help, and that is the part worth remembering: nothing
has been asserted *by us* and the lines are high anyway. The fix clears
them rather than declining to set them (`host/transport.py`, the seam
`CLAUDE.md` names for a policy that needs a `sys.platform` test). Cleared,
the same open returns the identity line and the board keeps running; the
documented NRSTB reset still happens and the native pair re-enumerates
about a second later.

**macOS is untouched** - it keeps opening `cu.*` and never enters the
branch. This is the Linux spelling of a rule that already existed.

A corollary for discovery: `find_all_ports()` returns as soon as the
programming port is found and does not wait for the native pair, so a
call made inside that ~1 s re-enumeration window returns
`(ttyACM0, None, None)`. That is the documented "re-glob after opening
control", not a fault.

## Byte conservation: Linux is Windows, not macOS

`tools/writepolicy.py`, same design and same arms as the 2026-08-29
macOS and windows-desk runs - four runs per arm per rate, ABBA within
each rate. `records/writepolicy-linux.jsonl`,
`records/writepolicy-linux-rc44-39.jsonl`.

| rate | const | due-sized |
|---|---|---|
| 200,000 sps | 0 B | 0 B |
| 397,959 sps | 0 B | 0 B |
| 600,000 sps | 0 B | 0 B |
| 886,363 sps | 0 B | 0 B |
| 1,000,000 sps | 0 B | 0 B |

**0 B in all 40 runs, both arms, every rate, `under=0` throughout.**

macOS loses 0.605-0.633% at 397,959 and 0.763-0.915% at 600,000 on the
due-sized arm. Linux loses nothing on either arm, which is the Windows
result. So `Feeder.WRITE_SIZE` is confirmed a **macOS-only** workaround
on a third platform, and `tests/helpers.py`'s
`BUFFERING_HOST = sys.platform == "darwin"` is now *measured* for Linux
rather than inferred from `not darwin`. The five tests it skips here are
correctly skipped.

## The WSL2 ambiguity is resolved, and the tunnel was innocent

`CLAUDE.md` flagged this explicitly and said only a native host could
settle it:

> "Linux buffers ahead without discarding" and "usbip supplies the
> elasticity" predict the same numbers, and only a native host separates
> them.

The WSL2 run had **lower** underruns than native Windows at the top of
the ladder - median 0 against 6 at RC 44, 0 against 8 at RC 39 - and that
was read as the tunnel's queue flattering the device, "optimistic, not
pessimistic, which is the worse trap".

Native Linux, no tunnel:

| | RC 44 | RC 39 |
|---|---|---|
| native Windows | 6 | 8 |
| WSL2 via usbip | 0 | 0 |
| **native Linux** | **0** | **0** |

The elasticity is **Linux's own**, not usbip's. The WSL2 underrun
figures were not optimistic after all.

Stated carefully, because this is one bench: it does not prove usbip
contributes nothing, and the kernels differ (7.0.0 native against WSL2's
5.15). What it removes is the *reason to suspect* the tunnel - native
Linux reaches 0 unaided, so no tunnel is needed to explain 0.

Note also that Linux beats native Windows here: Windows conserves bytes
but still underruns 6-8 times at these rates, and Linux does not.

## Suites

| suite | result |
|---|---|
| Track B, board attached | **505 passed, 1 failed, 16 skipped, 1 xfailed** (8:47) |
| GUI (`.venv-gui`, offscreen) | **100 passed** (23 s) |
| Track A | compiles (70512 bytes); suite not yet run here |

The failure is
`test_control.py::test_stream_stats_says_what_the_console_says[b]` -
`ring_overflow` 292 from the control channel against 332 from the
console. It **passes 3/3 standalone**, so it is context-only, the same
class as the `test_the_fanout_cost_is_recorded_per_frame` failure
documented on macOS. Not a Linux defect.

The xfail is issue #5's gate, drawing +13.5 codes at phase 156, inside
the recorded range.

`rt.py`'s `SCHED_FIFO` path works natively - `sched=fifo:10`, policy
confirmed with `sched_getscheduler`. It had only ever run under WSL2
before. Without an `rtprio` limit it declines cleanly with an accurate
message rather than pretending.

## Two documented figures reproduce independently

From `s` on a third board-and-host, which is worth more than either
existing bench re-running it:

| Quantity | Recorded | `linux-x1` |
|---|---|---|
| DAC output span | 546-2760 mV | **547-2766 mV** |
| ADC linearity | 171-172 codes / 256 DAC codes | **~172.3** |

## Setting up the next Linux box

`toolchains.json` needs **no new entry** - all five tools resolve
unmodified, with apt's cross compiler found at `/usr/bin`. What is not in
the docs and was needed here:

1. **`dialout` group.** `/dev/ttyACM*` is `root:dialout 0660`; without it
   every open is `EACCES`. Takes effect at next login (`sg dialout -c`
   bridges the current one).
2. **ModemManager** probes every new `ttyACM` and sends AT commands at
   the board. Ignore ours by VID/PID with `ID_MM_DEVICE_IGNORE=1` on
   2341:003d, 2341:003e and 03eb:6124, rather than disabling the service.
3. **`rtprio` is 0 by default**, so `rt.py` cannot promote. A
   `limits.d` entry fixes it, at next login.
4. **The GUI needs a second interpreter.** PySide6 6.9.3 is
   `>=3.9,<3.14` and Ubuntu 26.04 ships only 3.14, which is not in the
   archive as a lower version; brew's `python@3.13` is what this bench
   uses. `requirements-gui.txt` then installs **unchanged** - the pins
   resolve on Linux/3.13 as they do on macOS/3.13 and Windows/3.12.

### bossac left the boot bit clear once

`tools/flash.py`'s first run here wrote and verified, reported "Set boot
flash true", and the board still came back in SAM-BA with
`Boot Flash: false` on readback. An explicit `bossac --boot=1` set it,
and a later identical `flash.py`-shaped invocation worked correctly.

Its bossac arguments are right (`-U true -e -w -v -b ... -R`), so this is
**recorded, not attributed** - it happened once, against an unknown
firmware that was on the board at the time, and has not reproduced. Note
that `-b 1` is *not* the spelling: bossac takes `-b` with an optional
attached value, so `-b 1` parses the `1` as a stray positional and exits.
Use `--boot=1`.
