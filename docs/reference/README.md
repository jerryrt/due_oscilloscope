# Official hardware and KiCad references

Original publisher files are retained in the repository for offline reading
and reproducible design review. Do not edit the PDFs or vendor model files.
[`sources.json`](sources.json) records download URLs, retrieval date and
SHA-256 hashes. Publisher copyright and model license terms still apply.

| local reference | use |
|---|---|
| [MCP6021/2/3/4 datasheet](../datasheets/microchip/MCP6021-DS20001685F.pdf) | Stage A candidate limits, PDIP/SOIC pinouts, output drive and decoupling |
| [Microchip AN1297](../datasheets/microchip/AN1297-Op-Amp-SPICE-Models.pdf) | Model capabilities and limitations |
| [Microchip AN884](../datasheets/microchip/AN884-Capacitive-Loads.pdf) | Capacitive-load stability and isolation |
| [TI LM4040-N datasheet](../datasheets/ti/LM4040-N.pdf) | Candidate D101 MPN, grade, bias and pinout |
| [ASSMANN DIP socket drawing](../datasheets/assmann/Axx-LC-TT.pdf) | Low-cost socketed prototype dimensions; working assembly socket/package check |
| Yageo [56 ohm](../datasheets/yageo/RC0805FR-0756RL.pdf), [10 kohm 1%](../datasheets/yageo/RC0805FR-0710KL.pdf), [10 kohm 0.1%](../datasheets/yageo/RT0805BRD0710KL.pdf), [68 ohm](../datasheets/yageo/RC0805FR-0768RL.pdf), [470 pF](../datasheets/yageo/CC0805JRNPO9BN471.pdf) | Prototype passive purchasing specifications |
| Murata [10 uF](../datasheets/murata/GRM21BR71A106KE51.pdf), [1 uF](../datasheets/murata/GRM21BR71H105KA12.pdf), [100 nF](../datasheets/murata/GRM21BR71H104KA01.pdf) | Prototype capacitor sizes, ratings and handling cautions |
| [TI LM4040 datasheet](../datasheets/ti/LM4040.pdf) | Related family comparison; not the selected -N model's specification |
| [TI OPA4350 datasheet](../datasheets/ti/OPA4350.pdf) | Evaluation candidate only: SOIC-14 pinout, driver performance, power and layout requirements; not an approved substitution |
| [SAM3X/SAM3A 11057C datasheet](../datasheets/microchip/SAM3X-SAM3A-11057C.pdf) | Section 45.7.2.1 acquisition-time/source-impedance relation; retained separately from the older 11057B reference |
| [Arduino Due full pinout](../datasheets/arduino/Arduino-Due-full-pinout.pdf) | Connector signals and alternate functions |
| [Arduino Due schematic](../datasheets/arduino/arduino-due-schematic.pdf) | Board wiring, separate I2C buses, JR1/BR1 and AREF network |
| [Arduino Due V03 PCB in KiCad](../../hardware/reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb) | Working reference for the owner's DUE R3 board, selected from its reported six-pin IC2 and separate-inductor layout; [evidence and limits](../../hardware/reference/arduino-due/README.md) |
| [Arduino Due V02g archive](../../hardware/reference/arduino-due/v02g/README.md) | Alternate EAGLE/KiCad revision for comparison, with source hashes and checks |
| [Due mechanical models](../../hardware/reference/arduino-due/models/README.md) | V03 has 119 model assignments from the supplied assembly, standard KiCad packages and simplified special parts; sources, approximations and bare NM/fiducial sites recorded |
| [KiCad 10 schematic manual](kicad-10/eeschema.pdf) | Hierarchy, search, symbol fields, ERC and simulator |
| [KiCad 10 PCB manual](kicad-10/pcbnew.pdf) | Footprint update, routing, DRC and fabrication outputs |

The existing Arduino reference-design archives and SAM3X datasheet remain in
`docs/datasheets/`; the manifest identifies the newly downloaded references,
not an assertion that every pre-existing reference has been re-downloaded.

The old `hardware/afe-shield/models/` files are currently absent. Their
manifest entries retain historical source URLs/hashes, not proof of current
local availability. Follow the [AFE model plan](../../hardware/afe-proto/models/README.md)
to establish libraries under the new project before simulation.
