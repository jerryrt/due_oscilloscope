# The DAC and ADC with a Rigol scope on the pins: `montreal5`

DAC0 measured with a Rigol DS1102E on the pin, first with nothing else
on it and then with the ADC loop closed, and the same loop's held-code
noise and SINAD with and without the scope probes attached. Three
questions: where the DAC's output frequency stops following the request,
whether the probe or the ADC input (a jumper from DAC0 to A0) changes
that, and how much of the failing noise and SINAD tests is the probes.

## Result

| | |
|---|---|
| DAC output pins at | **about 866 kHz** (865,801 Hz measured), from a 1.8 MHz update rate up |
| Follows the request up to | 1.6 MHz update rate = 803-805 kHz |
| 10-90% edge | **290-300 ns** above 1 MHz, the same at every setting below |
| Swing, x1 probe | 2.32-2.36 V (0.49-0.51 V to 2.83-2.85 V on the scope) |
| Swing, x10 probe | 2.18-2.22 V (0.57-0.59 V to 2.77-2.79 V) |
| Effect of the A0 jumper | none resolved (at most one 0.04 V scope step) |
| Held-code noise, probes **on** the pins and the scope on | 1.23-1.37 codes rms, every condition above the recorded bound of 1.04 |
| Held-code noise, probes **off** | **0.79-0.81** codes rms, inside the bound |
| SINAD, probes on / off | 56.9-57.9 dB / **60.9-61.1 dB** (bound: at least 59.85) |

The probe's load (about 100 pF at x1, about 10 pF at x10) moved neither
the ceiling nor the edge speed. It moved the swing reading by 0.14 V, in
the direction a heavier load would not produce, so the x1/x10 difference
is a property of the measurement and not shown to be the DAC's. Its cause
is not established.

Every request from 400 kHz to 1.6 MHz equals 45 MHz / RC / 2 for the RC
the request rounds to (1.6 MHz is RC 28: 803,571 Hz), and everything from
1.8 MHz up lands on RC 26: 865,385 Hz, 0.05% under the measured value.
That is consistent with a pin at RC 26 and does not prove it. `docs/awg.md`
records about 750 kHz, which RC 26 gives at the 78 MHz clock (39 MHz / 26
/ 2); that attribution is a hypothesis, and this bench is 90 MHz only.

## The scope probes add noise, and half of it is passive

The same held-code noise and SINAD the board tier gates
(`tests/test_noise_board.py`, `tests/test_sinad_board.py`), measured by
`tools/station_repeat.py` under named conditions. Seven runs per
condition, run 1 dropped by index, so n = 6.

| Condition | Probes | Noise RC 86 / RC 225 | SINAD RC 86 / RC 225 |
|---|---|---|---|
| `seat0-asis` | x1 on pins | 1.223 / 1.260 | 57.91 / 57.71 dB |
| `seat1` to `seat3` (jumpers re-seated each time) | on | 1.30-1.33 / 1.33-1.37 | 57.2-57.5 / 57.1-57.2 |
| `seat4` | on | 1.292 / 1.342 | 57.43 / 56.89 |
| `probes-off` | tips lifted | **0.792 / 0.805** | **60.88 / 61.12** |
| `scope-off-tips-on` | tips on, scope powered off | 1.025 / 1.059 | 59.56 / 59.18 |
| `probes-back` | on again | 1.231 / 1.292 | 57.67 / 57.65 |
| `late-asis` | on, untouched | 1.231 / 1.294 | 57.76 / 57.52 |
| Recorded bound | | at most 1.04 | at least 59.85 |

- **The probes are the cause of the failing tests.** Lifting the tips
  takes noise from 1.29 to 0.79 codes and puts SINAD 1 dB inside its
  bound; putting them back restores the failure, and an untouched
  condition after it shows no drift.
- **The extra noise is about 1.0 code rms, broadband.** One narrow line
  appears with probes on and carries 0.4-2.3% of the power.
- **Half is the scope's electronics, half is passive.** At RC 86, in
  quadrature (independent sources assumed): 0.46 codes squared goes when
  the scope is powered off, 0.42 stays with the cables on the pins. The
  passive half is not split: probe loading, pickup and a ground loop
  through the scope's mains earth (still connected with the scope
  switched off) are all candidates.
- **Re-seating the jumpers is a small term**: the spread of the four
  seating means is 0.05 codes and 0.3 dB, against a probe effect of 0.5
  codes and 3.5 dB. Within a condition the scatter is 0.005-0.02 codes.
- **Build:** `seat0` to `seat3` ran on `ed87093`, the rest on
  `7ccc732+ad4a1a17`. `seat4` sits in the same band as the first four, so
  the build did not move the noise at this resolution.

A noise or SINAD acceptance measurement on this station therefore needs
the probes off the pins; with them on it measures the board plus the
scope. A condition not yet run: the scope's mains cord unplugged with the
tips on, which separates the ground loop from the passive load.

## Setup

| part | identity |
|---|---|
| Bench | `montreal5`, Ubuntu 26.04.1 LTS, Linux 7.0.0-42-generic x86_64 |
| Board | Arduino Due, programming port 2341:003d serial `1344847493935140A666`; native port 2341:003e serial `B-01`; uid `442032204e52344d3030363139303038` |
| Firmware | Track B, `fw=0.2.0`, `ctlver=4`, `framever=3`, MCK 90 MHz. DAC rows: `2809031` (a pre-rebase copy of `baac7f6`) and `ed87093`. Noise series: `ed87093`, then `7ccc732+ad4a1a17` |
| Scope | Rigol DS1102E, serial `DS1ET171806825`, firmware `00.04.02.01.00`, read through `host/scope.py` over raw USBTMC |
| Host software | Python 3.14.5, pyusb 1.3.1, libusb-package 1.0.30.0, pyserial 3.5, pytest 9.2.0, bossac 1.9.1, uhubctl 2.6.0 |
| Probes | two, x1/x10 switchable, make not recorded; compensated at x10 on the scope's 1 kHz terminal to 0.0% overshoot (the scope resolves 0.04 V steps) |

Wiring for the DAC rows: CH1 on DAC0, CH2 on DAC1 (undriven in solo), the
A0 jumper (DAC0 to A0) in only where a row says so, no A1 jumper. For the
noise series: both jumpers (DAC0 to A0, DAC1 to A1) in, which is the
standard board-tier wiring. The scope triggers on CH1 or CH2
interchangeably; DAC1 carries the phase-locked sync square in normal
modes.

## Method

DAC rows. Per rate: stop the generator, `=3,256J` (solo: every table entry
tagged DAC0, no sync, double rate), `=1,2,256W` (a square, two points),
then `=<dac_hz>,100000M` (the device's own table on TIOA1, no USB in the
path). The scope timebase is the smallest 1-2-5 step at least a third of
the period; CH1 is 0.5 V/div at the probe tip with a -1.65 V offset. The
frequency, levels and 10-90% rise time come from the scope's 600-point
waveform: levels are medians of the bottom and top fifth, the frequency
is the mean spacing of rising mid-level crossings, the rise is the median
over the rising edges. Three captures per row, medians reported. The raw
rows are `records/dac-openended-montreal5.jsonl`.

Noise series. `tools/station_repeat.py run --label X --runs 7`; the rows
are `records/station-repeat-montreal5.jsonl`, one per run and ADC rate,
each carrying the board's uid and build. `summary` drops run 1 of every
condition by index.

Two traps worth knowing:

- **The driver's vertical scale is volts at the probe tip, not at the
  scope input.** Passing 10x the scale for a x10 probe left the scope with
  0.16 V per step and every frequency came out as noise.
- **The scope's own `:MEAS:FREQ?` and `:MEAS:VAVG?` are not usable here:**
  `FREQ` returns `99e36` when it cannot measure and `VAVG` is not a valid
  query. Measure from the waveform.

## Rows

**The signal is a full-scale square wave on DAC0**: a two-point table,
one sample at the bottom code and one at the top, so every DAC update is
an edge. The output frequency is the update rate over two, and the
fastest square the converter can be asked for. The device plays its own
table, with no USB in the path, and DAC1 is not driven.

Each cell reads `output frequency (Hz) / swing (V) / 10-90% rise (ns)`.
The update rate is the `<dac_hz>` of `M`; `expect` is that rate over two.
A cell where the output is below `expect` is a rate the converter did
not keep up with.

| update rate | expect | x1, jumper off | x10, jumper off | x10, jumper on | x1, jumper on |
|---|---|---|---|---|---|
| 400 kHz | 200,000 | 200,803 / 2.36 / 360 | 200,803 / 2.22 / 360 | 200,803 / 2.22 / 320 | 200,803 / 2.36 / 360 |
| 800 kHz | 400,000 | 401,606 / 2.34 / 320 | 401,606 / 2.22 / 300 | 401,606 / 2.22 / 300 | 401,606 / 2.36 / 320 |
| 1.2 MHz | 600,000 | 608,519 / 2.34 / 300 | 608,519 / 2.22 / 300 | 608,519 / 2.20 / 300 | 608,519 / 2.32 / 300 |
| 1.4 MHz | 700,000 | 702,988 / 2.32 / 290 | 702,988 / 2.20 / 290 | 702,988 / 2.20 / 290 | 702,988 / 2.32 / 290 |
| 1.6 MHz | 800,000 | 804,829 / 2.32 / 300 | 803,213 / 2.20 / 290 | 804,829 / 2.20 / 290 | 803,213 / 2.32 / 290 |
| 1.8 MHz | 900,000 | 865,801 / 2.32 / 300 | 865,801 / 2.18 / 290 | 865,801 / 2.20 / 290 | 865,801 / 2.32 / 290 |
| 2.0 MHz | 1,000,000 | 865,801 / 2.32 / 300 | 865,801 / 2.18 / 290 | 865,801 / 2.18 / 290 | 865,801 / 2.32 / 300 |
| 3.0 MHz | 1,500,000 | 865,801 / 2.32 / 300 | 865,801 / 2.18 / 290 | 865,801 / 2.20 / 290 | 865,801 / 2.32 / 290 |

The first column exists only here: that case was printed and not saved to
the record file. The x1/jumper-on case was repeated on `ed87093` and read
the same to within one scope step at every row.

## The ADC against the scope

DAC0 playing a 1 kHz square from the host at 200 ksps (`host/loopback.py
--square 1000 --dac-sps 200000 --adc-hz 200000 --adc-channels 2`), the A0
jumper in, x1 probes. The ADC codes are converted at 3.3 V = 4095, an
assumption not checked against the reference.

| | low | high | span | mean |
|---|---|---|---|---|
| Rigol CH1 (medians of the bottom and top fifth) | 0.530 V | 2.810 V | 2.280 V | 1.662 V |
| Rigol CH1, extremes | 0.49 V | 2.85 V | 2.36 V | |
| ADC A0, extremes (647 / 3441 codes) | 0.521 V | 2.773 V | 2.252 V | 1.649 V (2046.5) |

The two instruments agree on the low level within 0.01 V and on the mean
within 0.013 V. The ADC's high is 0.037 V below the scope's median high, a
span ratio of 1.012. The ADC's span matches the documented 0.55-2.75 V DAC
range better than the scope's does, so the scope's top reads high by a few
percent.

A1, with nothing wired to it, carried 948 codes of amplitude against A0's
1,747: 54% of A0's, the bare-pin behaviour `CLAUDE.md` records. With DAC1
jumpered to A1 it reads flat (0.2 codes of amplitude at mid-scale).

`loopback.py` flagged each capture as starting at sequence 37 rather than
0. The figures are extremes, not plateau medians.

## Bench notes

- **USB power.** The host's chipset hub (Intel 8087:8000) advertises
  per-port power switching and `uhubctl` reports ports "off" and back
  "on", but the Due's power LED never goes out: VBUS is not switched. A
  hub with real per-port switching is needed to power-cycle the board
  from the host.
- **`tools/flash.py` and bossac 1.9.1.** The apt `bossac` rejects the
  `-U true` and `-b <file>` spellings the tool passes (they are the
  Arduino-patched bossac's). `bossac -d --port=<node> -w -v --boot=1 -R
  <bin>` works against 1.9.1, and the boot-from-flash bit often needs the
  command a second time.
- **Tool paths.** `bossac` and the ARM binutils come from apt at
  `/usr/bin`; a gitignored `toolchains.local.json` points the registry
  there.
- **The serial nodes.** The Due's nodes are renumbered at every
  re-enumeration. A redirect to a path that is missing at that moment
  creates a regular file under `/dev` that shadows the real node.
  `ls -l /dev/ttyACM*` should show only `c` entries.

## What does not generalise

- One board, one scope, one bench. The noise and SINAD figures say what
  this board does here and not how boards spread; the population run is
  still to be done.
- The scope's absolute levels read about 0.1 V above the DAC's
  documented 0.55-2.75 V window; no reference meter was used.
- The firmware stopped answering once on `ed87093` during the noise
  series, while probe tips were being lifted by hand: the native port
  left the USB bus, the console went silent, and a DTR reset changed
  nothing. Unplugging every cable restored it. No LED state was noted and
  the cause is not established.
- A DAC0 stuck at about 0 V appeared once, after the A0 jumper went in,
  with the board responding and DAC1 driving. A software reset cleared it
  and it did not recur.
