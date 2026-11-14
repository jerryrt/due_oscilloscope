# Clean-room models against the vendor models, on the v2 board's circuits

montreal5, ngspice 45.2 (host), the main checkout's `.venv`. Clean-room models read from the `open-models` worktree
(commit 944d76f), untouched. Every figure comes from a run in this folder unless a repository file is named. Nothing committed.
Layout: `tph/` (TPH2502), `ref/` (REF3030E), `lm/` (LM27762): scripts, raw results, work decks.

## Not compared

- **BAV99, ADS1115**: no vendor SPICE model in `models/`.
- **REF3030E vendor model**: TI's `models/ref3030/REF3030.lib` (sha256 731ff7f0...) is an encrypted TINA library; ngspice stops
  on it, `Error: UTF-8 syntax error in input deck, line 2` (`ref/vendor_try.log`; `models/SOURCES.md` line 30 records the same).
  Section 2 compares against what the board's sims use instead (`v2/sim/scope/netlib.py` `rails()`: 3.0 V behind 0.05 ohm).
- **LM27762 vendor model on the board's own feedback values**: both runs (`idle_steps`, `awg_step`) stalled at 380 us of
  simulated time (3.80e-4 s) after 59 min each, at 10 GB resident, and were stopped (`lm/runs/vendor/*.log`). This is the
  convergence lottery `v2/sim/powercal/lm_tran.py` and `whatif/lm27762/run.py` already document. The one vendor case that ran is
  the case `lm_results.json` records as converged (`su525`).

## 1. TPH2502: TPH2502_OPEN (VSREF=3.3, EN=6.5n) against the vendor TPH2501_simplify

Method: the board's scope driver `v2/sim/scope/run.py --range 5v` (whose `netlist` section writes `range5v/scope_5v.cir`), run
twice: as is, and with `run.MODELS['vendor']`, `netlib.SUB` and `netlib.OPAMP_INC` pointed at the clean model (`tph/run_swap.py`).
All netlist sections run (dc ac bw noise d17 tran stab beh prot xtalk static mc guards cscan); then the board's `report.py`
on each (copy `tph/report_nonefix.py`, changed only to print a `None`: the clean model never reaches 200 uV in D17's switch
sweep). The vendor run reproduces the committed `range5v/results/*.json` exactly (10 of 10 sections compared).
EN=6.5n is the datasheet density; the clean default EN=0 is noiseless.

**`report.py` verdicts are identical**: 11 PASS, 5 PASS*, 1 OPEN, 2 FAIL (SC-4, SC-3) in both, row for row
(`tph/vendor/report.md`, `tph/clean/report.md`).

| figure | vendor | clean-room | difference | requirement, limit | verdict changes? |
|---|---|---|---|---|---|
| DC pin, 0 V in | 1.62946 V | 1.62950 V | +45 uV | SC-2 centring (+-30 mV) | no |
| DC pin, -6 / +6 V in | 0.23289 / 3.0261 V | 0.23288 / 3.0261 V | -11 / +54 uV | SC-2 >= 80 mV margin | no |
| gain at 10 Hz | 0.232772 | 0.232771 | -6e-7 | SC-4 | no |
| f-3dB at pin vs DC (50 ohm source) | 33.6 MHz | 26.7 MHz | -21 % | SC-5 (info) | no |
| gain 1 / 5 / 10 MHz vs 100 kHz | -0.020 / -0.085 / -0.281 dB | -0.023 / -0.115 / -0.393 dB | -0.003 / -0.030 / -0.111 dB | SC-5 (host calibration) | no |
| f-3dB at pin, ADC 3.8k/6p and 1k/8p | 39.9 / 38.4 MHz | 31.7 / 30.5 MHz | -21 % | SM-3 >= 8 MHz at the pin | no (3.8x the floor vs 4.8x) |
| dB at 8 MHz at pin, worst ADC arm | -0.21 | -0.28 | -0.07 dB | SM-3 | no |
| step -5 -> 0 V in: rise 10-90 / settle 0.5 % | 9.7 / 27.4 ns | 11.8 / 29.4 ns | +2.1 / +2.0 ns | - | no |
| SC-10 alternating +6/-6 V through the S/H: error | 0.038 LSB | 0.038 LSB | -0.0002 | <= 0.5 LSB | no |
| SC-10 settle to 0.5 LSB, 3.8k/6p / 1k/8p | 205.1 / 73.1 ns | 205.2 / 73.3 ns | +0.1 ns | 667 ns window | no |
| pin source impedance, max to 10 MHz | 22.23 ohm | 22.24 ohm | +0.01 | SC-10 <= 5 kohm | no |
| THD 5 MHz 10 Vpp / 10 MHz 12 Vpp | -103 / -78 dB | -86 / -63 dB | +17 / +15 dB | SC-12 | no |
| amplifier noise density, 1 MHz | 9.33 nV/rtHz | 6.50 nV/rtHz | -30 % | - | - |
| noise at pin 10 Hz-10 MHz, stage + REF | 42.6 uV | 36.9 uV | -14 % | SC-6 0.2 mV (pre-D17 band) | no |
| noise at pin 10 Hz-1 GHz, stage + REF | 764 uV | 252 uV | -67 % | no limit on this band (D17) | no |
| SC-6 (D17) at Cs, 3.8k/6p / 1k/8p | 50.1 / 90.4 uV | 37.3 / 48.3 uV | -25 / -47 % | <= 200 uV | no |
| SC-9 shared rail + REF only, 10 MHz | 6.3e-6 LSB | 3.8e-4 LSB | x61 | <= 2 LSB | no |
| SC-9 layout budget 0.02 + 0.02 pF, 10 MHz | 1.448 LSB | 1.408 LSB | -0.04 | <= 2 LSB | no |
| SC-9 datasheet -100 dB injected, 5 MHz | 0.0133 LSB | 0.0130 LSB | -0.0002 | <= 2 LSB | no |
| AN-1 PM nominal / worst over Riso 0-100 ohm x 0-100 pF | 69.9 / 65.7 deg | 116.4 / 115.7 deg | +47 / +50 deg | >= 45 deg | no |
| AN-1 gain margin, no Riso / RF 25 ohm | 12.4 / 12.7 dB | 2.5 / 6.1 dB | -10 / -7 dB | no limit | - |
| AN-1 control: PM with Cpx = 0 | 54.4 deg | 88.4 deg | +34 deg | control (must be low) | see caveat 2 |
| PR-2 pin, powered, +12 / -12 V in | 3.292 / 0.0072 V | 3.221 / 0.0020 V | -71 / -5 mV | -0.2 .. 3.45 V | no |
| PR-1 edge: peak input-diode current, no Rnp | 5 mA | 3 mA | -2 mA | <= 10 mA | no |
| supply current, two amplifiers | 16.04 mA | 13.00 mA | -19 % | (budget uses its own IQ) | - |
| +3.3 V source -> pin, 10 Hz / 1 MHz / 10 MHz | -128.8 / -70.7 / -79.5 dB | -79.7 / -41.4 / -50.3 dB | +49 / +29 / +29 dB | LED task | - |
| 10 uV step on +3.3 V source: pin peak / final | -2.2 / +0.004 nV | +64.0 / +1.03 nV | | 1 LSB = 806 uV | no (8e-5 LSB) |
| 0.3 mA step drawn at the amplifier rail (30 uV): pin peak / final | +8.1 / -0.03 nV | -257 / -2.8 nV | | 1 LSB = 806 uV | no (3e-4 LSB) |

Supply rows: `tph/supply.py`, the board's rail network (`netlib.rails`: 0.1 ohm + 10 nH, 100 nF + 1 uF at the amplifier).
The steps are computed from the small-signal transfer (AC lin 10 Hz-200 MHz, inverse sine transform; its rail node settles to
9.9976 uV for 10 uV, so 0.02 % integration error), because a transient at reltol 1e-7 resolves only ~160 nV at 1.6 V. With
PSRR_DB=120 (datasheet typ) the clean model reads -107.4 dB at 10 Hz but the same -41.4 dB at 1 MHz: above a few kHz its
supply coupling follows its open-loop gain, not PSRR_DB.

**Verdict: yes, with caveats.** No board verdict changes. Caveats:
1. Pass `VSREF=3.3` and, for noise, `EN=6.5n` (default noiseless).
2. Stability: different loop shape (PM ~116 deg with GM 2.5-6 dB, against ~70 deg and 12 dB). It is the optimistic model for
   PM, so AN-1 must keep BEH21/BEH60 (it does), and the Cpx = 0 control does not fire on the clean model alone (88 deg).
3. Bandwidth ~20 % lower, THD 15-17 dB worse, supply rejection 30-50 dB worse, noise lower (6.5 against 9.3 nV/rtHz, and no
   rise above 10 MHz): all inside limits; the noise difference is the one in the optimistic direction.
4. Over-range output stops at 3.22 V, not 3.29 V (its input CM clamp): PR-2 moves 71 mV the safe way.

## 2. REF3030E: REF3030E_OPEN against the board's stand-in (vendor model unreadable)

`ref/ref_cmp.py`: VIN 3.3176 V ideal; 1 uF + 100 nF, 20 mohm ESR each, on both (as `netlib.rails`). Loads from
`v2/sim/powercal/power.py` budget(): scope centre 10.8 uA, ladder 1.535 mA, worst total 2.542 mA (AWG at its window bottom),
AWG offset-path change 0.634 mA; and docs/afe.md PA-9's "about 2.3 mA" ladder.

| figure | stand-in (3.0 V, 0.05 ohm) | clean-room | difference | requirement, limit | verdict changes? |
|---|---|---|---|---|---|
| DC out, no load | 3.000000 V | 3.0000003 V | +0.3 uV | 3.000 V +-0.2 % (budget) | no |
| DC out at 10.8 uA / 1.535 / 2.3 / 2.542 mA | 2.9999995 / 2.9999233 / 2.9998850 / 2.9998729 V | 3.0000002 / 2.9999864 / 2.9999795 / 2.9999773 V | load reg -50.0 vs -9.0 uV/mA | 15 ppm/mA max = 45 uV/mA | no |
| line, 3.22 -> 3.42 V | 0 | 16.0 uV/V | +16 uV/V | 240 uV/V max | no |
| line rejection 100 Hz / 10 kHz / 1 MHz | ideal | -95.8 / -98.8 / -98.7 dB | | none | - |
| Zout, part alone: 100 Hz / 1 kHz / 10 kHz / 100 kHz / 1 MHz | 0.05 ohm flat | 17.4 / 115.6 / 5.6 / 0.56 / 0.057 ohm | up to x2300 | none in the sims | see below |
| Zout with 1 uF + 100 nF, same points | 0.050 / 0.050 / 0.050 / 0.050 / 0.046 ohm | 17.6 / 80.7 / 4.1 / 0.40 / 0.041 ohm | | | see below |
| load step 0 -> 2.3 mA, 100 ns edge: peak dip | 0.117 mV | 112.3 mV | x960 | none | see below |
| AWG offset-path step 0.634 mA: peak dip | 0.032 mV | 31.0 mV | x960 | none | see below |
| noise 10 Hz-10 kHz | not in the deck (netlib adds ref30.pdf's 51 uV) | 53.2 uV (NOISE=1) | +4 % | SC-6, REF share | no |
| SC-9 via the shared REF, scope deck, 100 Hz / 1 kHz / 1.9 kHz / 10 kHz / 10 MHz | 1.5e-4 / 1.5e-4 / 1.5e-4 / 1.2e-4 / 6.3e-6 LSB | 0.052 / 0.237 / 0.079 / 0.0099 / 6.3e-6 LSB | up to x1600 | <= 2 LSB | no |

The clean Zout is its fit to the datasheet Fig 6-14 "5 V, open" curve (its PROVENANCE.md line 21; FACTS.md line 107: 115 ohm
peak at 1 kHz), so the kHz difference is the stand-in's omission rather than a clean-model error; at 1-10 MHz, where SC-9's
strays act, the two agree within 10 %. The step peaks are the full current into that impedance; settled values are not quoted
because the clean model was still drifting 37-66 uV/ms 8 ms after a `uic` start. SC-9 rows: `ref/scope_ref_xt.py` (its stand-in
arm reproduces run.py's 10 MHz figure, 6.277e-6 LSB, exactly).

Defect found: the clean model's transient **stalls when started from its operating point with the output capacitors on**
(timestep ~0.1 ps; 10 us not reached in 100 s, with gear and with trap). It runs without the capacitors, and with `uic`.

**Verdict: not validated against a vendor model (none readable).** Against the board's stand-in it changes no verdict computed
here (DC within 0.1 mV; SC-9 at most 0.24 LSB of 2), but it is three orders more pessimistic at 100 Hz-10 kHz, so any study of a
kHz disturbance on VREF (AWG offset path, ladder, the 1.9 kHz LED task) will read very differently with it. Usable with the
caveat of `uic` until the operating-point stall is fixed, and with the 5 V curve as a stated (check) for a 3.0 V part.

## 3. LM27762: LM27762_OPEN (switching) and _AVG against TI's LM27762_TRANS.LIB

`lm/lm_cmp.py`. TI's file patched `ddrs` by the repository's `whatif/lm27762/patch_lib.py` (source pointed at the main checkout,
copy in `lm/scratch/`, not committed), `ngbehavior=ps`, `method=gear abstol=1e-3`, max step 0.5 us, as `lm_tran.py`. Clean:
plain ngspice, max step 20 ns. Same deck otherwise: VIN via 0.2 ohm + R406 1 ohm, C401+C402, C409 as 0.63 uF (lm_tran.py),
CPOUT / OUT+ / OUT- 2 x 10 uF each derated by the C15850 DC-bias curve x 0.9 (`models-open/cl21a106kaynnne/dcbias.csv`, the data
the earlier studies used), loads as resistors.

`su525` (both ran; the case `lm_results.json` records as converged): VIN 5.25 V, feedback scaled for TI's 1.216 V reference
(R1 181.06k, R3 68.83k, R2 = R4 = 100k), loads 39.89 / 40.16 mA, 1.6 ms. My vendor run reproduces the committed one
(`v2/sim/powercal/lm_results.json` su_5.25_max: OUT+ 3.4177 V, t90 0.287 / 0.498 ms, OUT+ pp 0.165 mV).

| figure | vendor | clean-room (switching) | difference | requirement, limit | verdict changes? |
|---|---|---|---|---|---|
| OUT+ DC (same resistors) | 3.41817 V | 3.37088 V | -47.3 mV (-1.38 %) | power.py corners use the datasheet 1.2 V +-1.5 %, not a model | no |
| OUT- DC | -2.05575 V | -2.05794 V | -2.2 mV | as above | no |
| CPOUT DC | -5.0080 V | -4.8891 V | +119 mV | - | no |
| VIN current | 80.78 mA | 80.61 mA | -0.2 % | PW-1 (budget) | no |
| OUT+ / OUT- ripple pk-pk (last 200 us) | 0.158 / 0.053 mV | 0.372 / 0.225 mV | x2.4 / x4.3 | PW-2 <= 20 mV at a supply pin | no |
| CPOUT ripple pk-pk | 24.3 mV | 12.2 mV | x0.5 | - | no |
| pump line | 2.14 MHz | 2.00 MHz | -7 % | PW-2/fsw: 1.7-2.3 MHz | no |
| OUT+ line at the pump frequency (peak) | 0.22 uV | 3.38 uV | x15 | - | - |
| start-up, OUT+ / OUT- to 90 % | 287 / 498 us | 123 / 123 us | -164 / -375 us | PW-7 <= 15 s | no |
| start-up overshoot OUT+ / OUT- | 77.6 / 26.5 mV | 0.22 / 0.13 mV | | none | see caveat |
| OUT+ max / bare supply max (OUT+ - OUT-) | 3.4958 / 5.5003 V | 3.3711 / 5.4291 V | -125 / -71 mV | (info: TPH2502 VS max 5.5 V) | see caveat |

Board feedback values (R401 120k/R402 68k, R403+R404 64.2k/R405 100k), VIN 5.0 V, 1.5 / 1.3 ms. Clean only; TI's stalled.

| figure | vendor | clean-room switching | clean-room AVG | requirement, limit | verdict changes? |
|---|---|---|---|---|---|
| OUT+ / OUT- DC, idle loads 35.78 / 15.49 mA | not run (stalled at 380 us) | 3.31637 / -2.00268 V | 3.31637 / -2.00268 V | power.py nominal 3.3176 / -2.0032 V | n/a |
| OUT+ / OUT- / CPOUT ripple pk-pk, idle | not run | 0.88 / 0.45 / 30.0 mV | 0.0004 / 0.0003 / 0.0004 mV | PW-2 <= 20 mV | n/a |
| OUT+ +1 mA step: min / settled | not run | -0.65 / -0.07 mV (ripple 0.81 pk-pk before) | -0.043 / -0.038 mV | none | n/a |
| OUT+ further +10 mA: min / settled | not run | -0.96 / -0.36 mV | -0.43 / -0.38 mV | none | n/a |
| AWG bottom -> top (OUT+ +19.2 mA, OUT- -19.9 mA): OUT+ min / settled | not run | -1.39 / -0.76 mV | -0.78 / -0.78 mV | SC-9/AC hand figure uses 2.00 mV | n/a |
| same, OUT- min / settled | not run | -0.95 / -0.84 mV | -0.83 / -0.83 mV | none | n/a |
| start-up OUT+ / OUT- to 90 % | not run | 124 / 124 us | 124 / 124 us | PW-7 <= 15 s | n/a |

The AVG variant overflows (`2.79642e+225 out of range for ^` in `b.x1.xc.bpn`, the `(I/ILIM)^40` term) at a 0.5 us maximum
step with `uic`; it runs at 20 ns. TI's model has no LDO loop (lm_tran.py's header), so its load-step response would not have
been a like-for-like comparison even had it run.

**Verdict: yes, with caveats, on the evidence available.** On the one case both models ran, no PW-2 / PW-7 verdict changes;
the clean model runs in ~10 s where TI's takes 5 min or never finishes on the board's values. Caveats:
1. Its DC follows the datasheet's 1.2 V / -1.22 V references, TI's 1.216 V: OUT+ reads 1.4 % lower on the same resistors.
   Board deck feedback values must not be the ones lm_tran.py scaled for TI's model.
2. It has no start-up overshoot; TI's shows 78 mV on OUT+ and puts the AWG dual's bare supply at 5.5003 V at the 5.25 V corner.
   No verdict uses that figure, but a start-up stress check should not rely on the clean model.
3. Ripple shape differs (rails 2-4x higher, CPOUT half); both are far inside PW-2's 20 mV.
4. Load steps could not be compared against TI's model at all.

## Re-run

```sh
P=/home/jerry/Engieering.Projects/due_oscilloscope/.venv/bin/python
V=/tmp/claude-1000/-home-jerry-Engieering-Projects-due-oscilloscope/414e1c8e-ed6e-4b30-ae4a-0ad5da56bfbc/scratchpad/validate
# TPH2502 (~3 min per model; cscan must precede mc/guards)
cd $V/tph
for m in vendor clean; do
  $P run_swap.py $m $V/tph/$m dc ac bw noise d17 tran stab xtalk static prot
  $P run_swap.py $m $V/tph/$m cscan beh mc guards
  $P report_nonefix.py $V/tph/$m            # writes $V/tph/$m/report.md
done
$P supply.py $V/tph/supply.json; python3 table.py
# REF3030E
cd $V/ref; ngspice -b vendor_try.cir; $P ref_cmp.py; $P scope_ref_xt.py
# LM27762 (clean ~10 s per case; TI su525 ~5 min, the board cases stall)
cd $V/lm
for c in su525 idle_steps awg_step; do for m in clean avg vendor; do $P lm_cmp.py run $c $m; done; done
$P lm_cmp.py analyse                         # writes lm_cmp.json
```
