# v1 LM27762 capacitor distance: ripple by v2's AC analysis (LR-5 deviation evidence)

What it computes: v2's `v2/sim/powercal/pw2_ac/pw2_ac.py` (read its README first) with v1's capacitor geometry. TI's transient model
cannot take series L, so v2's ideal transient (stored window, `v2/.../results/transient_ideal_window.npz`, not re-run) is decomposed into
lines and each rail's real network (ESR(f), ESL 0.373 nH, the mounting loop L of each capacitor, in parallel) is applied line by line.
`pw2_ac_v1.py` imports v2's module and replaces its tables (distance, pin-link width, GND vias per capacitor); nothing of v2's is copied
or edited. Results: `../results/pw2_ac_v1.json`. Tests: `tests/test_v1_pw2_ac.py` (numpy only; no ngspice, the transient is not re-run).

## Run (repository root; image only)
    docker/pcb/run.sh -m 3G -c 2 -t 300 bash -c 'cd /work/hardware/afe-proto && python3 -I v1/sim/pw2_ac_v1.py'
    docker/pcb/run.sh -m 3G -c 2 -t 300 bash -c 'cd /work/hardware/afe-proto && python3 -m pytest -p no:cacheprovider -c tests/pytest.ini tests/test_v1_pw2_ac.py -q'
    docker/pcb/run.sh -m 3G -c 2 -t 200 bash -c 'cd /work/hardware/afe-proto && python3 -I v1/sim/pw2_ac_v1_geom.py kicad/afe-proto.kicad_pcb'   # the geometry (needs pcbnew)
2.5 s, 32 MB.

## Distances, and how a distance becomes L (as v2 does)
Distance = pad centre of the cap's own pad to the nearest same-net U401 pad centre (`pw2_ac_v1_geom.py`, `kicad/afe-proto.kicad_pcb`; agrees with
the POWER agent's table). L = L'(w) x d + L_via / n_vias: microstrip over the plane (Hammerstad-Jensen, h 1.6 mm, er 4.5 *(check)*; L' 0.832
nH/mm at 0.2 mm, 0.751 at 0.3 mm, ~0.79 at 0.25) plus Johnson's via 1.30 nH *(check)* / GND vias within 1.5 mm of the GND pad (1 each on v1). No mutual L.
w = width of the track segment on the cap's net touching its pad (same tool).

| rail (pin) | cap | d v1 mm | w mm | L v1 nH | d std mm | L std nH |
|---|---|---|---|---|---|---|
| VIN (3,8,12) | C403 / C404 | 2.81 / 5.07 | 0.3 | 3.41 / 5.11 | 3.5 / 5.5 | 3.93 / 5.43 |
| CPOUT (5) | C405 / C406 | 10.35 / 12.45 | 0.2 | 9.92 / 11.66 | 3.5 / 5.5 | 4.21 / 5.88 |
| OUT+ (11) | C407 / C408 | 5.55 / 5.76 | 0.25 | 5.67 / 5.84 | 3.5 / 5.5 | 4.06 / 5.63 |
| OUT- (6) | C409 / C410 | 6.16 / 8.26 | 0.25 | 6.15 / 7.81 | 3.5 / 5.5 | 4.06 / 5.63 |
| VIN 100n | C401 | 7.86 | 0.3 | 7.9 | 5.5 | |
| flying | C402 | 2.87 | 0.2 | 3.69 (in no bank, as in v2) | | |

v1's slots map onto the module's (v2's part names: C403->C401, C404->C402, C405/6->C403/4, C407/8->C405/6, C409/10->C407/8, C402->C409).
The module's banks are two equal capacitors each (10u at the deck's derating). The 100n (C401) is added as a separate case: C 100 nF, ESR 30 mohm,
ESL 0.5 nH, no derating, all *(check)* (v1 design.py: C401 100n X7R, C403/C404/C405-C410 10u, C402 1u; v1's X5R/25 V derating is v2's deck's).

## Sources of the drive (not v1's own)
The pump current is **v2's transient**: same LM27762, VIN 5.25 V, feedback at v2's max corner, loads from v2's `power.budget`. v1's own rail loads
(and feedback 175k/100k, 75k+100k=-2.052 V) were not re-derived: the injected current on OUT+/OUT- is tiny in this model, so the rails are insensitive *(check)*;
f_pump 2.13 MHz (model), 1.7/2.0/2.3 MHz scaled; band limit 30 MHz and the 10-30 MHz VIN content unvalidated, as in v2. Every limit is v2's: PW-2 20 mV pk-pk.

## Results (mV, worst of 1.7-2.3 MHz, as-built L; ideal = no loop L)
| rail | v2 as-built | v1 | standard 3.5 / 5.5 | ideal |
|---|---|---|---|---|
| OUT+ (+3V3A) pk-pk, limit 20 | 0.138 | **0.140** | 0.139 | 0.132 |
| OUT- (VNEG) pk-pk, limit 20 | 0.049 | **0.050** | 0.048 | 0.044 |
| VIN pk-pk (10u banks only; 30 MHz limit) | 133.1 | **93.6** | 101.2 | 23.5 |
| VIN, plus the 100n (check) | | 74.5 | 73.4 | 23.2 |
| CPOUT pk-pk (not PW-2) | 195 | **361** | 169 | 31 |

In band (as-built, worst of range; rms / pk-pk): VIN DC-1 MHz v1 5.71 / 18.3 (standard 5.71 / 18.3; ideal 5.75 / 18.8; v2 5.70 / 18.0): unchanged by distance. VIN 1-10 MHz
2.04 / 12.5 (std 2.27 / 13.8, ideal 0.40 / 2.2); 10-30 MHz 7.7 / 85 (std 8.4 / 93, ideal 0.69 / 7.2). OUT+ DC-1 MHz 0.046 / 0.130, 10-30 MHz 0.003 / 0.025;
OUT- DC-1 MHz 0.015 / 0.043, 10-30 MHz 0.002 / 0.023. Pump harmonics k = 1..4 (pk-pk, model f): VIN v1 3.8 / 2.1 / 6.6 / 2.9 (std 4.4 / 2.3 / 7.3 / 3.2; ideal 1.2 / 0.23 / 0.63 / 0.26);
OUT+ and OUT- <= 0.003 at every k. CPOUT v1 15 / 6.6 / 21 / 8.6 (std 6.1 / 3.1 / 9.9 / 4.1).

Verdicts (module's rule): OUT+ and OUT- **pass with margin** (0.14 and 0.05 mV against 20), but as in v2 this is the model's LDO talking, not a margin: the model
injects ~0.3 mA into OUT+ and cannot resolve distance there (L x0.5 / x2: 0.14-0.15 and 0.05-0.06). VIN is **not judged against 20 mV** (as v2: wideband content unvalidated;
no PW-4 pass); its in-band DC-1 MHz figure equals the ideal's. v1 VIN (2.8 / 5.1 mm) is nearer than the standard's 3.5 / 5.5, so it reads below it. **The cost of v1's deviation
is at CPOUT only** (C405 10.4 mm, C406 12.5 mm): 361 against 169 mV with the standard, and 195 for v2; CPOUT is not a PW-2 node and it is the pump's own output
(feeds the LDOs, whose PSRR is not modelled). VT-8 measures it.

## Controls (broken on purpose, and the guards)
C403 + 10 mm: VIN 93.6 -> 139.4 mV (test asserts > 1.3x). C405 + 10 mm moves CPOUT only. v2's own geometry through the same code reproduces v2's JSON to 1e-9
(133.062 / 195.161 / 0.1379 / 0.0494), and the tables are restored after every run.
