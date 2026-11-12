# JLC Basic passives for AFE version 2

The parts V2-3 (`docs/afe-v2.md`) lets the design use: every resistor and
capacitor in JLC's **Basic** library, read from JLC's own servers on
2026-11-12, with the diodes noted for MC-12. The full list, one row per part,
is `jlc-basic.csv`; this file says how it was read, what it contains, and
answers the questions version 1's values raise.

**Short answer.** The Basic resistor library is small and uniform: 182
parts, all UNI-ROYAL thick film, all ±1 %, **79 distinct values from 1 Ω to
10 MΩ, every one of them in 0603**, at ±100 ppm/K from 20 Ω up. There is no
Basic resistor better than 1 %. Of version 1's six precision values, **100k,
330k and 49.9 Ω exist as Basic 0603**; 174k, 953 Ω and 249 Ω do not, and each
is reached by a two-part combination (174k exactly). A 50 Ω back-termination
within ±1 % that survives the output short is **two 100 Ω 1206 in parallel**.

## 1. How the library was read

Three readings of JLC's own data, all public, no login, by `curl`:

| what | where | gives |
|---|---|---|
| **Enumeration** (international) | `POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`, JSON body `{"currentPage":n,"pageSize":100,"componentLibraryType":"base","searchSource":"search"}`, optionally with `"firstSortName":"Resistors","secondSortName":"Chip Resistor - Surface Mount"` (or `"Capacitors"`, `"Multilayer Ceramic Capacitors MLCC - SMD/SMT"`) | every Basic part: `componentCode` (LCSC number), `componentLibraryType` (`base` = Basic, `expand` = Extended), `preferredComponentFlag`, `attributes` (value, tolerance, tempco, power, voltage), `urlSuffix`, `dataManualFileAccessIdUrl` |
| **International part page** | `https://jlcpcb.com/partdetail/<urlSuffix>`, e.g. `.../partdetail/23955-0603WAF6800T5E/C23228` | the server-rendered record carries `componentLibraryType` |
| **Domestic part page** | `https://www.jlc-smt.com/lcsc/detail/<C-number>.html` | the server-rendered record carries `orderLibraryType` (`base` / `expand`); this is the service the board is ordered from |

The site is not JS-only for these: the API answers JSON, and both part
pages are server-rendered with the record embedded. Pages were read at
about 3 s each; the whole set takes about 25 minutes from one client.

**What the enumeration found on 2026-11-12:** 351 Basic parts in all, of which
182 chip resistors, 88 MLCCs, 3 resistor arrays, 2 tantalum capacitors and
14 diodes (switching, Schottky, rectifier). Every resistor, capacitor and
diode row (284) was then read on both part pages: **all 284 read `base` on the
international page and `base` on the domestic page**, and every domestic
record names the same manufacturer part. (12 domestic reads came back empty
the first time, apparently throttled, and read `base` on a retry.)

**The CSV.** Columns: kind, value, tolerance, package,
tempco_or_dielectric, voltage, lcsc, basic, mfr_part, date_read,
source_url, then three added: power (resistors), intl_library and
domestic_library (the raw `componentLibraryType` / `orderLibraryType`), and
domestic_url. `basic` is `yes` only when both pages read `base`.
`source_url` is the international part page; tolerance, tempco, voltage and
power are that page's attributes, not the datasheet's.

**Limits.**

- The enumeration is the **international** API. The domestic service has no
  equivalent that was found: its category pages (`/lcsc/<id>`) are rendered in
  the browser. So a part that is Basic domestically and not internationally
  would be missing here *(check, if a needed value is absent)*. Version 1's
  BOM showed the opposite direction only: two parts Preferred internationally
  (1.5 nF C1595, BAT54S C7420333) are plain Extended domestically, read again
  today. Only `base` counts for V2-3; the international Preferred tier does
  not exist domestically.
- **Stock** is not part of the evidence here (the domestic record shows
  `stockNum` 0 for every part); read it in the BOM matcher before ordering
  *(check)*.
- The library changes. Rerun before ordering:
  `selectSmtComponentList` with `componentLibraryType` `base`, then each
  `partdetail` and `lcsc/detail` page, comparing the library field.

## 2. Resistors

All 182 are UNI-ROYAL (Uniroyal Elec) thick film, ±1 % on the page. By
package: 80 in 0603 (`0603WAF`, 100 mW, 75 V), 57 in 0805 (`0805W8F`,
125 mW, 150 V), 30 in 0402 (`0402WGF`, 62.5 mW, 50 V), 15 in 1206
(`1206W4F`, 250 mW, 200 V). Ratings are the page's, and agree with the
datasheet's section 6 and 7.

**Values present, 1 Ω to 10 MΩ** (E24 grid; "--" is not Basic in any
package). Every value listed exists in 0603; 0.1 Ω (1206) and 0 Ω are the only
values outside this range.

| decade | values |
|---|---|
| 1 Ω | 1, 2, 2.2, 4.7, 5.1 |
| 10 Ω | 10, 20, 22, 33, 47, **49.9**, 51, 75 |
| 100 Ω | 100, 120, 150, 200, 220, 270, 300, 330, 390, 470, 510, 560, 680, 820 |
| 1 kΩ | 1, 1.2, 1.5, 1.8, 2, 2.2, 2.4, 2.7, 3, 3.3, 3.6, 3.9, 4.7, **4.99**, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1 |
| 10 kΩ | 10, 12, 13, 15, 18, 20, 22, 24, 27, 30, 33, 39, 47, **49.9**, 51, 56, 68, 75, 82 |
| 100 kΩ | 100, 120, 150, 200, 220, 300, 330, 470, 510 |
| 1 MΩ | 1, 2, 10 |

That is 76 of the 169 E24 values from 1 Ω to 10 MΩ, plus three E96-only
values (49.9 Ω, 4.99k, 49.9k): **79 values**. Of the 673 E96 values in the
range, 26 are present, all of them E24 values except those three. The gaps
widen at the ends: from 100k to 1M only nine values, and above 1M only 2M
and 10M, so a high-value network (1 MΩ inputs) is built from series parts.

**Tempco.** The page gives ±100 ppm/K for every value from 20 Ω to 10 MΩ in
every package. Below that the page gives ±200 or ±400 ppm/K (0603: 1, 2.2,
4.7 and 10 Ω at ±400; 2 and 5.1 Ω at ±200), and 33 Ω 0805 at ±200.

The datasheet JLC serves for these parts (the same file for C25803, C17408,
C17901, C25092 and C23185: UNI-ROYAL "Thick Film Chip Resistors, 01005 ...
2512 Series", V.3, Feb. 12 2019, section 11 "Performance Specification",
"Temperature Coefficient", test method 4.8 of GB/T 5729 / JIS-C-5201 /
IEC 60115-1) reads:

> 0402: 1≤R≤10: 200PPM/C; >10: 100PPM/℃
> 0603: 0.01Ω≤R≤0.03: 1500 PPM/C ... 1≤R≤10: 200PPM/C; >10: 100PPM/℃
> 0805, 1206, 1210, 2010, 1812, 2512: ... 1≤R≤10: 200PPM/C; >10: 100PPM/℃

So above 10 Ω the datasheet and the page agree at 100 ppm/K (no sign is
printed; read as ±). At 1 to 10 Ω in 0603 the page says ±400 where the
datasheet says 200, and 33 Ω 0805 is ±200 on the page against 100 in the
datasheet: **take the worse figure** for those *(check with UNI-ROYAL if it
matters)*. The datasheet gives no tracking (ratio) tempco, so two resistors
of one ratio are only known to drift within ±100 ppm/K each, in either
direction.

The same section's drift clauses for ±0.5 % and 1 % parts, worth having when
SC-7 and EN-1 are recomputed: load life 1,000 h at 70 °C ±(1.0 % + 0.05 Ω);
rapid change of temperature (100 cycles −55/+155 °C) ±(0.5 % + 0.05 Ω);
humidity steady state ±(0.5 % + 0.05 Ω); soldering heat ±(1.0 % + 0.05 Ω).
These are limits, not typical values.

**No Basic resistor is better than 1 %.** All 182 read ±1 % on the page; an
API keyword search for "0.5%" within Basic finds only the CJ431 reference,
and "0.1%" or "thin film" find nothing. (The datasheet lists a 0.5 % grade,
`D` in the seventh code, but no such part is Basic.)

### Version 1's precision values

Combinations below are of 0603 Basic parts unless stated; "error" is the
nominal value's error, before the parts' own ±1 %.

| v1 value | Basic of that value? | nearest single Basic | best combinations |
|---|---|---|---|
| 100k 0.1 % | **yes**: C25803 (0603), also C17900 1206, C25741 0402, C149504 0805 | - | - |
| 330k 0.1 % | **yes**: C23137 (0603 only) | - | - |
| 174k 0.1 % | no | 150k (−13.8 %), 200k (+14.9 %) | **150k + 24k = 174.0k, exact**; 75k + 100k = 175k (+0.57 %) |
| 953 Ω 0.1 % | no | 820 Ω (−14.0 %), 1k (+4.9 %) | **1k ‖ 20k = 952.4 Ω (−0.07 %)**; 1.2k ‖ 4.7k = 955.9 (+0.31 %); 270 + 680 = 950 (−0.31 %) |
| 249 Ω 0.1 % | no | 220 Ω (−11.6 %), 270 Ω (+8.4 %) | **270 ‖ 3.3k = 249.6 Ω (+0.23 %)**; 330 ‖ 1k = 248.1 (−0.35 %); 200 + 49.9 = 249.9 (+0.36 %); 100 + 150 = 250 (+0.40 %) |
| 49.9 Ω 0.1 % 1206 | **yes in 0603 and 0805, not 1206**: C23185 (0603, 100 mW), C17720 (0805, 125 mW), C25120 (0402) | - | see section 3 |

For the calibration ladder, which only needs equal steps, eight equal Basic
values (220 Ω or 270 Ω) avoid combinations altogether; the ladder's current
changes with the value, and that is the design's to check.

## 3. 50 Ω, and anything better than 1 %

**Single parts near 50 Ω**: 49.9 Ω (0603 C23185, 0805 C17720, 0402 C25120)
and 51 Ω (0603 C23197, 0805 C17738), both ±100 ppm/K. No 50 Ω part. A single
49.9 Ω is −0.2 % nominal, so with its own ±1 % it spans −1.2 to +0.8 % of
50 Ω: **outside AW-4's ±1 % at the low end** under a worst-case reading.

**Combinations exactly 50.0 Ω nominal**, so inside ±1 % worst case (series
and parallel of ±1 % parts stay within ±1 %):

| combination | parts | dissipation share | note |
|---|---|---|---|
| 100 ‖ 100 | C22775 0603, C17408 0805, C17901 1206 | equal halves | 1206 recommended (below) |
| 75 ‖ 150 | C4275 0603 (75 Ω only in 0603), C22808 0603 | 2/3 in the 75 Ω | |
| 4 × 200 ‖ | C8218 0603 | quarters | four parts |

**Rated for the short** (AW-4 asks for the short circuit of section 3.2).
`docs/afe-v2.md` gives about 64 mA through 50 Ω at the window's top end
(derived there, with the op-amp's own limit possibly lower). That is
0.064² × 50 = **0.205 W** in the termination (derived). Ratings are the
datasheet's at 70 °C ambient, derated above 70 °C (section 9):

| option | per part | rating | margin |
|---|---|---|---|
| single 49.9 Ω 0603 / 0805 | 0.205 W | 0.100 / 0.125 W | **fails** |
| 100 ‖ 100, 0603 | 0.102 W | 0.100 W | **fails** |
| 100 ‖ 100, 0805 (2 × C17408) | 0.102 W | 0.125 W | 82 % of rating, thin |
| 75 ‖ 150, 0603 | 0.137 W in the 75 Ω | 0.100 W | **fails** |
| 4 × 200 Ω 0603 (4 × C8218) | 0.051 W | 0.100 W | 51 % |
| **100 ‖ 100, 1206 (2 × C17901)** | 0.102 W | 0.250 W | **41 %** |

So **2 × 100 Ω 1206 in parallel (C17901)** meets AW-4 at ±1 % with the short
at 41 % of rating, one part type, two placements, and D-V2-4 (51 Ω) is not
needed. If the op-amp limits below 64 mA, the figures scale with I² *(check
against the AWG op-amp's datasheet short-circuit current)*.

## 4. Capacitors (MLCC)

88 Basic MLCCs, all read on both part pages. The full list is in the CSV;
the ranges asked for:

**C0G, 1 pF to 10 nF.** All ±5 %, 50 V. Nothing Basic below 10 pF and no
C0G at 1 nF; 2.2 nF exists only in 0805.

| value | 0402 | 0603 | 0805 |
|---|---|---|---|
| 10 pF | C32949 | C1634 | |
| 12 pF | C1547 | C38523 | |
| 15 pF | C1548 | C1644 | |
| 18 pF | C1549 | C1647 | |
| 20 pF | C1554 | C1648 | C1798 |
| 22 pF | C1555 | C1653 | C1804 |
| 30 pF | | C1658 | |
| 33 pF | C1562 | C1663 | |
| 47 pF | C1567 | C1671 | C14857 |
| 100 pF | C1546 | C14858 | C1790 |
| 330 pF | | C1664 | |
| 2.2 nF | | | C28260 |

Below 10 pF a value is made in series (10 s 10 = 5 pF, 10 s 12, 10 s 15 ...),
as version 1 already did for C2.

**X7R / X5R, 10 nF to 22 µF** (X7R below 1 nF also exists: 150 pF, 220 pF,
470 pF, 1 nF, 2.2 to 8.2 nF; see the CSV). Tolerance ±10 % unless stated.

| value | 0402 | 0603 | 0805 | 1206 |
|---|---|---|---|---|
| 10 nF X7R | C15195 50 V | C57112 50 V | C1710 50 V | C1846 50 V |
| 22 nF X7R | C1532 50 V | C21122 50 V | C1729 50 V | |
| 33 nF X7R | | C21117 50 V | C1739 50 V | |
| 47 nF X7R | | C1622 50 V | C53134 50 V | |
| 100 nF X7R | C1525 16 V, C307331 50 V | C14663 50 V | C49678 50 V, C28233 100 V | C24497 50 V |
| 220 nF X7R | C16772 16 V | C21120 25 V | C5378 50 V | |
| 470 nF X7R | | C1623 25 V | C13967 50 V | |
| 1 µF | X5R C52923 25 V | X5R C15849 50 V | X7R C28323 50 V | X7R C1848 50 V |
| 2.2 µF | X5R C12530 6.3 V ±20 % | X5R C23630 16 V | X5R C377773 50 V | X7R C50254 50 V |
| 4.7 µF | X5R C23733 10 V ±20 % | X5R C19666 16 V | X5R C1779 25 V | X7R C29823 50 V |
| 10 µF X5R | C15525 6.3 V ±20 % | C19702 10 V; C96446 25 V ±20 % | C15850 25 V; C440198 50 V | C13585 50 V |
| 22 µF X5R | | C59461 6.3 V ±20 % | C45783 25 V ±20 % | C12891 25 V |

Larger: 47 µF X5R (C16780 0805 6.3 V, C96123 1206 10 V) and 100 µF X5R
(C15008 1206 6.3 V), both ±20 %. Two tantalums are Basic (C7171 10 µF 16 V
case A, C16133 100 µF 6.3 V case B). DC-bias derating of the X5R parts is
not on the page and is the datasheet's *(check per part where it matters)*.

Version 1's Basic capacitors (12 pF C38523, 20 pF C1648, 100 nF C14663,
1 µF C15849, 10 µF C15850) are all still Basic on both pages.

## 5. Diodes and version 1's other parts (MC-12)

Not passives under V2-3, read for MC-12's "few in type". Library from the
domestic page unless stated, 2026-11-12.

| v1 part | LCSC | library | Basic alternative |
|---|---|---|---|
| BAT54S (ADC clamps, ratio-switch clamps) | C7420333 | **Extended** domestically (international: Extended, Preferred) | **No BAT54-family part of any maker is Basic** (a Basic-filtered search for "BAT54" returns 0 of 995 listings). The only Basic Schottkys are power parts: 1N5819WS C191023 (SOD-323), B5819W C8598 (SOD-123), SS14/SS34/SS54/SS210 (SMA), all 1 A or more and far more capacitance than a BAT54 *(check C and leakage before considering)*. The Basic small-signal pairs are silicon: **BAV99 C2500** (Nexperia, series pair, SOT-23) and **BAV70 C68978** (common cathode) |
| BAV99 (AWG clamp, unfitted) | C2500 Nexperia BAV99,215 | **Basic** | - |
| OPA354 | C36384 | Extended | |
| OPA365 | C96626 | Extended | |
| TLV9062 | C398355 | Extended (read today; was *(check)* in v1) | |
| LM27762 | C473398 | Extended | |
| REF3030E | C54120492 | Extended | |
| ADS124S08 | C2870171 | Extended | |
| TMUX1119 | C2673327 | Extended | |
| (1.5 nF, removed) | C1595 | Extended domestically | |

Other Basic diodes: 1N4148WS C2128 (SOD-323), 1N4148W C81598 (SOD-123),
SM4007PL C64898, M7 C95872, US1M C412437, MB10S bridge C2488. Basic
op-amps exist (TL072, NE5532, LM358, LM324, OP07) but none is a rail-to-rail
3.3 V/5 V part; none was assessed here.

## 6. Left to check

- Domestic Basic parts not in the international Basic list: none can be
  enumerated with the method above *(check, by part number, any value that
  is missing here)*.
- Tempco of 1 to 10 Ω 0603 and 33 Ω 0805: page and datasheet disagree; the
  worse figure is used *(check)*.
- Stock of every chosen part *(check before ordering)*.
- The AWG termination's short-circuit current, 64 mA, is the spec's derived
  figure *(check against the op-amp chosen)*.
- X5R/X7R DC-bias derating *(check per part)*.
