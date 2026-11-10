# ETS PAM-N: patterns, levels, acceptance, and who does what

The ETS capture of `docs/ets-mode.md` carries a two-level PRBS7. This is the plan
for carrying PAM4, PAM8, PAM16, PAM32, PAM64, PAM128 and PAM256 the same way:
a pattern per level count, the levels it puts on the DAC, what counts as a pass,
and how the two benches split and check each other. The criteria are fixed here
before any capture, so a result cannot move them.

Figures marked *(check)* are unmeasured: derived, or taken from another document.

## What was found

Where the sequence stopped, and why. The tables under Results have every figure.

- **PAM4, PAM8, PAM16 and PAM32 pass every gate on both benches** at a 1 V
  swing, from one board and from two Dues with independent crystals. The two
  benches agree on level spacing to 0.2%.
- **PAM64 passes at a 1.5 V swing and fails at 2 V**, on both benches. At 2 V
  the three bottom and top eyes close (six on the two-board pair). The cause is
  the step into the outermost levels: the end levels' spread at the symbol
  centre is 1.3 to 3 codes after steps up to 50 levels and 7 to 10 after steps
  of 51 to 63 levels, about 1.6 to 2 V. Capping the step at 47 levels opens
  both end eyes, and the smaller swing removes the large steps. Whether it is
  the step in volts or the position on the DAC's range cannot be separated by
  these captures, and the mechanism (slewing or settling in the DAC's output
  stage) is not known.
- **PAM128 fails at 1.5 V on both benches**, with every one of the 127 eyes
  closed at the symbol centre: the spacing is 14.6 codes and the 0.1% and 99.9%
  points of a level, whose spread is 1.5 codes, take about 10 of them. A larger
  swing widens the spacing and brings the end steps back.
- **PAM256 was not run.** At 1.5 V its spacing would be about 7.4 codes against
  the same level spread, which is smaller than the arithmetic that closes
  PAM128, and the 2 V swing that widens it fails on the end steps. *(check, not
  measured)*
- **The limit is the instrument's level noise against the DAC's usable swing,
  not the ETS method.** The tracker locks, the ladder stays straight (largest
  residual 0.5 codes at PAM128) and the capture is gapless at 43 M samples; what
  runs out is the ADC's resolution of one level step. A quieter reading, from
  averaging or a better ADC front end, moves the limit and this method needs
  no change for it.

Things learned that change how the next capture is run:

- A rate-dependent failure localised to the ends of the ladder is a step-size
  question, and `tools/ets_pam_steps.py` answers it from the raw capture.
- The Rigol window must cover the swing: at 200 mV/div it cut the ends off a 2 V
  signal and its spacing was off by 11%. `ets_pam.py` now sets the window from
  the swing.
- Check that no other `ets_pam.py` or `ets_cross.py` is alive before a run: two
  on one board cost a 45 s capture its integrity, and it read as a transport
  fault.
- The analysis of a 44 M-sample capture was the limit before the capture was:
  9.3 GB and never finished, now about 10 s and 1 GB (the merged CPU pipeline). Its
  remaining single-core stretch is the tracker (3.5 s) and the level statistics
  (1.9 s), pure Python and numpy loops that are not matrix products. BLAS does
  not accelerate them as written; see the measurements in the next section.

Not done: PAM128 at 2 V; PAM256; the capture as a host library function with a
daemon and GUI front end; the GPU path beyond `phase_indices`, `fold_warped` and
`corr_many` (branch `ets-pam-gpu`, not merged).

### What threads and BLAS do for this analysis

Measured on montreal5 (8 cores, scipy-openblas 0.3.30, threads on by default),
eight 6 M-element jobs run one after another against on eight threads:

| operation | threads | note |
|---|---|---|
| `np.bincount`, the histogram | 1.0x | holds the GIL, so threads do not help |
| `np.fmod` and a cast, the phase index | 2.9x | releases the GIL |
| fancy-index gather, `template[idx]` | 1.6x | memory-bound |
| 2000 x 2000 matrix product, BLAS | 2.1x (0.33 s on one thread, 0.16 s on all) | the one operation BLAS is for |

BLAS accelerates matrix products and dot products. The analysis's hot loops are
a gather, a fmod, a histogram and a running line fit, none of which BLAS reaches,
and the histogram does not scale with threads either: it needs processes or a
device (the GPU kernel's atomics). The single-core stretches left in the analysis
are the tracker and the level statistics, which are removed by restructuring them
as batched array operations, not by a faster linear algebra library.

## The order of work

PAM4, then PAM8, and so on, one level count at a time. A step is done when every
gate below passes on **both** benches and its eye diagram has been published and
shown to the owner; the next level count starts after that. The first gate that fails on either bench
stops the sequence: the cause is found first, the two benches compare what they
saw, and the owner decides how to go on. Nothing is retried or loosened to get
past it.

## The pattern

`N = 2^m` levels, `m` bits per symbol. The binary source is a maximal-length
PRBS of order `n`, a Fibonacci shift register that starts all ones and shifts
left:

* the register is `n` bits wide and starts at `2^n - 1`; each step first takes
  the **output bit, the register's lowest bit, before the shift** (so the first
  bit is 1), then shifts left and masks to `n` bits;
* feedback = the XOR of the register bits at positions `t - 1` for each tap `t`
  (bit 0 is the lowest), inserted at the bottom as the register shifts left;
* taps, by order: 7 (7, 6), 9 (9, 5), 11 (11, 9), 13 (13, 12, 2, 1),
  15 (15, 14), 16 (16, 15, 13, 4), 17 (17, 14).

The sequence has `L = 2^n - 1` bits and returns to the all-ones register after
exactly `L` steps. Symbols read `m` consecutive bits, **first bit most
significant**, in non-overlapping groups that wrap around the sequence: symbol
`j` starts at bit `j * m` (modulo `L`) of the binary sequence. A group
`g` is a Gray code, and the level index is its decoded value
`g XOR (g >> 1) XOR (g >> 2) XOR ...` (for `m = 2`: 00, 01, 11, 10 are levels
0, 1, 2, 3). Symbol `j` is group `j`, and the pattern
repeats when the groups do.

This is this project's pattern, not an IEEE one: the polynomials and the all-ones
start are ours, and no claim is made that PAM4 on PRBS13 matches PRBS13Q.

**Which order.** To put every one of the `N^2` ordered symbol pairs on the wire,
including one level followed by itself, the order must satisfy two conditions:

* `n >= 2m + 1`, because a pair is `2m` bits and an order-`n` sequence holds an
  all-zero run of only `n - 1`;
* `gcd(m, 2^n - 1) = 1`, so the groups start at every position of the sequence.
  When the gcd is `g`, only one position in `g` starts a group, the symbol
  sequence shortens to `L / g` symbols, and pairs are lost.

| PAM | `m` | order | `L` (symbols) | pairs | period at DAC RC 29 | samples for 20 per tick | at 978 ksps |
|---|---|---|---|---|---|---|---|
| 4 | 2 | 7 | 127 | 16 | 3,683 ticks | 74 k | 0.1 s |
| 8 | 3 | 7 | 127 | 64 | 3,683 | 74 k | 0.1 s |
| 16 | 4 | 9 | 511 | 256 | 14,819 | 296 k | 0.3 s |
| 32 | 5 | 11 | 2,047 | 1,024 | 59,363 | 1.19 M | 1.2 s |
| 64 | 6 | 13 | 8,191 | 4,096 | 237,539 | 4.75 M | 4.9 s |
| 128 | 7 | **16** | 65,535 | 16,384 | 1,900,515 | 38.0 M | 38.9 s |
| 256 | 8 | 17 | 131,071 | 65,536 | 3,801,059 | 76.0 M | 77.7 s |

PAM128 cannot use order 15: 7 divides 32,767, so only 4,681 symbols and 4,346 of
its 16,384 pairs occur. The table was checked by running each register: every
sequence is maximal, and every row above has all `N` levels and all `N^2` pairs.
The last two columns assume 20 samples in each 22 ns tick position of the fold and
the ADC at RC 46; 2.2 ns bins need ten times more.

The pairing rule of `docs/ets-mode.md` applies with the pattern length: the ADC RC
must share no more than a factor of 2 with `L * rc_dac`. PRBS11 is 2,047 = 23 * 89,
so RC 46 is refused for PAM32 and the planner picks another even RC.

## The levels

Level `i` of `N` is the DAC code

    floor(2048 + (i - (N - 1) / 2) * swing / ((N - 1) * lsb) + 0.5)

with `lsb` = 2214 / 4095 mV (the DAC's span of about 546 to 2760 mV over 4095
codes, `docs/hardware.md`), exactly, and the swing exactly 1000 or 2000 mV,
rounded half up (`Fraction`, not `float`, and not Python's `round`, which rounds
half to even). The "DAC codes per level" column below is the mean spacing; the
smallest neighbour step is a code or two less. Comparisons are against these whole
codes, not an ideal ladder.

The swing is 1 V up to PAM32 and 2 V from PAM64, inside the DAC's window of about
0.55 to 2.75 V, so the highest orders are not buried in noise. At the converters'
measured 1.3 codes of noise and 0.806 mV per ADC code:

| PAM | swing | spacing | ADC codes | noise sigmas | DAC codes per level |
|---|---|---|---|---|---|
| 4 | 1 V | 333.3 mV | 413.6 | 318 | 616 |
| 8 | 1 V | 142.9 mV | 177.3 | 136 | 264 |
| 16 | 1 V | 66.7 mV | 82.7 | 64 | 123 |
| 32 | 1 V | 32.3 mV | 40.0 | 31 | 60 |
| 64 | 2 V | 31.7 mV | 39.4 | 30 | 59 |
| 128 | 2 V | 15.7 mV | 19.5 | 15 | 29 |
| 256 | 2 V | 7.84 mV | 9.73 | 7.5 | 14.5 |

An eye is open when the upper level's samples at its centre sit above the lower
level's. With each level's 0.1% and 99.9% points at about 3.1 sigma, that needs a
spacing of about 8 codes. PAM256 at 2 V leaves **1.7 codes** of height, and at 1 V it
would be closed (4.9 codes). The DAC's and ADC's integral and differential
nonlinearity are unmeasured *(check)*, and at PAM256 one code is 10% of a level.

## Gates

Per PAM, per bench. Every number is chosen here and is not changed after a run.

| gate | what has to be true |
|---|---|
| **A1 pattern** | the library's symbols equal the independent oracle's over the whole period; all `N` levels and all `N^2` pairs occur; the DAC codes rise strictly with at least 2 codes between neighbours |
| **A2 transport** | 0 underruns, every byte played, no frame gaps, in a run of up to 120 s (about 117 M samples, 235 MB raw), the longest accepted until gaps are accounted for |
| **A3 clock** | `model_adequate` true and `lattice_gcd` at most 2 on two boards, ADC RC coprime on one; at least 20 samples per tick position of the fold, or the eye-only reading is labelled so |
| **A4 levels** | `N` distinct levels at the symbol centres, in order, each adjacent pair at least 3 sigma apart |
| **A5 linearity** | every level mean within a quarter of a level spacing of the least-squares line through the DAC codes; the residuals are reported in codes. They are the nonlinearity of the DAC and the ADC together: with no separate measurement of either, nothing here attributes one to the other |
| **A6 eyes** | **every** one of the `N - 1` eyes has a positive height, and a width, the stretch of the symbol where its height stays positive, of at least 0.2 of a symbol; the figures reported are the smallest height and the smallest width over the eyes, and all of them are listed |

| **A9 eye shown** | the step's eye diagram is drawn from its captures, published, and shown to the owner before the next level count starts. It is made by the same page script as the earlier eyes (`tools/ets_eye_page.py`), extended for several eyes: the density of every sample, the `N - 1` eyes marked, a histogram of the levels at the symbol centre, and the figures of A4 to A6 beside it |

Reported, not gated: **A7** the rise of the adjacent-level step against
`sqrt(a * step^2 + floor^2)` with that bench's own fit of the edge floor
(`docs/ets-mode.md`; on `linux-x1` `a` = 0.0168 ns^2/mV^2 and the floor is 42.4 ns);
**A8** the same pattern read on both benches: level spacing, eye heights, edge times.

**Predictions, before the first run.** A1 to A6 pass for PAM4 through PAM128 on
both benches. PAM256 is the likely first failure, at A6 and then A5, because its
eye height has 1.7 codes of margin and converter nonlinearity can take that. If
anything fails earlier, it is not the arithmetic above and something else is wrong.
The Rigol cannot test PAM64 and up: one step of its 8-bit record is about 8 mV at
200 mV per division, and the spacing is 31.7 mV and falling.

## Who does what

| | `montreal5` (one Due, a Rigol) | `linux-x1` (two Dues, no scope) |
|---|---|---|
| **Pattern** | the pattern module and its tests | an **independent oracle**, written from the section above and nothing else, and a test that the two agree bit for bit |
| **Capture** | the same-board loop, levels checked against the Rigol up to PAM32 | the two-board capture with its fine time axis |
| **Analysis** | the multi-level template, level classification, the `N - 1` eyes and their figures | an independent reading of the same raw captures from the gate definitions, to compare |
| **Backend** | | the numpy backend and its venv, with equivalence tests against the pure-Python reference. PAM64 and up need it |
| **Records, docs** | the ladder table of results, one row per step | their rows, indexed in `records/README.md` |

The captures of PAM4 to PAM32 fit the current pure-Python analysis; PAM64 and up
do not, so the backend has to land before PAM64. Each bench works on its own
short-lived branch and sends the other a message when something is ready; nothing
is merged to `main` without the owner's go-ahead. A lost frame is accounted for by
sequence number only once gap handling exists, and until then it fails A2.

## Results

One row per level count and bench. A step is finished when both benches pass and
the eye has been shown to the owner; the figures are in the records named.

| PAM | bench | A3 | A4 | A5 | A6 | levels, ADC codes | spacing | eyes, codes high, symbols wide | records |
|---|---|---|---|---|---|---|---|---|---|
| 4 | `montreal5`, one board | pass | pass | pass | pass | 1428.5, 1841.1, 2253.4, 2666.0 | 412.5 codes, 332 mV | 393-394, 0.90 | `ets-pam-montreal5.jsonl`, `ets-pam4-eye-montreal5.json` |
| 4 | `linux-x1`, two boards | pass | pass | pass | pass | 1425.5, 1838.9, 2252.0, 2665.4 | 413.3 codes | 396-397, 0.85-0.90 | `ets-pam-linux-x1.jsonl`, `ets-pam4-eye-linux-x1.json` |
| 8 | `montreal5`, one board | pass | pass | pass | pass | 8 levels, spacing 176.8 codes (142 mV) | 176.8 codes | 157-159, 0.75 | `ets-pam-montreal5.jsonl`, `ets-pam8-eye-montreal5.json` |
| 8 | `linux-x1`, two boards | pass | pass | pass | pass | 8 levels | 177.1 codes | 159-161, 0.75 | `ets-pam-linux-x1.jsonl`, `ets-pam8-eye-linux-x1.json` |
| 16 | `montreal5`, one board | pass | pass | pass | pass | 16 levels | 82.5 codes (66.5 mV) | 62-65, 0.70 | `ets-pam-montreal5.jsonl`, `ets-pam16-eye-montreal5.json` |
| 16 | `linux-x1`, two boards | pass | pass | pass | pass | 16 levels | 82.65 codes | 65, 0.70 | `ets-pam-linux-x1.jsonl`, `ets-pam16-eye-linux-x1.json` |
| 32 | `montreal5`, one board | pass | pass | pass | pass | 32 levels | 39.9 codes (32.2 mV) | 19-21, 0.70 | `ets-pam-montreal5.jsonl`, `ets-pam32-eye-montreal5.json` |
| 32 | `linux-x1`, two boards | pass | pass | pass | pass | 32 levels | 40.0 codes | 22, 0.65 | `ets-pam-linux-x1.jsonl`, `ets-pam32-eye-linux-x1.json` |
| 64 | `montreal5`, one board | pass | pass | pass | **FAIL** | 64 levels, 2 V swing | 39.3 codes (31.7 mV) | 3 of 63 eyes closed (-16, -4, -2); the other 60 are 8-22 | `ets-pam-montreal5.jsonl`, `ets-pam64-eye-montreal5.json` |
| 64, 1.5 V | `montreal5`, one board | pass | pass | pass | pass | 64 levels, 1.5 V swing | 29.5 codes (23.8 mV) | all 63 open, 8-13 | `ets-pam-montreal5.jsonl`, `ets-pam64-1v5-eye-montreal5.json` |
| 64 | `linux-x1`, two boards | pass | pass | pass | **FAIL** (2 V) | 64 levels, 2 V swing | 39.3 codes | 6 of 63 closed (-29 worst, top) | `ets-pam-linux-x1.jsonl` (diagnostic), `ets-pam64-eye-linux-x1.json`, `ets-pam64-steps-2v-linux-x1.txt` |
| 64, 1.5 V | `linux-x1`, two boards | pass | pass | pass | pass | 64 levels, 1.5 V swing | 29.5 codes | all 63 open, 11-13, 0.55 wide | `ets-pam-linux-x1.jsonl`, `ets-pam64-1v5-eye-linux-x1.json`, `ets-pam64-steps-1v5-linux-x1.txt` |
| 128, 1.5 V | `montreal5`, one board, 14 s | pass | pass | pass | **FAIL** | 128 levels, 1.5 V swing | 14.6 codes (11.8 mV) | all 127 closed, -7 codes | `ets-pam-montreal5.jsonl` (diagnostic row) |
| 128, 1.5 V | `montreal5`, one board, 45 s, 43 M samples | pass | pass | pass | **FAIL** | 128 levels, 1.5 V swing | 14.6 codes | all 127 closed, -7 codes, 0.35-0.5 wide | `ets-pam-montreal5.jsonl`, `ets-pam128-eye-montreal5.json` |

PAM4 on `montreal5`: the Rigol reads the same four levels at 1166, 1495, 1831 and
2154 mV, a spacing of 329.1 mV against the ADC's 332.4 mV (ratio 1.010), with a
residual from a line under one of its 8 mV steps. A2: 0 underruns and 45 MB played,
no gaps, with a capture of 13.9 M samples. One clock, so the samples sit on 56 of
560 columns and each transition crosses a few of them; the two-board eye fills
them all. The first run of this analysis failed A4 to A6, from a defect in the
analysis and not in the signal: the capture's trimmed start was not passed to
the labelling pass.

The two benches' PAM4 agree: level spacing within 0.2% (412.5 against 413.3
codes), eye heights 393-394 against 396-397 codes. The two-board level spread is
2.4 codes against 1.5 on one board; it has not been explained, and the figures
cannot say whether it is the second ADC, the ADC RC (46 against 45) or the
cross-wiring. A2 on `linux-x1`: 0 underruns, no gaps, 15.6 M samples, two runs
identical to three digits.

PAM64 on `montreal5` fails A6 on both runs, identically: the bottom eye, the one
above it and the top eye are closed at the symbol centre, 60 of 63 are open.
What the data show, and what they do not:

- The level spread is flat at 1.7 codes over the middle 30 levels and rises
  smoothly toward both ends, to 4.2 at the bottom and 3.6 at the top.
- It is a settling tail, not level noise. Within one symbol the end levels'
  spread falls from 5.5 at the start to 3.0 at the centre and 1.65 at 0.6-0.8 of
  the symbol, where a middle level reads 1.6 too. The A6 height is taken at the
  centre, where the ends have not settled and the middle levels have.
- The ladder is straight (largest residual 0.72 codes), so the ends are not
  compressed. The Rigol's 8-bit steps are 4 codes of the PAM64 spacing, so its
  spacing figure (ratio 1.11) is not a check at this level count.
- `montreal5` runs with probes on, which adds noise to the link. The failure is
  recorded against that setup; the two-board pair on `linux-x1` decides whether
  it is the setup or the signal.
- The Rigol window was 0.85 V to 2.45 V (200 mV/div, offset -1.648 V) against a
  signal of 0.65 V to 2.65 V, so its end levels were off screen and its spacing
  (1.11 against 1.01 at PAM4 to PAM32) is not a measurement here.
- It comes from the steps between the outermost levels. `tools/ets_pam_steps.py`
  splits each end level's centre samples by the previous symbol. At 2 V the bottom
  level's spread is 1.3 to 1.4 codes after steps of up to 25 levels, 3.0 after
  steps of 39 to 50 and 8.3 after steps of 51 to 63 (the top level, 6.5 from the
  far end). With the step into the level capped at 47 of 63 levels the bottom eye
  reads +18 codes and the top +19, where every step gave -16 and -2; the middle
  eye, whose largest step is 32 levels, reads 19 either way.
- Reducing the swing to 1.5 V works as expected. The same outermost steps fall to
  3.0 and 2.9 codes, every eye is open (8 to 13 codes against a spacing of 29.5)
  and A6 passes on both runs, with the Rigol window widened to 0.5 V/div.
- The two-board pair shows the same, larger: at 2 V the bottom level's spread is
  2.4 to 2.5 codes after steps up to 50 levels and 6.9 after 51 to 63, the top
  10.2; capping the step at 47 levels opens both end eyes (-8.7 and -29.0 become
  +22.0), and at 1.5 V all 63 eyes are open at 11 to 13 codes.
- Not established: whether it is the step in volts or the position on the DAC's
  range. At 2 V, steps of 39 to 50 levels (1.2 to 1.6 V) give 3.0 codes, the same
  as the 1.5 V swing's full-scale steps, which says the step in volts; but a
  smaller swing also moves the end levels away from the DAC's limits, and the two
  captures cannot separate them. Nor is the mechanism (slewing, or settling in
  the DAC output stage) known.

PAM128 at 1.5 V on `montreal5`, DAC RC 28 and ADC RC 47 (the pattern's 65,535
symbols share the factors 3 and 5 with RC 45):

- The full-length capture, 45 s (43.0 M samples, 23 per tick, 0 underruns, 144,666,624
  bytes sent and received), gives the same on both runs: A3 to A5 pass, spacing
  14.63 codes, smallest level separation 6.8 and 7.6 sigma, level spread 1.5
  (2.1 at most), and A6 fails with all 127 eyes closed at -7 codes. The 14 s
  capture below reads the same.
- A 14 s capture (about 7 samples per tick, against the 20 planned) is clean
  and passes A3 to A5, with the ladder straight (largest residual 0.47 codes) and
  a spacing of 14.6 codes, and fails A6: all 127 eyes are closed, the smallest at
  -7 codes. The level spread is 1.5 to 1.9 codes, so the 0.1% and 99.9% points
  sit about 5 to 6 codes either side of each level, against a spacing of 14.6.
  That is the arithmetic of the gate and not of the sample count, and more samples
  only widen the tails, so a longer capture would not open them. The swing that
  keeps PAM64's end steps short leaves PAM128 no margin.
- The first 45 s capture was not analysable (1,951 sequence gaps, 8,393 dropped
  frames, 96.4 MB sent against 86.3 MB received) and the cause was two runs on
  the board at once: an earlier attempt, started as a background job that was
  believed killed, ran to its end while the next run was capturing, so the raw
  files of the two start 15 s apart. Run alone, a 45 s PAM128 capture has no
  gaps, no dropped frames and every playback byte conserved (144,666,112 sent and
  received), so capture length is not a limit and PAM256's 77 s is not ruled out
  by it. The check before a run is that no other `ets_pam.py` or `ets_cross.py`
  process is alive.

## Defaults taken, to be confirmed

* the pattern is the full-transition one in the table, not a shorter eye-only one;
* the swing is 1 V to PAM32 and 2 V from PAM64;
* the eye is rendered as `N - 1` eyes in one tall plot with a level histogram and a
  figures table;
* the numpy backend is the default, with a CUDA backend when the runtime and the
  hardware are both present, and the pure-Python code is kept as the reference.
