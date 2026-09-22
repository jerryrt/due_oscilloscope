# Stage A electrical screening

The schematic is the circuit source. `run.py` exercises the established
five-analysis baseline; `screen.py` exports it again and applies explicit,
simulation-only source/load and candidate overlays. Neither edits the
schematic or qualifies hardware.

Run from the repository root with KiCad 10.x and ngspice installed:

```sh
hardware/afe-shield/sim/run.sh
hardware/afe-shield/sim/run.sh --strict
python3 hardware/afe-shield/sim/screen.py
python3 -m unittest discover -s hardware/afe-shield/sim -p test_screen.py -v
```

| Command | Meaning of success or failure |
|---|---|
| `run.sh` | Exit 0 means analyses and broad operating-point sanity checks completed; REVIEW lines remain unresolved |
| `run.sh --strict` | Exit 2 means an existing bandwidth, full-step settling or AREF disturbance check failed; exit 1 indicates a tool/data/sanity failure |
| `screen.py` | Exit 0 means the requested screening cases completed, not that their diagnostic checks passed; inspect the printed findings and JSON booleans |
| Unit tests | Check measurement arithmetic and refusal paths without KiCad, ngspice or a board |

No exit code means fabrication-ready. Formal flatness limits, the complete
error allocation and bench requirements still need review. The strict
baseline preserves the existing 1 dB/5 MHz and one-code screening checks;
it does not silently redefine the project's requirements.

## What is in the screen

The default model is the active MCP6024. The screen preserves the exported
schematic topology and values, apart from declared tolerance/model
overlays; it refuses if expected RC values or the model selection have
changed. It uses the **open-JP1** configuration, without the ADVREF load.
This differs from the baseline's closed-link reference-load experiment.

| Case group | Conditions | Scope |
|---|---|---|
| Nominal | 3.3 V, 27 C, 68 ohm / 470 pF | DC supply current, AC gain and both polarities of a 2 V step |
| Supply | 3.135 V and 3.465 V | One-factor +/-5% supply sensitivity, not an approved supply specification |
| Temperature | -20 C and 70 C | Modelled typical behaviour, not process limits |
| Passive values | R +/-1%, C +/-5%, low/low and high/high | Selected RC sensitivities, not exhaustive independent combinations |
| Wiring | 100 nH and 1 uH in series with 0.1 ohm and an 8 pF pin-load allowance | Assumed parasitics, not extracted geometry; 1 uH is a severe stress case |
| Stock DAC window | 0.55 to 2.75 V | Step-span sensitivity; ideal source, not a full stock-Due model |
| Sampling load | Constant inputs at 2.5 V and 0.5 V; opposite initial sampling-capacitor voltages | Recovery from a deliberately large charge-sharing step in each polarity |
| Time-step convergence | 2 ns versus 1 ns for the nominal sampling case and severe-wire step case | Numerical sensitivity, not model validation |

The diagnostic code-voltage convention is fixed at 3 V / 4096 throughout,
including the stock-DAC-span stress case. This does not claim that a stock
Due's actual reference is 3 V. Input steps use ideal sources with 1 ns
edges; real DAC dynamics and output impedance are not represented.

The screen saves each generated deck, log and trace under the ignored
`screen-output` directory, separated by model selection. The summary
records results, diagnostic checks, exact tool versions and input-source
hashes. A failed run removes the previous summary before starting and
does not publish a successful summary. Logs remain available on failures
and timeouts. Copy only deliberately accepted evidence into a versioned
review; do not treat a leftover individual trace as a successful run.
The [retained review snapshot](../reports/driver-screen.json) is one such
record, including failed diagnostic checks rather than only passing rows.

## Acquisition model and its limits

The official [SAM3X/SAM3A 11057C datasheet](../../../docs/datasheets/microchip/SAM3X-SAM3A-11057C.pdf),
section 45.7.2.1, gives the 12-bit tracking requirement:

```text
t_track_ns = 0.054 * source_resistance_ohm + 205
```

For its first case it specifies TRANSFER=1, TRACKTIM=0 and uses a
15-ADC-clock acquisition assumption. At 19.5 MHz that is approximately
769.23 ns, not the 1.129 us sample interval and not one ADC clock.
Confirm the relevant sequencing and register settings before applying
this to a physical acquisition. No firmware settings are changed here.

The simplified switched-RC load fits that relation using an **assumed**
half-LSB endpoint for a full-scale 12-bit step:

```text
C_sample_fit = 0.054 ns/ohm / ln(8192) = approximately 5.99 pF
R_on_fit     = 205 / 0.054            = approximately 3.80 kohm
t_settle    = ln(8192) * (R_source + R_on_fit) * C_sample_fit
```

These are inferred surrogate parameters, **not published silicon values**.
The additional 8 pF pin-load allowance is separate and may conservatively
overlap capacitance represented by the fit. This is not a transistor-level
ADC model. It omits conversion kickback, nonlinear switching resistance,
the real shared multiplexer sequence, leakage variation and package/board
coupling. It cannot establish noise, crosstalk, distortion or hardware
sampling accuracy.

Two independent sample capacitors exercise opposite charge histories;
they do not imply two ADCs on the Due. The inputs are held constant and
the drivers have settled before the sampling switches close. Consequently
this experiment does **not** replace the separate full-input-step test.

Dynamic error is measured relative to the pre-acquisition pin voltage;
total error is measured relative to the ideal source voltage. Keeping
them separate prevents DC offset from being hidden inside a settling
claim. Values are interpolated immediately before switch opening, never
after a convenient extra settling interval. The 210 ns case is a shorter
stress/negative-control window, not an asserted SAM3X configuration.

The step measurement uses the first in-band sample after the **last**
excursion, and rejects an insufficiently stable final plateau rather than
printing a reassuring settling time. Numerical options include tight
tolerances, a 1 Tohm node shunt and operating-point initial guesses;
these aid solving and are not physical BOM elements or power-on evidence.

## Candidate evaluation

```sh
python3 hardware/afe-shield/sim/screen.py --quick --model opa4350
```

The candidate uses TI's own OPAx350 library through `models/candidates.lib`.
It represents replacing all four channels with the SOIC-14 OPA4350,
not a mixed-MCP/TI physical IC. The active KiCad model and BOM do not change.

In the ngspice 47 check, the integrated candidate failed to establish its
operating point: gmin/source stepping failed, followed by transient-OP
failure or timeout. An isolated single-channel operating-point test was
able to converge. This leaves model integration unresolved; it establishes
neither good candidate performance nor a physical instability. Do not
loosen tolerances until a plot appears and then promote that plot to proof.

Before any selection change: resolve reproducible model operation, check
the reference/mid-rail behaviour as well as the signal drivers, review
power and thermal load, exact ordered package, decoupling, noise and
real-board measurements. A same-pinout part is not automatically a
qualified replacement.
