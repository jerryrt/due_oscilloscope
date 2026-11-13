# JLCPCB fabrication and assembly: what the AFE shield can rely on

Notes for the AFE shield (2-layer, one side populated, 0603 and larger,
no BGA, first order <= 20 boards). Every figure carries the page it came
from. Pages were read through a summarising fetch on 2026-11-10, not
opened in a browser, so a figure marked *(check)* was not confirmed on a
JLCPCB page and a figure without the mark should still be re-read in the
live quote tool before an order. Stock and price move daily; none of the
stock figures below is a commitment.

## 1. Fabrication, 2-layer

Source: <https://jlcpcb.com/capabilities/pcb-capabilities>

| item | value |
|---|---|
| Thickness options | 0.4 to 4.5 mm; standard 0.4/0.6/0.8/1.0/1.2/1.6/2.0 mm |
| Thickness tolerance | +/-10% at >= 1.0 mm, +/-0.1 mm below |
| Outer copper | 1, 2, 2.5, 3.5, 4.5 oz |
| Min track/space, 1 oz | 0.10 / 0.10 mm; 2 oz 0.16 / 0.16 mm |
| Track width tolerance | +/-20% |
| Min via hole / diameter | 0.15 / 0.25 mm; 0.20 mm hole preferred |
| 0.1 mm drill | boards <= 1 mm with ENIG/OSP only, extra cost |
| Via hole-to-track / PTH-to-track | 0.2 mm / 0.28 mm (0.35 recommended) |
| Annular ring, PTH | 0.25 mm recommended, 0.18 mm absolute |
| Min NPTH / recommended PTH | 0.50 mm / >= 0.5 mm |
| Min plated / non-plated slot | 0.5 mm / 1.0 mm wide |
| Min SMD pad, pad-to-pad | 0.25 x 0.25 mm; 0.15 mm between nets |
| Surface finish | HASL (leaded or lead-free), ENIG, OSP |
| Mask colours | green, purple, red, yellow, blue, white, black |
| Mask bridge | 0.10 mm (colours) / 0.13 mm (black, white) |
| Silk | line >= 0.15 mm, text height >= 1.0 mm, pad clearance 0.15 mm |
| Copper to routed edge | >= 0.2 mm |
| Outline tolerance | +/-0.2 mm regular, +/-0.1 mm precision (>= 50 x 50 mm) |
| Min / max board | 3 x 3 mm; 670 x 600 mm for 2-layer |
| V-cut | copper >= 0.4 mm from edge, panel 70 x 70 to 475 x 475 mm |
| Mouse bites | tab >= 4 mm (5 mm with bites), board spacing >= 2 mm |

Files for KiCad, source
<https://jlcpcb.com/help/article/how-to-generate-gerber-and-drill-files-in-kicad-9>
(a KiCad 9 article; no KiCad 10 article was found *(check)*):

- Gerber with Protel extensions, 4.6 mm, F/B.Cu, F/B.Mask, F/B.Silkscreen,
  Edge.Cuts, plus F.Paste for assembly; drill marks None, scale 1:1,
  extended X2 and netlist attributes on, zones filled before plot.
- Excellon drill, mm, absolute origin, decimal zeros, PTH and NPTH in
  separate files, alternate drill mode for ovals. One .zip, English names.

BOM and CPL, source
<https://jlcpcb.com/help/article/how-to-generate-the-bom-and-centroid-file-from-kicad>:

- BOM (.csv/.xls/.xlsx) required columns: Comment, Designator, Footprint,
  JLCPCB/LCSC Part #. KiCad's own export needs its headers renamed
  (Reference to Designator, Value to Comment).
- CPL required columns: Designator, Mid X, Mid Y, Rotation, Layer, in mm.
  KiCad's .pos writes Ref, PosX, PosY, Rot, Side, to be renamed.
- The page recommends the Fabrication Toolkit plugin with "Apply
  automatic component translations" ticked, which corrects rotation and
  offset per footprint. The page says nothing further on rotation. Treat
  the CPL as unverified until the quote tool's placement preview has been
  checked against every polarised part (diodes, SOT-23, ICs).

## 2. Assembly (PCBA)

Sources: <https://jlcpcb.com/capabilities/pcb-assembly-capabilities>,
<https://jlcpcb.com/help/article/pcb-assembly-price>

| | Economic | Standard |
|---|---|---|
| Sides assembled | one | one or two |
| Layers / thickness | 2, 4, 6 / 0.8 to 1.6 mm | 1 to 32 / any |
| Single board size | 10 x 10 to 470 x 500 mm | 70 x 70 to 460 x 500 mm |
| Order volume | 2 to 50 | 2 to 80,000 |
| Fiducials, edge rails | not necessary | necessary |
| Smallest package, IC pitch | 0402, 0.4 mm | 01005, 0.35 mm |
| Gold fingers, castellated, edge plating | not supported | supported |
| Build time | 1 to 3 days | 4 or more days |
| Setup fee | $8.18 | $25.56 one side |
| Stencil | $1.53 | $8.21 one side |
| Part loading | $3.07 per extended part type | $1.53 per part type, basic or extended |
| SMT placement | $0.0016 / joint | $0.0016 / joint |
| Hand soldering labour | $3.58 per order | $3.58 per order |

Other items from the price page: a handling charge applies when the
choice of options differs by less than $14.93; $0.45 "confirm parts
placement" fee; Standard has a $0.48 per-board minimum SMT charge. Basic
parts carry no loading fee under Economic (the page implies it; the
extended fee is the only one stated) *(check)*.

- ENIG surcharge: not on the price page *(check)*; the quote tool shows
  it. Economic limits finish and colour to "listed options" and says some
  colours restrict quantity to 5 to 30 *(check which)*.
- Lead time: only the 1 to 3 / 4+ day build time above; shipping and
  fabrication time not found *(check)*.
- Through-hole: the capabilities page says THT is supported in both tiers,
  by wave soldering, with a manual-assembly charge of $0.0164/joint. The
  owner solders the BNCs and headers anyway, so leave them out of BOM and
  CPL *(whether Economic really accepts THT is ambiguous on the page)*.
- Panels: the page recommends at most 250 x 250 mm, and Economic accepts a
  single board or a mouse-bite panel. Our 101.6 x 53.3 mm board fits both
  tiers' size limits.
- Parts: Basic and Extended library; global sourcing and consigned parts
  are a separate service whose terms were not read *(check)*,
  <https://jlcpcb.com/parts>.

## 3. Basic-library parts

A live Basic listing (<https://jlcpcb.com/parts/basic_parts>, 1,586 items,
paginated) was only readable for page 1, which showed:

| part | LCSC # | class | stock seen |
|---|---|---|---|
| GZ1608D601TF 0603 ferrite bead | C1002 | Basic | 430,275 |
| SDFL1608S100KTF 0603 inductor | C1035 | Basic | 398,851 |
| CC0603KRX7R9BB104 100 nF 50 V X7R 0603 | C14663 | Basic | not read |

Source for C14663: <https://jlcpcb.com/partdetail/CC0603KRX7R9BB104/C14663>.
Only third-party lists name C25804 (10k) and C21190 (1k) as 0603 Basic
resistors, so they are *(check)*. 0 ohm 0603, the LED, 0603 C0G capacitors
and 0.1% E96 0603 resistors: not found. BAV99 and BAT54S: every listing seen
is Extended (BAV99 e.g. C408392, C916421, C68983; BAT54S e.g. C2688221,
C171786); I saw no Basic one, e.g.
<https://jlcpcb.com/partdetail/BAV99/C408392>.

## 4. Candidate ICs

Prices at qty 20 were not obtained for any part: *(check)* throughout.
Stock figures differ between snapshots and are an indication only.

| part | LCSC # | package | class | stock / price seen | source |
|---|---|---|---|---|---|
| OPA2354AIDGKR | C95502 | VSSOP-8 | Extended | JLC page 2, LCSC 380 (conflict); from $1.9126 | <https://jlcpcb.com/partdetail/TexasInstruments-OPA2354AIDGKR/C95502> |
| OPA2354AIDGKT | C2861763 | VSSOP-8 | *(check)* | 49 | <https://www.lcsc.com/product-detail/C2861763.html> |
| OPA356AIDBVR | C183100 | SOT-23-5 | *(check)* | 2,010 | <https://www.lcsc.com/product-detail/C183100.html> |
| OPA356AID | C1347088 | SOIC-8 | *(check)* | 0 on JLC | <https://jlcpcb.com/partdetail/TexasInstruments-OPA356AID/C1347088> |
| OPA2356AIDR | C2867057 | SOIC-8 | Extended | 0 (Mar 2026 snapshot) | <https://www.flux.ai/lcsc/opa2356aidr~h52c.md> |
| LM27762DSSR | C473398 | WSON-12 | Extended | LCSC 2,845 to 8,585 across snapshots | <https://jlcpcb.com/partdetail/TexasInstruments-LM27762DSSR/C473398> |
| REF3030AIDBZR | C38423 | SOT-23 | *(check)* | not read | <https://www.lcsc.com/product-detail/C38423.html> |
| ADR4530BRZ | C208042 | SOIC-8 | *(check)* | not read | <https://jlcpcb.com/partdetail/AnalogDevices-ADR4530BRZ/C208042> |
| ADR4530ARZ-R7 | C404001 | SOIC-8 | *(check)* | not read | <https://www.lcsc.com/product-detail/C404001.html> |
| LM4040CEM3-3.0 | C3680390 | SOT-23-3 | *(check)* | not read | <https://api.jlcpcb.com/partdetail/4248193-LM4040CEM3_3_0T/C3680390> |
| ADS1115IDGSR | C37593 | VSSOP-10 | *(check)* | 0 to 26,826 (conflict) | <https://www.lcsc.com/product-detail/C37593.html> |
| ADS1256IDBR | C28186 | SSOP-28 | *(check)* | 3,312 to 7,288; flagged NRND on one snapshot | <https://www.lcsc.com/product-image/C28186.html?whichImg=0> |
| MCP3564-E/ST | C1012816 | TSSOP-20 | *(check)* | not read | <https://www.lcsc.com/product-detail/C1012816.html> |

Not found, or not searched, so no claim: OPA354, OPA355, OPA350 family,
THS4031 or other >= 100 MHz rail-to-rail parts, TLV7xx and TPS7A LDOs,
AD5693/AD5686/DAC8571/MCP4725, ADS1118/ADS1219/ADS8688/AD7124,
TS5A3159/TMUX1119 and ADG switches. Search engines returned nothing for
TS5A3159, TMUX1119 and THS4031; that is not proof they are unstocked.

## Constraints this puts on the design

1. Choose Economic if one-sided placement holds: no fiducials or rails
   are then required, but add three fiducials anyway if a later Standard
   order is plausible *(check whether they would be wanted)*.
2. Keep the board 0.8 to 1.6 mm thick (Economic limit); 1.6 mm is the
   default, and impedance work is not offered by these pages.
3. Design to 0.15 mm trace/space and 0.3 mm via hole minimum so no extra
   cost option is touched; keep copper 0.2 mm from the outline.
4. Every extended part type costs $3.07 (Economic). Count distinct
   extended types, and prefer Basic 0603 values and the Basic ferrite
   bead C1002 where the circuit allows. BAV99/BAT54S, the precision ICs
   and any 0.1% or C0G parts will all be Extended.
5. Stock of the ICs listed is thin and inconsistent between pages
   (OPA2354 low, OPA2356 zero, ADS1115 conflicting). Check live stock on
   the chosen C-number before freezing the BOM, and record it.
6. BNCs and stacking headers stay out of the BOM and CPL; leave their
   pads unmasked-for-paste (no F.Paste aperture) and keep soldering
   clearance for hand work.
7. Use the Fabrication Toolkit output and check every polarised part's
   rotation in the quote preview; do not trust raw KiCad .pos rotations.
8. Mask bridge of 0.10 mm and min silk text 1.0 mm govern fine-pitch
   footprints (VSSOP, WSON); use footprints with mask dams or accept web
   removal.
