# AFE shield

Stage A schematic for the Arduino Due analog front end. Verified with
KiCad 10.0.6 and ngspice 47. **KiCad 10.x is the default and required CAD
major version on every team/bench.** Do not edit or validate this project
with KiCad 9 or older. **Design/prototype only: not ready for
fabrication.** See [review findings](REVIEW.md), [requirements](../../docs/afe.md)
and [official references](../../docs/reference/README.md).

For the end-to-end process, read
[AFE design with KiCad: workflow and quality gates](../../docs/afe-workflow.md).

| file | what |
|---|---|
| `afe-shield.kicad_pro`, `afe-shield.kicad_sch` | project and root sheet: Mega-format mechanics with Due-specific net assignments |
| `reference.kicad_sch` | Stage A: the LM4040 reference, its buffer, the mid-rail, the AREF jumper |
| `pin-driver.kicad_sch` | Stage A: the followers from DAC0 and DAC1 into A0 and A1, VREF1V5 onto A2, the unused pins held |
| `afe-shield.kicad_pcb` | the template's board outline, headers and holes; the PCB phase draws on it |
| `models/afe-models.lib` | pin-order adapters for the original Microchip and TI models in `models/vendor/` |
| `sim/sources.cir` | simulation-only Due supplies, DAC stimuli and AREF load; included by root schematic text |
| `sim/stage_a.cir`, `sim/run.sh` | DC, AC, settling and reference-load checks using the exported schematic |
| `stage-a.wbk` | KiCad operating-point analysis setup |
| `check.py` | ERC and critical connector/analog-net regression checks |

## Finding D1 and the Phase A IC

Open **afe-shield.kicad_pro**, then its Schematic Editor, not the PCB Editor.
Enter the **reference** sheet by double-clicking its rectangle on the root
sheet. **D1** is at the upper left, below R1: the LM4040 3.0 V shunt reference.
Its label is horizontal and readable. Find (`Cmd+F` on macOS) can search D1;
enable searching all sheets when searching from the root.

**U1 is one physical MCP6024 quad IC**, drawn as five units:

| unit | sheet | function |
|---|---|---|
| U1A | reference | 3.0 V reference buffer |
| U1B | reference | 1.5 V mid-rail buffer |
| U1E | reference | supply pins 4 and 11, with C4 decoupling |
| U1C | pin-driver | DAC0 follower into A0 |
| U1D | pin-driver | DAC1 follower into A1 |

D1 and U1 are not on the PCB yet. It contains the template headers and
mounting holes only; their absence there is not a search problem.

## Running the checks

From the repository root:

```sh
python3 hardware/afe-shield/check.py
hardware/afe-shield/sim/run.sh
```

Requires Python 3, KiCad 10.x `kicad-cli` and `ngspice`. Both check scripts
reject a different KiCad major version before exporting or checking files.
The runner discovers the macOS
KiCad app automatically, or accepts `KICAD_CLI` / `NGSPICE` executable paths.
When multiple KiCad installations exist, set `KICAD_CLI` explicitly to the
10.x executable and open the project in the corresponding GUI. Use matching
10.x symbol/footprint libraries; record the exact patch version with results.
Some source files retain KiCad 9 serialization until saved by KiCad 10;
their generator tags are provenance, not the supported toolchain version.
Generated netlists, logs and numeric `.dat` traces stay in `sim/` and are
ignored by Git. Exit zero means the analyses completed and basic reference
sanity checks passed; **REVIEW messages are unresolved performance targets**.

In KiCad, open **Inspect → Simulator → File → Open Workbook**, choose
`stage-a.wbk`, and run the operating-point analysis. In **Simulation → Edit
Analysis Tab**, choose **PSpice** compatibility and keep **Add full path for
.include library directives** enabled. This setup was run in the GUI as well
as from the command line. Create further tabs with **Simulation → New Analysis
Tab**: AC (decade, 100 points, 1 kHz to 100 MHz), or transient (2 ns, 40 us).
Plot `V(a0)`, `V(dac0)`, `V(buffer)` and `V(vref3v0)` as appropriate.

The GUI defaults to the nominal static AREF load. The batch deck additionally
sets `AREF_C=200n` and reruns the load-step stress test. Supplies and test loads
are simulation-only, never physical PCB parts.

**JP1 stays open by default.** Do not close it on a Due with JR1 still fitted.
The alternative AREF connection requires the documented Due modification and
reference-load stability validation; see the review before wiring hardware.
