"""Gate-3 table of the v2 layout of record: every source and every board-specific sentence the generic engine (pcbtools/gate3) needs,
as named fields and no logic. Fields are described in pcbtools/gate3/README.md. Paths are relative to the repository root. The prose
fields are templates: `{name}` is filled by the engine (the names each one receives are listed in the README), `{name:n3}` formats a
number the way the document does, and `{name[key]}` indexes a mapping.

    python3 -B -m pcbtools.gate3 --config v2_layout --table gate3_v2 --out hardware/afe-proto/v2/layout/gate3
"""

AFE = 'hardware/afe-proto/'

# ---------------------------------------------------------------------------------------------------- identity and files
TITLE = 'v2 AFE integrated layout'
GENERATED_BY = '`v2/layout/gate3/build_gate3.sh` (`gate3.py`)'
BOARD = AFE + 'v2/layout/integrated/afe-v2-integrated.kicad_pcb'
PROJECT = AFE + 'v2/layout/integrated/afe-v2-integrated.kicad_pro'
RENDER_DIR = AFE + 'v2/layout/integrated/render'
RENDERS = (('top (F.Cu + silk)', 'afe-v2-integrated-F.Cu-silk.png'), ('bottom (B.Cu)', 'afe-v2-integrated-B.Cu.png'),
           ('3D top', 'afe-v2-integrated-3d.png'), ('3D bottom', 'afe-v2-integrated-3d-bottom.png'))
RENDER_LINK_PREFIX = '../integrated/render/'              # the renders as the document links them, relative to GATE3.md
RENDER_HINT = '(`v2/layout/render.sh`; it needs `magick`, which x1\'s image lacks).'
DUE_ORIGIN = (50.0, 150.0)                                # KiCad x = 50 + x, KiCad y = 150 - y: the Due-mm frame the document quotes
RULE_DOC = 'docs/afe.md'                                  # the rule table (`| LR-n | text |` rows) and the cited D24 / MC-1 rows

SECTION_SOURCES = (
    ('1 Renders', 'PNGs in `v2/layout/integrated/render` (not regenerated here; checked for existence and age against the board)'),
    ('2 LR table', '`pcbtools.rules.ROWS` on the board with `boards/v2_layout.py`; LR-10 from kicad-cli; rule text from `docs/afe.md`'),
    ('3 DRC', 'kicad-cli `pcb drc --severity-all` on a work copy of the board and its project file'),
    ('4 Bridges and hops', 'board arrays (pads, tracks, vias) via `gate3.bridge_table` / `hop_table`; justifications from `v2/kicad/design.py` `BRIDGES`'),
    ('5 Deviations', 'rule figures (2), board (power caps, outline), `boards/v2_layout.py` waiver tables, project file rules; cited spec text is quoted from the named file'),
    ('6 Cap and ripple rows', '`pcbtools/cap_converged_v2_integrated.json`, `v2/sim/scope/sensitivity_n_stray.json`, `v2/sim/powercal/pw2_ac/results/pw2_ac_results.json` and `GATE3_ROW.md`, `v2/sim/awg/report_table.md` and `design.md` (read, not recomputed)'),
    ('7 BOM and cost', 'LCSC/value/footprint from the board; prices and the cost model from `v2/bom/*.csv` through `v2/bom/bom.py` (the engine that writes `bom.md`)'),
)

# ---------------------------------------------------------------------------------------------------- section 2: the LR table
LR_HEADING = '## 2. LR table (rules LR-1 to LR-11 on the integrated board)'
LR_INTRO = ('Verdicts are the checker\'s own (`python3 -B -m pcbtools.check BOARD --config {config} --drc`, called through the library so the figures are kept). '
            'The rule text is `docs/afe.md`\'s, shortened to its first sentence; the full text is there. '
            'The supply-pin decoupling distance is a sub-check of **LR-4** ("each supply pin has its 100 nF within a few millimetres", `docs/afe.md`), printed here as '
            '"LR-4 decoupling" with the config\'s limit; the checker\'s own name for that row is `LR-12 DECOUP_MAX` (`pcbtools/rules.py`; tests and goldens key on it), '
            'and `docs/afe.md` has no LR-12 row. The rule numbers in this table are `docs/afe.md`\'s.\n')
LR_DOC_ROWS = ('LR-1', 'LR-2', 'LR-3', 'LR-4', 'LR-5', 'LR-6', 'LR-7', 'LR-8', 'LR-9', 'LR-10', 'LR-11')      # rows whose text is in RULE_DOC
LR_RENAMES = (('LR-12 DECOUP_MAX', 'LR-4 decoupling (DECOUP_MAX {:.1f} mm)', 'DECOUP_MAX'),)             # (checker row, label shown, config field filling {})
LR_SUBCHECKS = (('INV_MAX', '(LR-4 sub-check) the inverting-node trace is the shortest of the stage'),
                ('LR-4 decoupling', '(LR-4 sub-check) each supply pin has its 100 nF within a few millimetres'))
DRC_ROW = 'LR-10'                                          # the row the engine adds from kicad-cli DRC

# ---------------------------------------------------------------------------------------------------- section 3: DRC
DRC_DOCUMENTED = (('courtyards_overlap', 'MH602'),)        # (violation type, a reference it names): documented, not counted as "other"
DRC_DOCUMENTED_LABEL = 'MH602 courtyards'
DRC_DOCUMENTED_NOTE = ('**The MH602 courtyard overlaps** (MH602 with the sockets J607 and J605) are the Due\'s own geometry: MH602 is the optional M2.5 standoff position beside the socket '
                       'rows. The older layout notes record it as "M2.5, screw optional, verify socket clearance" (`tests/fixtures/v2-8a1f7ac/floorplan.py`). '
                       '**The owner\'s caliper check of the socket clearance is pending**, and the screw is optional, so the overlap costs nothing if the screw is left out. '
                       '(The caliper status is the gate brief\'s statement, not a repo file *(check)*.)')
RULE_DIFF_TEXT = ("**The project file next to the board does not carry the design's rules.** `{n}` rule value(s) in `afe-v2-integrated.kicad_pro` differ from `BOARD_SETUP` in `pcbtools/boards/v2_layout.py` "
                  "(the values `v2/layout/outline_overhang.py` writes). The file was last written at the same moment as the board (see its time), and its values read like KiCad's defaults; "
                  "**the board agent should rerun `outline_overhang.py`'s `apply_pro` or restore the file before the gate**. LR-10 in section 2 is the checker's, at the file as it stands (run A). Run B repeats DRC with the design's rules applied to a scratch copy of the project file.\n")

# ---------------------------------------------------------------------------------------------------- section 4: bridges and hops
BRIDGE_REF_PATTERN = r'BR\d+'                              # which footprints on the board are bridges (re.fullmatch)
BRIDGES_SOURCE = ('pcbtools.boards.v2', '_design.BRIDGES')   # (module, attribute path): (ref, net a, net b, block, justification) tuples
# how a crossed net is classed, from config fields: adc = fields joined, divider = fields joined, vref = prefix field, other = first minus second
NET_CLASS_FIELDS = dict(adc=('CHANNELS.out_nets', 'ADC_NETS'), divider=('HIZ', 'DIVIDER_GROUPS'), vref_prefix='VREF_NET', other=('XSENS', 'HIZ'))
D24_ROW_PATTERN = r'\| D24 \|[^\n]*'
D24_QUOTE_PATTERN = r'The "1 to 3" first estimated was wrong[^|]*?which is where the count is reviewed'
D24_FOUND = ('`docs/afe.md` (row D24) says, quoted from the file: "{quote}". The sentence arrived on main with commit 446bb68, which the document does not name; '
             'it is cited here as the file\'s text. ')
D24_MISSING = ('The spec lead\'s message records that D24 was updated on main in commit 446bb68: the "1 to 3 in all" was an estimate, and the count is now reviewed in this table. '
               '(`docs/afe.md` in this tree does not carry that wording, so it is cited as quoted from the spec lead\'s message, not as a repo file.) *(check)* ')
BRIDGE_ACCEPT = (' **All {nb} bridges are accepted, including the {nover} over ADC or VREF lines** ({over}): LR-1 prescribes exactly this method '
                 '(a top-layer 0603 0 ohm bridge over the ADC trace, never a bottom hop under it). {parts}; {div}. The last column says which bridges sit over a net of those classes.\n')

# ---------------------------------------------------------------------------------------------------- section 5: deviations
POWER_CAPS = dict(ic='U401', caps=('C401', 'C402', 'C403', 'C404', 'C405', 'C406', 'C407', 'C408', 'C409'), far_mm=5.0)
POWER_CAPS_CAPTION = '**LM27762 capacitor distances on this board** (nearest U401 pad on the same net; the farther pin for the flying capacitor C409):'
CFG_QUOTED = ('HOP_MAX', 'HOP_MAX_VIAS', 'DESIGNATOR_FOREIGN_WAIVED', 'DESIGNATOR_GAP_WAIVED', 'DESIGNATOR_GAP_MIN', 'DESIGNATOR_GAP_ONE_LABEL')   # config fields quoted
CFG_FOREIGN_WAIVED = 'DESIGNATOR_FOREIGN_WAIVED'          # {ref: block}
CFG_GAP_WAIVED = 'DESIGNATOR_GAP_WAIVED'                  # {(ref, ref): floor mm}
CFG_GAP_MIN = 'DESIGNATOR_GAP_MIN'
CFG_GAP_ONE_LABEL = 'DESIGNATOR_GAP_ONE_LABEL'
# each deviation row is (rule / item, deviation text, status / authority text)
DEV_COURT = ('DRC / courtyards', '{items}: courtyards overlap', 'documented; owner caliper check pending, screw optional (section 3)')
DEV_POWER = ('LR-5 (generator caps at their pins)',
             'capacitors more than {far_mm:n3} mm from their {ic} pad: {far}; the nearer ones: {near} mm (all measured here, pad centre to pad centre; full list below)',
             'the far (second) capacitors accepted by the spec lead (gate brief; not a repo file *(check)*); PW-2 AC analysis, section 6')
DEV_FOREIGN = ('LR-11 designators', '{n} label(s) waived as sitting in a foreign block outline{detail}',
               'DESIGNATOR_FOREIGN_WAIVED in `pcbtools/boards/v2_layout.py`, read at run time')
DEV_FOREIGN_EMPTY = ' (the table is empty in `v2_layout.py` as read now)'
DEV_GAP = ('LR-11 designators', '{n} label pairs under the {gap_min} mm gap, each held to a floor: {pairs}',
           'DESIGNATOR_GAP_WAIVED (floors in mm; same-baseline pairs under {one_label} mm are never waivable)')
DEV_OUTLINE = ('MC-1 board outline',
               'the board overhangs the Due by {overhang} mm on the analog-header edge: {w:.2f} x {h:.2f} mm against the {max0} x {max1} mm bound; the band is a copper keep-out ({band})',
               None)                                       # the authority text is MC1_FOUND or MC1_MISSING
MC1_COMMIT = 'caba9c8'
MC1_PATTERN = r'Amended by the owner, 2026-11-13[^|]*overhangs the Due by 5 mm'
MC1_FOUND = ('owner ruling 2026-11-13, in `docs/afe.md` row MC-1 ("Amended by the owner, 2026-11-13 ... the outline overhangs the Due by 5 mm", '
             'read from the file at run time; amendment commit caba9c8, not named in the document)')
MC1_MISSING = 'owner ruling 2026-11-13, MC-1 amended on main (`caba9c8`); `docs/afe.md` in this tree does not carry the wording *(check)*'
DEV_EDGE = ('copper-to-edge', 'min_copper_edge_clearance {edge_rule} mm in the project file (config says {edge_cfg} mm)',
            'fabricator minimum 0.2 mm *(check)*, outline tolerance 0.2 mm, so 0.45 leaves 0.25 mm worst case (spec team ruling, `boards/v2_layout.py`)')
DEV_PROOF = ('+5V_F feed (information, not a deviation)', '+5V_F: {tracks} tracks, {length:.1f} mm, {vias} vias, {zones} zone fills, pads {pads}: {result}',
             'proven in 5.1 (copper graph, kicad-cli DRC with 0 unconnected, and a broken-once arm); LR-6 does not look at +5V_F')
DEV_PROOF_JOINED = 'U401 pins 3 and 12 are joined to R406 pin 2 by copper tracks alone (one piece); no pour is involved'
DEV_PROOF_NOT = '**U401 pin 3 or 12 is NOT joined to the source: see 5.1**'
# the margins table: checker figures against config limits. row = the checker's row name, key = a figure of it, limit = a config field;
# each_of = every figure of that row, each against its limit
MARGINS = (
    dict(rule='LR-5', what='sensitive copper to U401/C409 (mm)', row='LR-5', key='min_distance_mm', limit='KEEPOUT', kind='min'),
    dict(rule='LR-1', what='longest bottom hop (mm)', row='LR-1', key='max_run_mm', limit='HOP_MAX', kind='max'),
    dict(rule='LR-1', what='vias on the longest hop', row='LR-1', key='max_run_vias', limit='HOP_MAX_VIAS', kind='max'),
    dict(rule='LR-4 INV_MAX', what='AWG_FB inverting node (mm)', row='LR-4 INV_MAX', key='AWG_FB', limit='INV_MAX', kind='max'),
    dict(rule='LR-4 INV_MAX', what='CH1_OUT (mm)', row='LR-4 INV_MAX', key='CH1_OUT', limit='INV_MAX', kind='max'),
    dict(rule='LR-4 INV_MAX', what='CH2_OUT (mm)', row='LR-4 INV_MAX', key='CH2_OUT', limit='INV_MAX', kind='max'),
    dict(rule='LR-4', what='AWG_FB node track length (mm; FB_MAX)', row='LR-4', key='fb_mm', limit='FB_MAX', kind='max'),
    dict(rule='LR-4 decoupling', each_of='LR-12 DECOUP_MAX', limit='DECOUP_MAX', kind='max'),
)

# ---------------------------------------------------------------------------------------------------- section 5.1: the connectivity proof
PROOF = dict(net='/+5V_F', source='R406.2', pins=('U401.12', 'U401.3'), upstream=('/+5V_DUE', 'R406.1', 'J601.5'), on_net_head='on +5V_F',
             arms=(('stub at U401 pin 12', 'U401.12', 'first'), ('stub at U401 pin 3', 'U401.3', 'first'), ('trunk, middle of the pin 3 run', 'U401.3', 'middle')))
PROOF_PATH_ORDER = ('U401.12', 'U401.3')
PROOF_HEADING = '\n### 5.1 +5V_F: what joins U401 pins 3 and 12 to the source ({status})\n'
PROOF_INTRO = ("`{net}` is the LM27762's filtered 5 V feed: R406 (1 ohm sense resistor, pin 1 on `/+5V_DUE`, pin 2 on `{net}`) feeds U401 pin 3 (VIN), pin 8 (EN-) and pin 12 (EN+), "
               "and C401, C402 and TP403 (`v2/kicad/design.py`; U401's pins as listed there). The check below is `v2/layout/gate3/connectivity.py`: the copper graph of the net built from the board arrays "
               "(track capsules, via annuli, pad boxes, and the fills of any filled zone of that net), run on the board as it stands.\n")
PROOF_COPPER = ('**Every piece of copper on the net.** {tracks} tracks ({length:.1f} mm, all F.Cu), {vias} vias, {npads} pads ({pads}), '
                '{arcs} arcs, **{zones_on_net} zone fills on the net**. The board has {nzones} zones:\n')
PROOF_RESULT = ('**Result.** The graph has {ncomp} connected piece(s) of `{net}` copper: {pieces}. With every zone fill left out the result is {same}'
                ' (there is no fill on this net to leave out). So U401 pin 12 {j_a} joined to the source {src} by tracks alone'
                ', and so is pin 3 ({j_b}); **no via and no pour is involved**.\n')
PROOF_PATH_HEAD = ('**Path, {ref} pin {pin} to {src}** (coordinates are Due mm: KiCad x = 50 + x, KiCad y = 150 - y; '
                   'the link says how each item touches the one before it):\n')
PROOF_HISTORY = ('**What the earlier wording got wrong.** GATE3 used to report these pins in different pieces, "joined only through a pour or not at all". That came from the '
                 'old `net_summary`, which joined two tracks only when their end points coincided within 0.01 mm and ignored vias and zones; on this net successive tracks meet at corners '
                 'where one end lies inside the other track\'s 0.3 mm width, which is copper contact and what KiCad counts. '
                 'That function is deleted; the graph above replaces it.\n')
PROOF_UPSTREAM = ('**Upstream of the sense resistor.** R406 pin 1 to J601 pin 5 (the Due 5 V pin) on `/+5V_DUE`: {n} items, {tracks} tracks, {vias} vias, '
                  '{fills} zone fills ({chain}).\n')
PROOF_UPSTREAM_NONE = '**Upstream of the sense resistor.** R406 pin 1 and J601 pin 5 on `/+5V_DUE` are **not** joined by copper in the graph.\n'
PROOF_DRC = ("**KiCad's own connectivity.** kicad-cli DRC (`--severity-all`, section 3) reports **{n} unconnected items** on the board, its nets assigned from the schematic: "
             "KiCad sees the net connected through the same tracks. The check is only worth that if it can fire, so one track is cut at a time in a scratch copy of the board file "
             "(the board is never touched), the graph predicts which pads lose the source, and DRC is run on the cut copy:\n")
PROOF_RULE = ('\n**Which rule sees this net.** LR-6 (the star rails) checks only `/+3V3A` and `/VNEG_G` (`STAR` and `GROUPS` in `pcbtools/boards/v2.py`); `/+5V_F` is in neither, and no LR row looks at its connectivity. '
              'The only check that sees it is LR-10 (kicad-cli DRC, unconnected items), which is what the figure above is, and this section\'s graph. '
              'LR-6 therefore says nothing about U401 pins 3 and 12.\n')

# ---------------------------------------------------------------------------------------------------- section 6: evidence rows
EVIDENCE_HEADING = '## 6. Capacitance, LR-3 evidence and ripple rows'
# the study files: `json` is a path; with `values` each named value is read by dotted path (and written to data/<write> when given), without it the whole file is `name`
EVIDENCE_DATA = (
    dict(name='cap', json=AFE + 'pcbtools/cap_converged_v2_integrated.json'),
    dict(name='sens', json=AFE + 'v2/sim/scope/sensitivity_n_stray.json'),
    dict(name='pw2', json=AFE + 'v2/sim/powercal/pw2_ac/results/pw2_ac_results.json', write='pw2.json', values=dict(
        outp_ideal='worst_datasheet_mv.ideal.outp', outp_ab='worst_datasheet_mv.asbuilt.outp',
        outn_ideal='worst_datasheet_mv.ideal.outn', outn_ab='worst_datasheet_mv.asbuilt.outn',
        vin_dc1m_ideal='cases.ideal.model.vin.bands_mv.dc_1M.rms', vin_dc1m_ab='cases.asbuilt.model.vin.bands_mv.dc_1M.rms',
        vin_1_10_ideal='cases.ideal.model.vin.bands_mv.1M_10M.rms', vin_1_10_ab='cases.asbuilt.model.vin.bands_mv.1M_10M.rms',
        vin_10_30_ideal='cases.ideal.model.vin.bands_mv.10M_30M.rms', vin_10_30_ab='cases.asbuilt.model.vin.bands_mv.10M_30M.rms',
        verdict_outp='verdict.outp', verdict_outn='verdict.outn', limit_mv='limit_mv')),
)
# values computed from the data above, in order: find (a list item matching), add, div, margins (limit - value per case), regex (a sentence read from a file)
EVIDENCE_DERIVED = (
    dict(name='awg', op='find', list='cap.figures', match=dict(figure='/AWG_FB', pour=True)),
    dict(name='top', op='add', args=('awg.extrapolated', 'awg.uncertainty')),
    dict(name='ratio', op='div', a=10.0, b='top'),
    dict(name='an1', op='regex', file=AFE + 'v2/sim/awg/design.md',
         pattern=r'min PM ([\d.]+) deg on BEH21 and \*\*([\d.]+) deg on BEH60\*\*.*?the vendor macro ([\d.]+)',
         found='vendor macro {g[3]} / BEH21 {g[1]} / BEH60 {g[2]} deg against the 45 deg requirement (`v2/sim/awg/design.md` section 3)',
         missing='not found in design.md *(check)*'),
    dict(name='sc9_margins', op='margins', data='sens.results', key='sc9_budget_0p02_0p02_10MHz_lsb', limit=2.0, sep=', ', case_split='_', fmt='{case} {margin:.2f} LSB'),
)
EVIDENCE = (
    dict(kind='text', text=('**Extracted capacitance** (`pcbtools/cap_converged_v2_integrated.json`; grid-converged over cell sizes 0.2 / 0.1 / 0.05 mm, Richardson-extrapolated where the sequence allows; "+-" is the file\'s own spread). '
                            '**Not validated against a field solver.** The sequences are mostly *not* monotone, which is the file\'s and `pcbtools/README.md`\'s finding: at these cell sizes a 0.2 mm track and the 0.3 mm pour keep-back (`round(0.3 / h)` cells) change by whole cells between levels, so each figure is a value with a spread, not a converged limit. '
                            'The extraction ran on the fixture board `{cap[board]}`, **not re-run on the current board** (it is heavy: `pcbtools.cap.report(converge=True)`); if the CH2 move changes the N-node copper, rerun it *(check)*.\n')),
    dict(kind='cap_table', data='cap'),
    dict(kind='text', text='\n(Pair values are stored in pF and shown here in fF.) Near-zero N-N values (about 1e-17 pF) are numerically zero: the pad-pair rows are the ones that carry information.\n'),
    dict(kind='text', when='awg', text=('**AWG_FB**: {awg[extrapolated]:n3} +- {awg[uncertainty]:n2} pF with pour, so {top:.2f} pF at the top of the spread, against AN-1\'s inverting-node tolerance row of 10 pF '
                                        '(`v2/sim/awg/design.md`): a margin of about {ratio:.0f}x. The 10 pF row\'s phase margin: {an1}.\n')),
    dict(kind='text', text='**LR-3 evidence: the scope sensitivity to the extracted N-node stray** (`v2/sim/scope/sensitivity_n_stray.json`; case A adds the extraction to the study\'s assumed 3.5 pF stray, case B replaces the assumption by it):\n'),
    dict(kind='matrix', data='sens', head0='figure', rows=(('f3dB_MHz', 'SC-5 f-3dB (MHz)'), ('droop_10MHz_dB', 'droop at 10 MHz (dB)'), ('nominal_shelf_pct', 'SC-3 shelf (%)'),
                                                           ('sc9_shared_rail_10MHz_lsb', 'SC-9 shared rail (LSB)'),
                                                           ('sc9_budget_0p02_0p02_10MHz_lsb', 'SC-9 combined-budget figure (LSB; margin below)'))),
    dict(kind='text', text=('\n**SC-9 budget margin** = 2 LSB (SC-9: "crosstalk at most 2 LSB", `docs/afe-v2.md`) minus the file\'s combined-budget figure `sc9_budget_0p02_0p02_10MHz_lsb`: '
                            '{sc9_margins}. **Case B (the extraction replacing the assumed stray) leaves the smallest margin**; case A leaves it larger than the baseline. The 10 MHz droop and SC-5 f-3dB barely move in case A; the SC-3 shelf moves by the amounts tabulated.\n')),
    dict(kind='text', text='**Ripple rows: PW-2 AC analysis** (`v2/sim/powercal/pw2_ac/GATE3_ROW.md`, results `results/pw2_ac_results.json`; **no PW-4 pass is claimed** there):\n'),
    dict(kind='table', id='pw2_rows', head=['node', 'judged by', 'figure (ideal / as built)', 'verdict'], rows=(
        ('OUT+ (+3V3A)', 'PW-2, against {pw2[limit_mv]:n3} mV pk-pk', 'worst of 1.7-2.3 MHz: {pw2[outp_ideal]:n3} / {pw2[outp_ab]:n3} mV pk-pk', 'PW-2 pass'),
        ('OUT- (VNEG)', 'PW-2, against {pw2[limit_mv]:n3} mV pk-pk', 'worst of 1.7-2.3 MHz: {pw2[outn_ideal]:n3} / {pw2[outn_ab]:n3} mV pk-pk', 'PW-2 pass'),
        ('VIN (+5V_F)', 'not a PW-2 node; judged by PW-4 in band (DC-1 MHz)',
         'ideal {pw2[vin_dc1m_ideal]:n3} vs as-built {pw2[vin_dc1m_ab]:n3} mV rms, equal; no PW-4 pass claimed (VT-8 bench); 10-30 MHz content unvalidated', 'no PW-2 verdict'))),
    dict(kind='text', text='\n**VIN band figures** (information; no limit is applied to them here):\n'),
    dict(kind='table', head=['band', 'ideal mV rms', 'as built mV rms', 'source key'], rows=(
        ('DC-1 MHz (PW-4 band)', '{pw2[vin_dc1m_ideal]:n3}', '{pw2[vin_dc1m_ab]:n3}', 'cases.*.model.vin.bands_mv.dc_1M'),
        ('1-10 MHz', '{pw2[vin_1_10_ideal]:n3}', '{pw2[vin_1_10_ab]:n3}', 'bands_mv.1M_10M'),
        ('10-30 MHz (**unvalidated**)', '{pw2[vin_10_30_ideal]:n3}', '{pw2[vin_10_30_ab]:n3}', 'bands_mv.10M_30M'))),
    dict(kind='text', text=("\nThe study JSON's own `verdict.vin` field is not used: it applies the OUT+/OUT- limit to VIN, which is not a PW-2 node. The row's own text: the model cannot resolve the OUT+/OUT- cap-distance question; PW-4's 0.3 mV rms is on the Due 3.3 V pin and AREF and is NOT judged "
                            "by it (VT-8's measurement); the 10-30 MHz VIN content is the model's switch-edge current and nothing validates it against the real part. Sensitivity: distance acts at the CP and VIN capacitors (C403, C404, C402, C401), not the output capacitors.\n")),
    dict(kind='text', text=('The PW-2 row quotes as-built distances from an earlier table (C401 8.55, C406 7.64 mm ...); section 5 above has this board\'s own measured distances (measured pad to pad on the current file); the two differ and the AC analysis used the older ones. '
                            'Whether the analysis needs a re-run after the CH2 move is the study owner\'s call *(check)*.\n')),
)

# ---------------------------------------------------------------------------------------------------- section 7: BOM and cost
BOM_ENGINE = AFE + 'v2/bom/bom.py'          # Data(folder), lines(data, flags), Part(data, lcsc, flags), tier(ladder, n), cost(...), FX, D_RATIO, PER_ORDER_MAX
BOM_DATA_DIR = AFE + 'v2/bom'
BOM_EXTRA_CSV = 'v2/bom/extra.csv'
BOARD_COUNTS = (5, 10, 20, 100)             # the board-count tiers priced
REPORT_BOARDS = 20                          # the tier of the per-board line column
TARGET_BOARDS = (20, 100)                   # the two tiers the cost-target sentence quotes
OWNER_FITTED_LCSC = ('C2837587',)           # parts tiered on all boards, not per order (the BNC)
BRIDGE_PART = dict(lcsc='C21189', footprint_prefix='Resistor_SMD:R_0603')
WATCH_PACKAGES = ('2512', '2010')
BOM_INTRO = ('Parts, LCSC numbers, footprints and quantities are read from the board. Prices, Basic/Extended class and the fee model are the repo\'s (`v2/bom/catalog.csv`, `intl.csv`, `../jlc-basic.csv`, `extra.csv`; engine `v2/bom/bom.py`, the same one that writes `v2/bom/bom.md`; domestic JLC Economic SMT, PCB included, owner-fitted parts separate). '
             'Exchange rate {fx} CNY/USD (bom.py\'s constant, Bank of China 2026-11-12 *(it moves daily)*).\n')
BOM_UNIT_NOTE = ('Unit prices are the quantity tier holding (boards, capped at one 50-board order, x parts per board) pieces, as the engine does; the BNC is owner-fitted and tiered on all boards. ')
BOM_RECONCILE_NOTE = ('The engine\'s lists come from the three stream `parts.csv` files, which predate the bridges: where the board has more of a part than the lists, the "board-adjusted" totals below add the excess as extra lines (block: other). '
                      'The mounting holes on the board are M2.5 (`MountingHole_2.7mm_M2.5`: MH601, and MH602 as the optional position of the LR-10 courtyard item; the owner\'s screw is optional). The engine used to price an M3 x 8 standoff (C66568) and M3 x 5 screws (C357542), version 1\'s parts, which do not fit an M2.5 hole: **both lines are removed from `v2/bom/extra.csv`**. '
                      'The repo carries no M2.5 standoff or screw LCSC number (searched: `v2/bom/*.csv`, `v2/jlc-basic.csv`, `v2/*.md`, `whatif/bom.md`, the KiCad design; `v2/kicad/README.md` says only "nylon or brass, header-stack height, DIN 912 M2.5 screws"), so **no M2.5 part is priced** *(check)*: the lines `MH-so25` and `MH-sc25` stay in the engine as owner-fitted and unpriced, in no total, and nothing was invented.')
BRIDGE_PART_TEXT = ('\n**The {n} fitted 0R bridges (LCSC {c}, {mfr}, {cls}) are priced** through `v2/bom/read_intl.py` (the same JLC call as every other part: the LCSC number only, read {read_utc} UTC; ladder in `v2/bom/intl.csv`; '
                    '`../jlc-basic.csv` lists the part as Basic, the domestic ladder was not read, so the price is the international ladder times {ratio} and is marked D like the others without one): '
                    '{u:n4} CNY each at the 20-board tier, so they are in the board-adjusted totals above ({stock}). '
                    'Unpriced on the board: {unpriced}. DNP on the board and left out of every count: {dnp}.\n')
BOM_PCB_NOTE = 'The PCB row is the published rule (engineering fee + CNY/m2 x area), **not a quote**; the header price is a retail listing with its tail length unchecked *(check)*; the calibration jumper pins are unpriced and in no total (all per `bom.md`).'
COST_TARGET = ('No numeric target exists in the repo: `v2/bom/bom.md` leaves D-V2-1 "_owner to set_", so no margin against a target can be computed; V2-4 asks for the cost at 20 and 100 boards. '
               'No comparison with version 1 is made here.')
COST_TARGET_RESULT = (' Version 2 as above is ${a_lo:.2f} / ${a_hi:.2f} at {a} boards and ${b_lo:.2f} / ${b_hi:.2f} at {b} '
                      '(board-adjusted, bridges included; owner-fitted M2.5 hardware unpriced).')
GAPS = (
    'Renders are the board agent\'s, not regenerated here; section 1 says whether each is newer than the board.',
    'Capacitance extraction is read from the committed JSON (fixture board 990d4b03), not re-run on the current board.',
    'PW-2 AC analysis used earlier as-built capacitor distances; not re-run for this board.',
    'The spec lead\'s acceptances (power second caps, the owner\'s caliper check of MH602) are the gate brief\'s statements; no repo file in this tree carries them *(check)*. (The 13-bridge count and the D24 update are in `docs/afe.md`, row D24, and cited there in section 4.)',
    'Prices: the PCB is a published rule, not a quote; the stacking headers are retail listings with tail length unchecked; calibration jumper pins are unpriced; no M2.5 standoff or screw part is priced (none in the repo).',
    'No numeric cost target exists in the repo (D-V2-1 is open).',
)
