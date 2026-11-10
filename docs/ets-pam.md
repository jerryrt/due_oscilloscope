# ETS PAM-N: patterns, levels, acceptance, and who does what

The ETS capture of `docs/ets-mode.md` carries a two-level PRBS7. This is the plan
for carrying PAM4, PAM8, PAM16, PAM32, PAM64, PAM128 and PAM256 the same way:
a pattern per level count, the levels it puts on the DAC, what counts as a pass,
and how the two benches split and check each other. The criteria are fixed here
before any capture, so a result cannot move them.

Figures marked *(check)* are unmeasured: derived, or taken from another document.

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

## Defaults taken, to be confirmed

* the pattern is the full-transition one in the table, not a shorter eye-only one;
* the swing is 1 V to PAM32 and 2 V from PAM64;
* the eye is rendered as `N - 1` eyes in one tall plot with a level histogram and a
  figures table;
* the numpy backend is the default, with a CUDA backend when the runtime and the
  hardware are both present, and the pure-Python code is kept as the reference.
