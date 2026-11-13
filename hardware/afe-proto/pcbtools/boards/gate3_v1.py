"""Gate-3 table of the v1 layout of record: every source and every board-specific sentence the generic engine (pcbtools/gate3) needs, as named
fields and no logic (`pcbtools/gate3/README.md` describes each; `gate3_v2.py` is the v2 table this one follows in wording and shape).

    docker/pcb/run.sh -m 3G -t 900 -c 2 env PYTHONPATH=hardware/afe-proto python3 -B -m pcbtools.gate3 \
        --config v1 --table gate3_v1 --out hardware/afe-proto/kicad/gate3

Facts this table rests on, all from the repo: the running record of the deviations and rulings is `kicad/gate3/notes.md` (items 1-17, in kvm_01's
tree); the board is `kicad/afe-proto.kicad_pcb` with its project file; v1's 0603 0R bridge part is C21189 (type 0Rb in `kicad/design.py`); the study
results are `v1/results/`; v1's BOM is priced by the same engine as v2's, `v2/bom/bom.py`, over `bom/v1/data/` (parts streams generated from `kicad/design.py` by `bom/v1/make_parts.py`,
`catalog.csv`, `intl.csv`, `blocks.csv`, `extra.csv`); `bom/v1/bom.md` is that engine's output and `bom/v1/bom.txt` the designator list.
"""
from pcbtools.boards import v1 as _cfg

AFE = 'hardware/afe-proto/'

# ---------------------------------------------------------------------------------------------------- identity and files
TITLE = f'{_cfg.NAME} {_cfg.MODEL} REV {_cfg.REV} integrated layout ({_cfg.FILE_STEM})'
GENERATED_BY = '`pcbtools/gate3` (`python3 -B -m pcbtools.gate3 --config v1 --table gate3_v1`)'
BOARD = AFE + 'kicad/afe-proto.kicad_pcb'
PROJECT = AFE + 'kicad/afe-proto.kicad_pro'
RENDER_DIR = AFE + 'kicad/render/'
RENDERS = (('Top', 'v1-top.png'), ('Bottom', 'v1-bottom.png'), ('3D', 'v1-3d.png'))
RENDER_LINK_PREFIX = '../render/'                          # the renders as the document links them, relative to kicad/gate3/GATE3.md
RENDER_HINT = ('(in the PCB image: `kicad-cli pcb render --side top|bottom --quality basic --width 2400 --height 1400 -o v1-top.png|v1-bottom.png BOARD`, and '
               '`--side top --rotate "-45,0,45" --perspective` for `v1-3d.png`, with `KICAD10_3DMODEL_DIR=/usr/share/kicad/3dmodels`; the image has no `magick` or SVG '
               'rasteriser, so there is no copper-only view).')
DUE_ORIGIN = (50.0, 150.0)                                 # KiCad x = 50 + x, KiCad y = 150 - y: the Due-mm frame the document quotes
RULE_DOC = 'docs/afe.md'

SECTION_SOURCES = (
    ('1 Renders', 'PNGs in `kicad/render` (`v1-top.png`, `v1-bottom.png`, `v1-3d.png`; not regenerated here; checked for existence and age against the board)'),
    ('2 LR table', '`pcbtools.rules.ROWS` on the board with `boards/v1.py`; LR-10 from kicad-cli; rule text from `docs/afe.md`'),
    ('3 DRC', 'kicad-cli `pcb drc --severity-all` on a work copy of the board and its project file'),
    ('4 Bridges and hops', 'board arrays (pads, tracks, vias) via `gate3.bridge_table` / `hop_table`; the 16 bridges and their justifications from `kicad/design.py` (the `two(...)` notes) through `BRIDGE_TABLE` in `boards/gate3_v1.py`, '
                           'with the standing rules (a) and (b) of `kicad/gate3/notes.md`'),
    ('5 Deviations', 'rule figures, board (power caps, outline), project file rules; the recorded rulings are `kicad/gate3/notes.md` items 1-17 (read, not regenerated); cited spec text is quoted from the named file'),
    ('6 Cap and ripple rows', '`v1/results/scope_baseline.json`, `scope_A.json`, `scope_B.json`, `awg.json` (read, not recomputed), the extraction logs `v1/results/cap_converge.txt` and `cap_in_nets.txt`, '
                              '`v1/results/spicecmp.txt`; study definition `v1/sim/README.md`; no ripple study exists for v1'),
    ('7 BOM and cost', 'LCSC/value/footprint from the board; prices and the cost model from `bom/v1/data/*.csv` through `v2/bom/bom.py`, the engine that also writes `bom/v1/bom.md` (the same one as version 2)'),
)

# ---------------------------------------------------------------------------------------------------- section 2: the LR table
LR_HEADING = '## 2. LR table (rules LR-1 to LR-11 on the integrated board)'
LR_INTRO = ('Verdicts are the checker\'s own (`python3 -B -m pcbtools.check BOARD --config {config} --drc`, called through the library so the figures are kept). '
            'The rule text is `docs/afe.md`\'s, shortened to its first sentence; the full text is there. '
            'The supply-pin decoupling distance is a sub-check of **LR-4** ("each supply pin has its 100 nF within a few millimetres", `docs/afe.md`), printed here as '
            '"LR-4 decoupling" with the config\'s limit; the checker\'s own name for that row is `LR-12 DECOUP_MAX` (`pcbtools/rules.py`; tests and goldens key on it), '
            'and `docs/afe.md` has no LR-12 row. The rule numbers in this table are `docs/afe.md`\'s. '
            '**Two recorded LR-2 deviations are not rows of this table**, because the checker has no figure for them; they are in section 6 with their conditions '
            '(the 10.22 mm IN-pad to N-bus distance, and the CH2 output-run ruling that became moot).\n')
LR_DOC_ROWS = ('LR-1', 'LR-2', 'LR-3', 'LR-4', 'LR-5', 'LR-6', 'LR-7', 'LR-8', 'LR-9', 'LR-10', 'LR-11')      # rows whose text is in RULE_DOC
LR_RENAMES = (('LR-12 DECOUP_MAX', 'LR-4 decoupling (DECOUP_MAX {:.1f} mm)', 'DECOUP_MAX'),)             # (checker row, label shown, config field filling {})
LR_SUBCHECKS = (('INV_MAX', '(LR-4 sub-check) the inverting-node trace is the shortest of the stage'),
                ('LR-4 decoupling', '(LR-4 sub-check) each supply pin has its 100 nF within a few millimetres'))
DRC_ROW = 'LR-10'                                          # the row the engine adds from kicad-cli DRC

# ---------------------------------------------------------------------------------------------------- section 3: DRC
# (violation type, a reference it names): documented, not counted as "other". The five silk_overlap items are the waived ones recorded below.
DRC_DOCUMENTED = (('courtyards_overlap', 'MH602'), ('silk_overlap', 'Reference field of J501'), ('silk_overlap', 'Reference field of R514'),
                  ('silk_overlap', 'Reference field of R520'))        # the engine matches the item description after 'Footprint ' is stripped
DRC_DOCUMENTED_LABEL = 'MH602 courtyards and the waived silk overlaps'
DRC_DOCUMENTED_NOTE = (
    '**The MH602 courtyard overlaps** (MH602 with the sockets J607 and J605) are the Due\'s own geometry: MH602 is the optional M2.5 standoff position beside the socket '
    'rows. **The owner\'s caliper check of the socket clearance is pending**, and the screw is optional, so the overlap costs nothing if the screw is left out. '
    '(The caliper status is the gate brief\'s statement, not a repo file *(check)*.)\n\n'
    '**Silk waivers, granted by the spec team** (recorded for this gate; the waiver text is the brief\'s, not a repo file *(check)*). '
    '(1) **5 DRC `silk_overlap` items**: J501\'s reference against U502\'s polygon, J501\'s reference against its own silk, R514\'s reference against U502\'s silk, and R520\'s reference against '
    'J501\'s box (twice). Each is a label touching a part outline and each label stays legible: waived. '
    '(2) **47 label pairs 0.6-1.0 mm apart**, clearly separate, listed on the `WAIVE` line of `whatif/blocks/gate3/silk3/check_final.txt` in kvm_01\'s tree '
    '*(check: the copy of that file read for this table lists 49 pairs on its `WAIVE` line and 3 under 0.6 mm, against the 47 of the brief; the count is the brief\'s)*. '
    '(3) **Two labels far from their parts**: R207 3.44 mm and R403 3.89 mm. (4) **MH602\'s label lies inside the SCOPE fence** (the mounting hole is the Due\'s own position at the edge of the fence; '
    'the label is not a part). (5) **D501\'s two decorative silk lines were deleted** (they were the cause of a `lib_footprint_mismatch` warning as recorded in the brief); the one `lib_footprint_mismatch` warning still reported below is on D501 itself *(check: whether it is the deleted lines that make the footprint differ from its library copy now, or the warning that was meant to go)*; it is a warning, counted as a library-copy warning, and the project file sets mismatch to ignore. '
    '(6) **"ON"** stands under the J501 pin 1-2 gap with an L-shaped line to the pin 2-3 box (the pocket beside the pins is full of copper; the label is as close as the copper lets it be). '
    '(7) **C301 and C304 labels are ambiguous at 0.33 mm. Both are 10 pF C0G 0603 capacitors (C301 across Rf, C304 across Rbin) stacked in the AWG block. Board-house assembly places from the CPL, not the silk, so only a hand rework could misread them; check the value before replacing either; F.Fab arrows run from each label to its part.** '
    '(8) **R505, R506 and R508 designators stand over J602\'s socket row** (horizontal, 0.6-1.6 mm over its holes, nearest their own parts; no silk-only position exists, and the REFCAL ladder is not moved for a silk gain). '
    'Waived by the spec team: every Due pin name is printed vertically in the bands and these three designators are horizontal, so orientation tells them apart.\n')
RULE_DIFF_TEXT = ("**The project file next to the board does not carry the design's rules.** `{n}` rule value(s) in `afe-proto.kicad_pro` differ from `BOARD_SETUP` in `pcbtools/boards/v1.py`. "
                  "**Restore the file's rules before the gate.** LR-10 in section 2 is the checker's, at the file as it stands (run A). "
                  "Run B repeats DRC with the design's rules applied to a scratch copy of the project file.\n")

# ---------------------------------------------------------------------------------------------------- section 4: bridges and hops
BRIDGE_REF_PATTERN = r'R(110|111|112|113|309|310|410|411|412|413|515|516|517|518|519|520)'      # the 16 type-0Rb parts of design.py

# justification per bridge: (block, text), from the `two(...)` notes of kicad/design.py and the standing rules of gate3-notes.md:
#   (a) a 0603 0R bridge of the existing type (0Rb, C21189) may be added inside a block when the crossed net is not an ADC line, a divider node or a VREF branch;
#   (b) an LR-2 or LR-5 deviation of an already recorded kind is allowed, with its measured figure.
# The nets of each bridge are read from design.py's own PARTS, so a net here cannot differ from the design's.
_WHY = {
    'R110': ('SCOPE', 'wall bridge over the A1 column: the scope\'s +3V3A branch (from R413) to the dual V+ and the clamps; LR-1 method over an ADC line, one of the original six wall bridges (D24 count review)'),
    'R111': ('SCOPE', 'VREF_P to the CH1 R3 leg over the A0 horizontal, part 1 of 3 (A0, the supply belt and A1 close the north half of the fence); LR-1 method over ADC and VREF lines (D24 count review)'),
    'R113': ('SCOPE', 'over the supply belt (R110.2, R108, U101.8, U101, R107) inside fence 1, part 2 of 3; LR-1 method (D24 count review)'),
    'R112': ('SCOPE', 'over the A1 horizontal, part 3 of 3: CH1 R3 (R104) hangs on VREF_R; LR-1 method over an ADC line (D24 count review)'),
    'R309': ('AWG', 'wall bridge over A1: the AWG_BNC sense tap, west-bound, part 1 of 2; LR-1 method over an ADC line (original six wall bridges, D24 count review)'),
    'R310': ('AWG', 'wall bridge over A0: the AWG_BNC sense tap, west-bound, part 2 of 2; LR-1 method over an ADC line (original six wall bridges, D24 count review)'),
    'R515': ('REFCAL', 'wall bridge over A1 (the CH2 leg of VREF), part 1 of 2; LR-1 method over an ADC line (original six wall bridges, D24 count review)'),
    'R516': ('REFCAL', 'wall bridge over A0 (the CH2 leg of VREF), part 2 of 2; LR-1 method over an ADC line (original six wall bridges, D24 count review)'),
    'R517': ('REFCAL', 'over a VREF leg: the ADS side of +3V3A beyond it (VDD, its 100 nF, the pull-ups, the clamps). Accepted by the spec team (2026-11-13) under the same ruling as v2\'s BR506-BR508 (D24 of `docs/afe.md`, as updated on main): '
                       'a top-side 0603 bridge is LR-1\'s prescribed method for crossing a VREF or ADC line, and none of R517-R519 crosses a divider node; standing rule (a) only said when to ask'),
    'R518': ('REFCAL', 'over a VREF leg: SDA to the ADS; accepted with R517 (D24)'),
    'R519': ('REFCAL', 'over a VREF leg: SCL to the ADS; accepted with R517 (D24)'),
    'R520': ('REFCAL', 'splits the sense bottom node B into SNS_B / SNS_B_N so the Rd tie (R512) reaches VREF branch D without a crossing; it crosses a VREF leg (not a TAP line, as design.py\'s note now says) '
                       'and carries only the ADS input current. Owner team\'s ruling (option a), mirrors v2 BR508 (gate3-notes item 3); the later standing rule (a) is wider but excludes VREF branches, so the ruling is the authority'),
    'R410': ('POWER', 'a 0 ohm link that carries VNEG over the +5V_F column (VNEG | VNEG_O, one net each side so the board connects it through the part): the generator\'s two rails cannot both leave the pockets '
                      'the +5V_F tree encloses on one layer (LR-1: no hop). Crossed net is +5V_F: standing rule (a) (gate3-notes item 4: no new part type, the other bridges\' pattern)'),
    'R411': ('POWER', 'corridor bridge over the VNEG strip lane: +3V3A from the generator to the AWG branch (the lane order is the reverse of the generator\'s outputs, so R411 is topological); standing rule (a) (item 7)'),
    'R412': ('POWER', 'corridor bridge over AREF: the +3V3A trunk to the ADS side of REFCAL (R517); AREF stays top-continuous; standing rule (a) and the spec team\'s corridor rule (item 7)'),
    'R413': ('POWER', 'corridor bridge over AREF: the scope\'s own +3V3A branch from the star, straight to R110; AREF stays top-continuous; standing rule (a) (item 7). '
                      'R109, the earlier second part of this branch, was REMOVED (item 17: it crossed nothing on the final board)'),
}
BRIDGE_TABLE = [(p['ref'], p['pins']['1'], p['pins']['2'], _WHY[p['ref']][0], _WHY[p['ref']][1])
                for p in _cfg._design.PARTS if p['ref'] in _WHY]
BRIDGES_SOURCE = ('pcbtools.boards.gate3_v1', 'BRIDGE_TABLE')                 # (module, attribute path): (ref, net a, net b, block, justification) tuples
NET_CLASS_FIELDS = dict(adc=('CHANNELS.out_nets', 'ADC_NETS'), divider=('HIZ', 'DIVIDER_GROUPS'), vref_prefix='VREF_NET', other=('XSENS', 'HIZ'))
D24_ROW_PATTERN = r'\| D24 \|[^\n]*'
D24_QUOTE_PATTERN = r'The "1 to 3" first estimated was wrong[^|]*?which is where the count is reviewed'
D24_FOUND = ('`docs/afe.md` (row D24) says, quoted from the file: "{quote}". The sentence arrived on main with commit 446bb68, which the document does not name; '
             'it is cited here as the file\'s text. ')
D24_MISSING = ('The spec lead\'s message records that D24 was updated on main in commit 446bb68: the "1 to 3 in all" was an estimate, and the count is now reviewed in this table. '
               '(`docs/afe.md` in this tree does not carry that wording, so it is cited as quoted from the spec lead\'s message, not as a repo file.) *(check)* ')
BRIDGE_ACCEPT = (' **All {nb} bridges are accepted, including the {nover} over ADC or VREF lines** ({over}). Version 1 carries 16 bridges of the one type 0Rb (C21189); '
                 '**R109 was REMOVED** (spec team\'s ruling, 2026-11-13: it crossed nothing on the final board, no other-net copper within 0.8 mm, and the quiet VREF trunk it bridged no longer exists; '
                 'R413 feeds the scope branch P33_S directly, one part fewer), so the older counts of 13 and 17 do not apply. The bridges fall in three groups. '
                 '**(1) The wall bridges and the SCOPE and REFCAL bridges over ADC and VREF lines** (R110-R113, R309, R310, R515, R516, R517-R519): LR-1 prescribes exactly this method '
                 '(a top-layer 0603 0 ohm bridge over the ADC trace, never a bottom hop under it), and the D24 count is reviewed in this table. '
                 '**(2) The corridor bridges R410-R413**, added under standing rule (a) (a 0603 0R of the existing type inside a block when the crossed net is not an ADC line, a divider node or a VREF branch): '
                 'R410 over the +5V_F column, R411 over the VNEG strip lane, R412 and R413 over AREF (AREF stays top-continuous). Their crossed nets are in the last columns of the table. '
                 '**(3) R520**, the sense bottom node split, under the owner team\'s earlier ruling (option a, mirrors v2 BR508). '
                 'Standing rule (b) (an LR-2 or LR-5 deviation of a recorded kind is allowed with its measured figure) is applied in section 5, not here. '
                 '{parts}; {div}. The last column says which bridges sit over a net of those classes. '
                 '**Hops:** the integrated board has four 1.8 mm bottom hops (two vias each) of +3V3A under SCL and SDA, outside the analog fences, at x 40.0 and 42.0 (gate3-notes item 7, '
                 'the spec team\'s corridor rule: a supply hop of 3 mm or less under SCL/SDA); the hop table below is the board\'s own count.\n')

# ---------------------------------------------------------------------------------------------------- section 5: deviations
POWER_CAPS = dict(ic='U401', caps=('C401', 'C402', 'C403', 'C404', 'C405', 'C406', 'C407', 'C408', 'C409', 'C410'), far_mm=5.0)
POWER_CAPS_CAPTION = '**LM27762 capacitor distances on this board** (nearest U401 pad on the same net; the farther pin for the flying capacitor C402):'
CFG_QUOTED = ('HOP_MAX', 'HOP_MAX_VIAS')                         # config fields quoted; boards/v1.py has no designator waiver tables, so those rows are off (None below)
CFG_FOREIGN_WAIVED = 'DESIGNATOR_FOREIGN_WAIVED'
CFG_GAP_WAIVED = 'DESIGNATOR_GAP_WAIVED'
CFG_GAP_MIN = 'DESIGNATOR_GAP_MIN'
CFG_GAP_ONE_LABEL = 'DESIGNATOR_GAP_ONE_LABEL'
# each deviation row is (rule / item, deviation text, status / authority text). The engine adds this row once per documented DRC item
# (the MH602 courtyards and the waived silk overlaps), so the text is generic and names the item.
DEV_COURT = ('DRC documented items', '{items}: documented DRC item', 'documented (section 3): MH602 courtyards (owner caliper check pending, screw optional); silk overlaps waived by the spec team')
DEV_POWER = ('LR-5 (generator caps at their pins)',
             'capacitors more than {far_mm:n3} mm from their {ic} pad: {far}; the nearer ones: {near} mm (all measured here, pad centre to pad centre; full list below)',
             'standing rule (b): an LR-5 deviation of a recorded kind is allowed with its measured figure, which is this row. Gate3-notes item 5 recorded only the output capacitors C407-C410 at 5.6-8.3 mm '
             'and left them "to be judged" (this board: 5.55-8.26 mm). The spec team\'s v2 standard is: the first capacitor of each rail within about 3.5 mm of its pin, the second at 5-6 mm; v1 meets it for the input (C403 2.8 mm) '
             'and the flying capacitor, and not for the charge-pump output (C405 10.4 mm, C406 12.5 mm), OUT- (C409 6.2 mm) or OUT+ (C407 5.6 mm). A POWER rework within the existing topology found no layout that reaches 3.5 mm on any of the three: '
             'the three +5V_F pins force the +5V_F copper into a ring round the closed side of U401, the one-layer VNEG hop through R410 puts the FBN resistors in the east strip, and what is left west of pins 5 and 6 is 4 mm wide, so a CP cap '
             'and a VNEG cap cannot both fit (a north-west variant reaches about 3.3 mm for C405 but leaves three GND vias within 3 mm of the IC\'s ground pads where LR-1 needs four); a rebuild that bulges the ring and re-seats R410, R408, the VNEG exit and the test points '
             'might, untested. **Evidence instead (`v1/results/pw2_ac_v1.json`, `v1/sim/pw2_ac_README.md`; v2\'s pw2_ac model with v1\'s distances), judged the way v2\'s row is: VIN in the PW-4 band (DC to 1 MHz) is 5.713 mV rms / 18.31 mV pk-pk at v1\'s distances against 5.710 / 18.26 at the standard\'s 3.5 and 5.5 mm (and 5.745 / 18.85 for ideal capacitors): '
             'equal within 0.3 %, so the distance deviation changes nothing a requirement bounds there (above 1 MHz v1 reads 2.04 mV rms in 1-10 MHz against 2.27 at the standard: nearer, since C403 and C404 sit at 2.8 and 5.1 mm); '
             'OUT+ 0.046 mV rms / 0.130 mV pk-pk and OUT- 0.015 / 0.043 in the same band (the standard: 0.046 / 0.131 and 0.015 / 0.044), pass with margin; '
             'CPOUT is an internal pump node with no requirement of its own: in DC-1 MHz it reads 6.25 mV rms against 6.30 at the standard, and only at 10-30 MHz does it show the distance (23.0 mV rms / 341 mV pk-pk against 10.9 / 162, the full-band 361 against 169, 2.1 times); '
             'its effect would show at OUT+ and OUT-, which pass. The model has no LDO supply rejection and uses v2\'s pump transient, so **VT-8 is the bench check of the charge-pump output and of OUT+/OUT-** '
             '*(check: v1\'s own rail loads and the 175k/100k feedback were not re-derived; the 100n sensitivity case uses guessed parasitics; the 10-30 MHz content is unvalidated)*. '
             'The record carries no ruling text on C401 (100n VIN, 7.9 mm) and C404 (5.1 mm): they are the second and third input capacitors *(check)*')
DEV_FOREIGN = None                                               # no designator waiver tables in boards/v1.py: no row (the silk waivers are in section 3)
DEV_FOREIGN_EMPTY = ''
DEV_GAP = None
DEV_OUTLINE = ('MC-1 board outline',
               'the board overhangs the Due by {overhang} mm on each long edge, the figure computed from the longest pin name at 1.0 mm text (`pcbtools.pinlabels.required_overhang`): {w:.2f} x {h:.2f} mm against the {max0} x {max1} mm bound; '
               'each band is a top-layer keep-out and the bottom ground plane fills it to 0.45 mm of the edge ({band}); the Due\'s pin names are printed in the bands, all vertical, 1.0 x 1.0 mm',
               None)                                       # the authority text is MC1_FOUND or MC1_MISSING
MC1_COMMIT = '9489582'
MC1_PATTERN = r'Amended by the owner, 2026-11-13[^|]*overhangs the Due by %g mm on each long edge' % _cfg.OVERHANG
MC1_FOUND = ('owner ruling 2026-11-13, in `docs/afe.md` row MC-1 ("Amended by the owner, 2026-11-13 ... the outline overhangs the Due by %g mm on each long edge", ' % _cfg.OVERHANG +
             'read from the file at run time; amendment commit 9489582, not named in the document)')
MC1_MISSING = ('owner ruling 2026-11-13, MC-1 amended on main (`9489582`, with the pin-name text size set in the later commits); `docs/afe.md` in this tree does not carry the %g mm wording *(check)*' % _cfg.OVERHANG)
DEV_EDGE = ('copper-to-edge', 'min_copper_edge_clearance {edge_rule} mm in the project file (config says {edge_cfg} mm); the three strip lanes (0.2 mm wide, 0.2 mm gap) at y 0.59, 0.99, 1.39 '
            '(the contract\'s 0.55, 0.95, 1.35 do not fit: three lanes and gaps need 1.00 mm, the space is 0.99 mm) leave exactly 0.2 mm to the J602 round pads',
            'spec team ruling 2026-11-13 (gate3-notes item 9): keep the 0.2 / 0.2 lanes at y 0.59 / 0.99 / 1.39 and set the copper-to-edge clearance to 0.45 mm. Arithmetic as ruled: the fabricator\'s minimum is 0.2 mm *(check)* '
            'and the outline tolerance is +-0.2 mm, so 0.45 mm leaves 0.25 mm worst case; 0.2 mm to the J602 pads meets the 0.2 mm clearance rule. '
            'The outline overhangs by the computed figure on each long edge (gate3-notes item 11 recorded the earlier 5 mm south overhang, superseded); 0.45 mm applies to every edge, the bottom plane included')
DEV_PROOF = ('+5V_F feed to the pump (information, not a deviation)', '+5V_F: {tracks} tracks, {length:.1f} mm, {vias} vias, {zones} zone fills, pads {pads}: {result}',
             'proven in 5.1 (copper graph, kicad-cli DRC with 0 unconnected, and broken-once arms); LR-6 does not look at +5V_F')
DEV_PROOF_JOINED = 'U401 pins 3, 8 and 12 are joined to R408 pin 2 by copper (one piece); no pour is involved'
DEV_PROOF_NOT = '**U401 pin 3, 8 or 12 is NOT joined to the source: see 5.1**'
MARGINS = (
    dict(rule='LR-5', what='sensitive copper to the generator (mm)', row='LR-5', key='min_distance_mm', limit='KEEPOUT', kind='min'),
    dict(rule='LR-1', what='longest bottom hop (mm)', row='LR-1', key='max_run_mm', limit='HOP_MAX', kind='max'),
    dict(rule='LR-1', what='vias on the longest hop', row='LR-1', key='max_run_vias', limit='HOP_MAX_VIAS', kind='max'),
    dict(rule='LR-4 INV_MAX', what='AWG_INV inverting node (mm)', row='LR-4 INV_MAX', key='AWG_INV', limit='INV_MAX', kind='max'),
    dict(rule='LR-4', what='AWG_INV node track length (mm; FB_MAX)', row='LR-4', key='fb_mm', limit='FB_MAX', kind='max'),
    dict(rule='LR-4 decoupling', each_of='LR-12 DECOUP_MAX', limit='DECOUP_MAX', kind='max'),
)

# ---------------------------------------------------------------------------------------------------- section 5.1: the connectivity proof
# The v2 table proves the filtered 5 V feed of the LM27762: which pins join which source pad by copper alone, with one-track cuts checked against DRC.
# v1's analogue: net /+5V_F, source pad R408.2 (the sense resistor, +5V_F side), the pump's three supply pins U401.3 (VIN), .8 (EN-), .12 (EN+),
# which must be tied on one layer; upstream is the +5V_DUE side of the sense resistor, R408.1 to J601.5 (the Due 5 V pin).
PROOF = dict(net='/+5V_F', source='R408.2', pins=('U401.3', 'U401.8', 'U401.12'), upstream=('/+5V_DUE', 'R408.1', 'J601.5'), on_net_head='on +5V_F',
             arms=(('stub at U401 pin 8', 'U401.8', 'first'), ('stub at U401 pin 12', 'U401.12', 'first'),
                   ('trunk, middle of the pin 3 run', 'U401.3', 'middle'), ('track, middle of the pin 12 run', 'U401.12', 'middle')))
PROOF_PATH_ORDER = ('U401.3', 'U401.8', 'U401.12')
PROOF_HEADING = '\n### 5.1 +5V_F: what joins U401 pins 3, 8 and 12 to the source ({status})\n'
PROOF_INTRO = ("`{net}` is the LM27762's filtered 5 V feed: R408 (1 ohm sense resistor, pin 1 on `/+5V_DUE`, pin 2 on `{net}`) feeds U401 pin 3 (VIN), pin 8 (EN-) and pin 12 (EN+) "
               "(`EN+ / EN- from VIN`, `kicad/design.py`), and C401, C403, C404 and the test point TP402 sit on it. The three supply pins of the pump must be tied together on one layer: "
               "the generator's two rails cannot both leave the pockets this net encloses, which is why R410 carries VNEG over it. The check below is `pcbtools/gate3/connectivity.py`: the copper graph of the net "
               "built from the board arrays (track capsules, via annuli, pad boxes, and the fills of any filled zone of that net), run on the board as it stands.\n")
PROOF_COPPER = ('**Every piece of copper on the net.** {tracks} tracks ({length:.1f} mm), {vias} vias, {npads} pads ({pads}), '
                '{arcs} arcs, **{zones_on_net} zone fills on the net**. The board has {nzones} zones:\n')
PROOF_RESULT = ('**Result.** The graph has {ncomp} connected piece(s) of `{net}` copper: {pieces}. With every zone fill left out the result is {same}. '
                'So U401 pin 3 {j_a} joined to the source {src} by copper alone, and so is pin 8 ({j_b}); pin 12 is in the same piece when the status above says PROVEN JOINED '
                '(the path tables below name each item the chain passes, including any via).\n')
PROOF_PATH_HEAD = ('**Path, {ref} pin {pin} to {src}** (coordinates are Due mm: KiCad x = 50 + x, KiCad y = 150 - y; '
                   'the link says how each item touches the one before it):\n')
PROOF_HISTORY = ''
PROOF_UPSTREAM = ('**Upstream of the sense resistor.** R408 pin 1 to J601 pin 5 (the Due 5 V pin) on `/+5V_DUE`: {n} items, {tracks} tracks, {vias} vias, '
                  '{fills} zone fills ({chain}).\n')
PROOF_UPSTREAM_NONE = '**Upstream of the sense resistor.** R408 pin 1 and J601 pin 5 on `/+5V_DUE` are **not** joined by copper in the graph.\n'
PROOF_DRC = ("**KiCad's own connectivity.** kicad-cli DRC (`--severity-all`, section 3) reports **{n} unconnected items** on the board, its nets assigned from the schematic: "
             "KiCad sees the net connected through the same tracks. The check is only worth that if it can fire, so one track is cut at a time in a scratch copy of the board file "
             "(the board is never touched), the graph predicts which pads lose the source, and DRC is run on the cut copy:\n")
PROOF_RULE = ('\n**Which rule sees this net.** LR-6 (the star rails) checks only `/+3V3A` and `/VNEG` (`STAR` and `GROUPS` in `pcbtools/boards/v1.py`); `/+5V_F` is in neither, and no LR row looks at its connectivity. '
              'The only check that sees it is LR-10 (kicad-cli DRC, unconnected items), which is what the figure above is, and this section\'s graph. '
              'LR-6 therefore says nothing about U401 pins 3, 8 and 12.\n')

# ---------------------------------------------------------------------------------------------------- section 6: evidence rows
EVIDENCE_HEADING = '## 6. Capacitance, LR-3 evidence and AN-1 / AW-3 rows'
R = AFE + 'v1/results/'
_SC = dict(f3='ac.f3dB_Hz', shelf='ac.shelf_pct', c1m='ac.zin.1000000.C_pF', r1k='ac.zin.1000.R_k', sc9='sc9_lsb_6Vpp.10MHz',
           pm21='pm.BEH21.pm_deg', pm60='pm.BEH60.pm_deg', pmv='pm.vendor.pm_deg', nn='N_N_fF_per_LSB_10MHz', pp='pad_pad_fF_per_LSB_10MHz',
           inin='IN_IN_fF_per_LSB_10MHz', cn='params.Cn_par_pF', cwire='params.Cwire_pF')
EVIDENCE_DATA = (
    dict(name='sb', json=R + 'scope_baseline.json', values=_SC),
    dict(name='sa', json=R + 'scope_A.json', values=_SC),
    dict(name='sB', json=R + 'scope_B.json', values=_SC),
    dict(name='aw', json=R + 'awg.json', write='aw3.json', values=dict(
        thr='aw3_threshold.threshold_pF', top='aw3_threshold.extracted_top_of_bar_pF', margin='aw3_threshold.margin_pF', limit='aw3_threshold.limit_MHz',
        tol='aw3_threshold.tolerance_pF', fA='aw3_threshold.at_extracted_top.A.f3dB_MHz', fB='aw3_threshold.at_extracted_top.B.f3dB_MHz',
        cbpl='aw3_threshold.assumed.Cbpl_pF', cfbA='aw3_threshold.assumed.Cfb_pF.A', cfbB='aw3_threshold.assumed.Cfb_pF.B',
        b21='an1.baseline_2pF.worst.BEH21.pm', b60='an1.baseline_2pF.worst.BEH60.pm', bv='an1.baseline_2pF.worst.vendor.pm',
        a21='an1.A_2pF_plus_top.worst.BEH21.pm', a60='an1.A_2pF_plus_top.worst.BEH60.pm', av='an1.A_2pF_plus_top.worst.vendor.pm',
        t21='an1.B_top_only.worst.BEH21.pm', t60='an1.B_top_only.worst.BEH60.pm', tv='an1.B_top_only.worst.vendor.pm',
        sA21='an1_with_bin_strays.A.BEH21.pm', sA60='an1_with_bin_strays.A.BEH60.pm', sAv='an1_with_bin_strays.A.vendor.pm',
        sB21='an1_with_bin_strays.B.BEH21.pm', sB60='an1_with_bin_strays.B.BEH60.pm', sBv='an1_with_bin_strays.B.vendor.pm',
        w21='c304_pm_baseline.without_C304.BEH21.pm', w60='c304_pm_baseline.without_C304.BEH60.pm')),
    dict(name='awf', json=R + 'awg.json'),                 # the whole file, for the keys that carry a dot (Cpad_0.0pF)
)


def _cap(name, file, net, pour='True'):
    """an extraction line of a log read as a sentence: the extrapolated value and its spread, with the pour"""
    return dict(name=name, op='regex', file=R + file, pattern=net + r'\s+pour=' + pour + r'\s+converge.*?extrapolated ([\d.]+) \+- ([\d.]+) pF',
                found='{g[1]} +- {g[2]} pF', missing='not found in the log *(check)*')


# values computed in order from the data above: -3 dB frequencies in MHz, and the extraction lines read as sentences from the logs
EVIDENCE_DERIVED = (
    dict(name='f3b', op='div', a='sb.f3', b=1e6), dict(name='f3a', op='div', a='sa.f3', b=1e6), dict(name='f3B', op='div', a='sB.f3', b=1e6),
    _cap('capN1', 'cap_converge.txt', '/CH1_N'), _cap('capN2', 'cap_converge.txt', '/CH2_N'), _cap('capInv', 'cap_converge.txt', '/AWG_INV'),
    _cap('capIn1', 'cap_in_nets.txt', '/CH1_IN'), _cap('capIn2', 'cap_in_nets.txt', '/CH2_IN'),
    _cap('capBin', 'cap_in_nets.txt', '/AWG_BIN'), _cap('capBpl', 'cap_in_nets.txt', '/AWG_BPL'),
    _cap('capNP', 'cap_converge.txt', r'NP-NP \(\+IN pads\)', 'True'),
)
EVIDENCE = (
    dict(kind='text', text=(
        '**The `pcbtools.cap --converge` extraction was re-run on the board of this package and reproduces the first run on the earlier merge (`v1_merge5`) figure for figure; the IN-net and AWG_BPL figures (own scripts, coarser cells) were taken on `v1_merge5`, whose copper on those nets is the same, and were not re-run *(check)*.** '
        'the REFCAL, POWER and silk changes since touch no copper of the scope or AWG nets read here, which the re-run on this board confirms for the nets in CAP_SELF and CAP_PAIRS. '
        'The logs are `v1/results/cap_converge.txt` and `cap_in_nets.txt` (the 0.05 mm level does not fit 3 M cells on the IN nets, so those use 0.4 / 0.2 / 0.1 mm). '
        '**Not validated against a field solver.** The sequences are mostly *not* monotone: at these cell sizes a 0.2 mm track and the 0.3 mm pour keep-back change by whole cells between levels, '
        'so each figure is a value with a spread, not a converged limit (the "+-" is the log\'s own spread).\n')),
    dict(kind='table', id='cap_rows', head=['net', 'with the top pour: extrapolated +- spread', 'top of the bar used by the study (pF)', 'where it enters'], rows=(
        ('/CH1_N (divider node, with pour)', '{capN1}', '{sB[cn]:n3} (N, both channels)', 'SC-3 / SC-5 / SC-9 cases A and B, `Cn_par`'),
        ('/CH2_N (divider node, with pour)', '{capN2}', '{sB[cn]:n3}', 'same'),
        ('/CH1_IN (BNC to R1, with pour)', '{capIn1}', '{sB[cwire]:n3} (IN)', 'SC-5 / SC-9, `Cwire`'),
        ('/CH2_IN (with pour)', '{capIn2}', '{sB[cwire]:n3}', 'same'),
        ('/AWG_INV (inverting node, with pour)', '{capInv}', '{aw[cfbB]:n2}', 'AN-1 of the AWG, `cfb` (case B; A adds it to the assumed 2 pF)'),
        ('/AWG_BIN (+IN node, with pour; before the pad correction of `cap_in_nets.txt`)', '{capBin}', '{aw[top]:n3} (after it)', 'AW-3 threshold below'),
        ('/AWG_BPL (offset-divider node, with pour)', '{capBpl}', '{aw[cbpl]:n3}', 'AW-3 / AN-1'),
        ('NP-NP, the two +IN pads (with pour)', '{capNP}', 'pad-pad: see `cap_in_nets.txt`', 'SC-9 pad-pad'))),
    dict(kind='text', text='\n**N-N and IN-IN couplings are below 0.05 fF** (numerically zero in both logs; 0.05 fF is what the study uses), so channel-to-channel coupling through the divider nodes is not the limit.\n\n'),
    dict(kind='text', text=('**LR-3 evidence: the scope with the extracted strays put back** (`v1/results/scope_*.json`; study definition `v1/sim/README.md`; the study is v2\'s harness with v1\'s values, '
                            '`results/spicecmp.txt` shows the patched netlists are v1\'s circuit: scope 28 / 28 elements, AWG 14 / 14, four mutants fail as they must). Baseline = v2\'s assumptions (3.5 pF at N, 4 pF BNC and trace); '
                            'case A adds the extraction at the top of its bar; case B replaces the assumption by it:\n')),
    dict(kind='table', id='scope_rows', head=['figure', 'limit', 'baseline', 'A (extraction added)', 'B (extraction replaces)'], rows=(
        ('SC-5 / SM-3 -3 dB at the ADC pin (MHz)', '>= 8, no filter', '{f3b:n4}', '{f3a:n4}', '{f3B:n4}'),
        ('SC-3 input capacitance at 1 MHz (pF)', '<= 30', '{sb[c1m]:n4}', '{sa[c1m]:n4}', '{sB[c1m]:n4}'),
        ('SC-3 input resistance at 1 kHz (kohm)', '1000 nominal', '{sb[r1k]:n5}', '{sa[r1k]:n5}', '{sB[r1k]:n5}'),
        ('SC-3 shelf (%)', 'information', '{sb[shelf]:n3}', '{sa[shelf]:n3}', '{sB[shelf]:n3}'),
        ('SC-9, 6 Vpp at 10 MHz (LSB)', '<= 2', '{sb[sc9]:n3}', '{sa[sc9]:n3}', '{sB[sc9]:n3}'),
        ('SC-9 sensitivity N-N (fF per LSB at 10 MHz)', 'information', '{sb[nn]:n3}', '{sa[nn]:n3}', '{sB[nn]:n3}'),
        ('SC-9 sensitivity pad-pad (fF per LSB)', 'information', '{sb[pp]:n3}', '{sa[pp]:n3}', '{sB[pp]:n3}'),
        ('SC-9 sensitivity IN-IN (fF per LSB)', 'information', '{sb[inin]:n3}', '{sa[inin]:n3}', '{sB[inin]:n3}'),
        ('AN-1 scope phase margin BEH21 (deg)', '>= 45', '{sb[pm21]:n3}', '{sa[pm21]:n3}', '{sB[pm21]:n3}'),
        ('AN-1 scope phase margin BEH60 (deg)', '>= 45', '{sb[pm60]:n3}', '{sa[pm60]:n3}', '{sB[pm60]:n3}'),
        ('AN-1 scope phase margin, vendor macro (deg)', '>= 45', '{sb[pmv]:n3}', '{sa[pmv]:n3}', '{sB[pmv]:n3}'))),
    dict(kind='text', text=('\nThe scope phase margin does not move with the strays (the strays sit on the divider and the pin, not at the op-amp\'s inverting node). The vendor macro is a single amplifier: '
                            'the shared-die crosstalk of the TPH2502 dual is **not modelled** (VT-10 on the first boards is where it is measured, `docs/afe.md` SC-9), and the 0R corridor bridges are shorts in the model *(check)*. '
                            'The SC-9 margin is 2 LSB less the table\'s value in every case.\n\n')),
    dict(kind='text', text=('**The AWG stage: AN-1 and AW-3** (`v1/results/awg.json`). The inverting-node stray `cfb` is v2\'s assumed 2 pF (baseline), 2 pF plus the extraction ({aw[cfbA]:n3} pF, A) or the extraction alone '
                            '({aw[cfbB]:n2} pF, B; /AWG_INV {capInv} with pour); worst of five loads and two rail corners:\n')),
    dict(kind='table', id='awg_an1', head=['AN-1 AWG phase margin (deg), requirement >= 45', 'BEH21', 'BEH60', 'vendor macro'], rows=(
        ('baseline, cfb 2 pF', '{aw[b21]:n3}', '{aw[b60]:n3}', '{aw[bv]:n3}'),
        ('A, cfb {aw[cfbA]:n3} pF', '{aw[a21]:n3}', '{aw[a60]:n3}', '{aw[av]:n3}'),
        ('B, cfb {aw[cfbB]:n2} pF', '{aw[t21]:n3}', '{aw[t60]:n3}', '{aw[tv]:n3}'),
        ('A with the /AWG_BIN stray at its top of bar {aw[top]:n3} pF', '{aw[sA21]:n3}', '{aw[sA60]:n3}', '{aw[sAv]:n3}'),
        ('B with the /AWG_BIN stray at its top of bar {aw[top]:n3} pF', '{aw[sB21]:n3}', '{aw[sB60]:n3}', '{aw[sBv]:n3}'),
        ('baseline without C304 (for comparison)', '{aw[w21]:n3}', '{aw[w60]:n3}', '-'))),
    dict(kind='text', text=('\n**AW-3 (the AWG\'s bandwidth, {aw[limit]:n3} MHz) against the +IN node stray: the threshold is {aw[thr]:n3} pF** of /AWG_BIN stray (bisection 0-20 pF, tolerance {aw[tol]:n3} pF, the 13 steps are logged in `awg.json`; '
                            'monotonic is assumed and was checked at 0 / 5 / 10 / 20 pF). The extracted top of bar is **{aw[top]:n3} pF**, so the margin is **{aw[margin]:n3} pF**; '
                            'at the extracted top the -3 dB point is {aw[fA]:n3} MHz (A) and {aw[fB]:n3} MHz (B). C304 (10 pF across Rbin, a zero at 312 kHz) is what makes the margin: '
                            'with it the -3 dB point is {awf[c304_bandwidth][Cpad_0.0pF][with_C304][f3dB_MHz]:n3} / {awf[c304_bandwidth][Cpad_4.0pF][with_C304][f3dB_MHz]:n3} MHz at 0 / 4 pF of stray, without it {awf[c304_bandwidth][Cpad_0.0pF][without_C304][f3dB_MHz]:n3} / {awf[c304_bandwidth][Cpad_4.0pF][without_C304][f3dB_MHz]:n3} MHz, which fails AW-3 at every stray. '
                            'Assumed: C304 10 pF; AWG_BPL stray {aw[cbpl]:n3} pF (extracted top of bar); vendor macro, hi-Z load. '
                            '(The extraction behind the {aw[top]:n3} pF was re-run on this board and is unchanged.)\n')),
    dict(kind='text', text=(
        '\n**Recorded rulings that no checker row reads** (`kicad/gate3/notes.md`, items 1, 2, 8, 13, 16; quoted as recorded, not regenerated). '
        '(1) **LR-2, IN pad to the N bus 10.22 mm in both channels** (asked 10-11 mm; CH1_R1A node 6.1 mm, CH1_N and CH2_N 8.2 mm each with stubs): a recorded deviation. '
        '(2) **LR-2, the CH2 output run** 17.8 mm against the divider side 22.7 mm (CH1 24.1 against 21.4) was accepted as a second deviation on the merge, with the condition that the N self-capacitance and IN stray of both channels '
        'are extracted with `cap.py --converge` and the scope simulation run at the top of the error bar: that condition is the table above. '
        '(8) **On the integrated board that deviation is moot**: with the A0 and A1 corridors routed to J602 the output side is 45 mm and 51 mm and LR-2 passes. '
        '(13) **REFCAL\'s interior** was placed and routed on the router flow (Freerouting 2.5.0 in the image; five runs of 40-50 s, with the VREF legs, TAPs, the +3V3A trunk, part of the sense nets and the four north exits by hand); '
        'LR-5, LR-6, LR-8 and LR-12 pass on this board, zero unconnected; **the analog performance (loop areas, SNS pair matching) was NOT assessed** *(check)*. '
        '(16) **The SNS pair legs are unequal by 5.05 mm** (tap leg R502.1 > R513 > U502.6 8.54 mm, bottom leg R502.2 > R514 > U502.7 13.59 mm along the copper, resistor pad-to-pad spans included; measured on `v1_merge5` '
        'in `bom/v1/measure.txt`, with R109 present, which that file says changes no SNS figure; the track gap along the pair is 0.300 mm at best): **accepted by the spec team on 2026-11-13. There is NO copper-length requirement**: '
        'the source-impedance match of PA-4 is by the Rs and Rm resistors (a DC differential reading at 860 SPS), and unequal pickup of fast noise is negligible at 16 mm from AWG_OUT and 16-20 mm from the pump. '
        'The contract table\'s earlier "pair rule" wording is corrected.\n')),
)

# ---------------------------------------------------------------------------------------------------- section 7: BOM and cost
BOM_ENGINE = AFE + 'v2/bom/bom.py'          # the one engine, shared with v2 (Data(folder, paths), lines, Part, tier, cost, FX, D_RATIO, PER_ORDER_MAX)
BOM_DATA_DIR = AFE + 'bom/v1/data'
BOM_PATHS = {k: AFE + v for k, v in (('scope', 'bom/v1/data/scope_parts.csv'), ('awg', 'bom/v1/data/awg_parts.csv'),
                                     ('powercal', 'bom/v1/data/powercal_parts.csv'), ('basic', 'v2/jlc-basic.csv'))}    # the engine's --path overrides
BOM_EXTRA_CSV = 'bom/v1/data/extra.csv'
BOARD_COUNTS = (5, 10, 20, 100)             # the board-count tiers priced, as v2
REPORT_BOARDS = 20
TARGET_BOARDS = (20, 100)
OWNER_FITTED_LCSC = ('C2837587',)           # the BNC, as v2
BRIDGE_PART = dict(lcsc='C21189', footprint_prefix='Resistor_SMD:R_0603')
WATCH_PACKAGES = ('2512', '2010')
BOM_INTRO = ('Version 1 and version 2 are priced by **one engine**, `v2/bom/bom.py`; version 1\'s inputs are `bom/v1/data/` (`scope_parts.csv`, `awg_parts.csv`, `powercal_parts.csv` generated from `kicad/design.py` by `bom/v1/make_parts.py`, '
             '`catalog.csv`, `intl.csv`, `blocks.csv`, `extra.csv`; the Basic table is `v2/jlc-basic.csv`) and the engine\'s own report is `bom/v1/bom.md`. Parts, LCSC numbers, footprints and quantities are read from the board; prices, Basic/Extended class and the fee model are the engine\'s '
             '(domestic JLC Economic SMT, PCB included, owner-fitted parts separate). Exchange rate {fx} CNY/USD (bom.py\'s constant, *(check)*: it moves daily). '
             'Nine v1-only types carry the ladder recorded in `bom/v1/legacy/bom-2026-11-13.md` (read 2026-11-12, not re-read) and no international ladder *(check)*.\n')
BOM_UNIT_NOTE = ('Unit prices are the quantity tier holding (boards, capped at one 50-board order, x parts per board) pieces, as the engine does; the BNC is owner-fitted and tiered on all boards. ')
BOM_RECONCILE_NOTE = ('The engine lists are generated from `kicad/design.py`, so no difference between board and engine lists is expected: the reconciliation above is the proof (99 placements, 234 SMT joints, 33 types of which 4 Extended, 16 bridges of C21189). '
                      'The mounting holes on the board are M2.5 (`MountingHole_2.7mm_M2.5`: MH601, and MH602 as the optional position of the courtyard item); `extra.csv` carries `MH-so25` and `MH-sc25` as owner-fitted and unpriced, as v2\'s does, because the repo has no M2.5 standoff or screw LCSC number *(check)*. '
                      'The header set is priced as in v2 (three retail listings, tail length unchecked *(check)*), and the CAL header J501 is unpriced.')
BRIDGE_PART_TEXT = ('\n**The {n} fitted 0R bridges (LCSC {c}, {mfr}, {cls}) are priced** from the same JLC call as every other part (read {read_utc} UTC; ladder in `v2/bom/intl.csv`; '
                    'the domestic page was not read, so the price is the international ladder times {ratio} and is marked D): '
                    '{u:n4} CNY each at the 20-board tier. Unpriced on the board: {unpriced}. DNP on the board and left out of every count: {dnp}.\n')
BOM_PCB_NOTE = ('The PCB row is the engine\'s published rule (engineering fee + CNY/m2 x area, 410 CNY/m2, board outline `BOARD_MM` in `bom.py` = 100 x 62.34 mm, which is version 1\'s outline too), **not a quote**; '
                'the header price is a retail listing with its tail length unchecked *(check)*; '
                'the calibration jumper pins, J501 and the M2.5 hardware are unpriced and in no total; shipping outside Guangdong, attrition and the 8 cm tape rule are excluded.')
COST_TARGET = ('The owner\'s target is about $35 per board for the first batch, PCB included (`docs/afe.md` MC-12, 2026-11-11), against which the version 1 baseline `b3a3bf3` was $37.08 / $37.45 at 20 boards. '
               'Both totals below are well under it; the margin is the difference, and it rests on the unverified items above.')
COST_TARGET_RESULT = (' Version 1 as above is ${a_lo:.2f} / ${a_hi:.2f} at {a} boards and ${b_lo:.2f} / ${b_hi:.2f} at {b} '
                      '(board-adjusted, bridges included, owner-fitted M2.5 hardware and J501 unpriced; the two figures are the X-ray priced wholly at its tier / tier by tier).')
GAPS = (
    'Renders are made by `kicad/render.sh` in the PCB image: a copper-and-silk top view and a bottom-copper view (SVG rasterised with the image\'s `svg2png.sh`), the two 3D renders (top, bottom) and one crop of the top silk per overhang band (the Due\'s pin names). '
    'Section 1 says whether each is newer than the board.',
    'The capacitance extraction was re-run on this board (identical to the first run on `v1_merge5`); the scope / AWG study (`v1/results/`) takes its figures from it and is unchanged; `v1/results/*.txt` are the logs read here. '
    'The IN-net and AWG_BPL figures (own scripts, coarser cells) were taken on `v1_merge5` and not re-run *(check)*.',
    'The ripple evidence for the LM27762 capacitor placement is v2\'s pw2_ac model run with v1\'s measured distances (`v1/results/pw2_ac_v1.json`, `v1/sim/pw2_ac_README.md`); its figures are in the LR-5 deviation row (section 5), not in a section-6 row *(check)*.',
    'The spec team\'s rulings (the silk waivers, the C301/C304 exception, the power caps and the in-band ripple fallback, R517-R519 under D24, the 0.45 mm edge clearance, the outline and pin-label ruling, R109\'s removal, the unequal sense legs) are recorded in `kicad/gate3/notes.md` '
    '(the running record, kept with this package); the MH602 caliper check is the gate brief\'s statement, not a repo file *(check)*. The D24 count review and the MC-1 amendment are in `docs/afe.md`, cited in sections 4 and 5.',
    'The C301 and C304 labels are ambiguous at 0.33 mm (both 10 pF C0G 0603, C301 across Rf, C304 across Rbin, stacked in the AWG block): a recorded exception to the hard rule, accepted by the spec team because board-house assembly places from the CPL, not the silk, '
    'so only a hand rework could misread them; check the value before replacing either; F.Fab arrows run from each label to its part.',
    'Prices: every ladder was read 2026-11-11 / 12 and not re-read; C21189 was never read (priced from the international read of v2, marked D); the PCB is a published rule, not a quote; the owner-fitted headers are priced from v2\'s three retail listings; '
    'the M2.5 standoff and screws are unpriced. The 5- and 10-board tiers are in the engine\'s table.',
)
