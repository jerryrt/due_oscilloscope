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

## `flash.py` left every board erased here, and the cause is its own last line

This took two wrong diagnoses to reach, and both are kept because the
route matters more than the answer.

**The symptom.** `tools/flash.py` writes, verifies, resets, watches the
native port come up, reports success - and the board is in SAM-BA with
`Boot Flash: false` moments later. Every tool that then opens the console
finds silence and no native port, which reads exactly like firmware that
will not boot.

**Wrong diagnosis 1: "opening the programming port erases the board."**
Committed, documented and pushed before it was tested. The claim was that
Linux has no callout node, that the tty layer raises DTR and RTS in
`tty_port_open()`, and that on the Due those are the 16U2's RESET and
ERASE. Measured afterwards, **all four arms survive**: DTR alone, RTS
alone, both, neither - the board answers `v` every time, and six
consecutive pyserial opens at library defaults answer six times. The
`transport.py` branch it produced was reverted.

**Wrong diagnosis 2: "`-R` in the same bossac invocation races the GPNVM
write."** Tested before writing this time: `-e -w -v -b file -R` against
`-e -w -v -b file` then a separate `-R`, three reps each. **Both set the
bit, 6 of 6.** bossac's arguments were never the problem.

**What it actually is.** `touch_1200()` leaves `/dev/ttyACM0` configured
at 1200 baud, and `restore_115200()` - the function written specifically
to stop the next open re-triggering the 16U2 - is on Linux the open that
triggers it. `os.open()` applies the tty's stored termios, still 1200,
and the kernel drives the modem lines before pyserial can set the speed.
It runs *after* `wait_for_boot()`, so the boot check passes, flash.py
prints success, and the erase lands on the way out.

Measured, with a control:

| arm | after bossac | after the one open |
|---|---|---|
| `restore_115200()` | running (3/3) | **SAM-BA (3/3)** |
| same wait, no open | running (2/2) | **running (2/2)** |

**The fix is at the source**: `touch_1200()` sets the speed back to
115200 on the fd it already holds, so the stored termios is never left at
1200 and the next open is ordinary. Three full `tools/flash.sh` runs end
with the board **running** where they previously ended dead every time.
It is not a platform branch - leaving sane line coding behind is right
everywhere, and it is what `restore_115200`'s own docstring always asked
for.

**What is *not* true**, and was asserted here in an earlier version of
this file: there is no erase-on-open in general. An ordinary console open
is harmless. What is dangerous is exactly one open - the first one after
a 1200-baud touch - and the precise trigger condition inside the 16U2 was
not isolated here.

**The lesson.** `restore_115200`'s docstring already described this
symptom in one sentence - *"presents as the board mysteriously restarting
whenever a tool attaches"* - and it was read only after two mechanisms
had been invented, one of them committed. The cheap readings that would
have ended it: `bossac -i` prints `Boot Flash:` in one line, and the
function's own docstring names the failure. *Ask what state the board was
left in before blaming the transport.*

### Other things that are true and useful

- **Linux has no callout node.** `/dev/ttyACM0` is the only node; there
  is no `cu.*` to prefer. Opening it resets the board over NRSTB, which
  is documented and harmless.
- **A clear GPNVM boot bit imitates dead firmware exactly** - silent
  console, native port that will not enumerate, SAM-BA on every reset.
  Read `bossac -p <native> -i` before diagnosing anything else.
- **`bossac -b 1` is not the spelling.** `-b` takes an optional
  *attached* value, so `-b 1` parses `1` as a stray positional and exits
  "extra arguments found". Use `--boot=1`.
- **`find_all_ports()` returns as soon as the programming port is
  found** and does not wait for the native pair, so a call inside the
  ~1 s re-enumeration window returns `(ttyACM0, None, None)`.

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

### flash.py's boot-bit failures are explained

All three `Boot Flash: false` boards here came from `tools/flash.py` or
`tools/sketch.sh`, and none from a direct bossac run. That is not a
coincidence and not bossac: it is `restore_115200()` erasing the board
after the boot check, as measured above. The fix in `touch_1200()`
removes it.
