"""Gate-3 table of the v1 layout: a TEMPLATE. Every field the engine reads is present (`pcbtools/gate3/README.md` describes each), the values
the repo gives are filled, and each field only the v1 board's owner can supply carries a `TODO(kvm_01):` marker. The engine refuses to
run while a marker is left, and names the field:

    python3 -B -m pcbtools.gate3 --config v1r --table gate3_v1 --check-table      # lists every field still to do

Fill a field by replacing the whole value (a marker inside a list or dict is found too). Where a field says "as v2", the v2 value is
in `gate3_v2.py`. Paths are relative to the repository root.

Facts this template rests on, from the repo: the latest v1 merge is `kicad/wip/v1_merge5` (kvm_01's running record is
`kicad/wip/gate3-notes.md`); v1's 0603 0R bridge part is C21189; the Due frame is the same as v2's; v1 has no BOM engine of its own (only
the text lists `whatif/bom.md` and `whatif/bom.txt`): `v2/bom/bom.py` is the engine, and v1's parts are its `v1.csv`.

The board CONFIG named on the command line (`--config v1r`) must also carry the fields the engine reads from it; `--check-table` does not
look at it, the run does and names what is missing. At the time of writing `boards/v1.py` lacks OVERHANG, BOARD_MAX_MM and BAND_NAME (it has
BOARD_RECT and KEEPOUTS, from which they follow): add them there, as `boards/v2_layout.py` has them.
"""

AFE = 'hardware/afe-proto/'

# ---------------------------------------------------------------------------------------------------- identity and files
TITLE = 'v1 AFE integrated layout'
GENERATED_BY = '`pcbtools/gate3` (`python3 -B -m pcbtools.gate3 --config v1r --table gate3_v1`)'
BOARD = AFE + 'tests/fixtures/v1-merge5-a256c8f/v1_merge5.kicad_pcb'                    # the latest merge in the repo; point at the integrated board when it exists
PROJECT = AFE + 'tests/fixtures/v1-merge5-a256c8f/v1_merge5.kicad_pro'
RENDER_DIR = 'TODO(kvm_01): folder holding the renders of the integrated board (kicad/render has only the 34b2e51-era afe-top.png and afe-iso.png)'
RENDERS = (('TODO(kvm_01): view name', 'TODO(kvm_01): png file name'),)             # (view, file name in RENDER_DIR), e.g. top / bottom / 3D
RENDER_LINK_PREFIX = 'TODO(kvm_01): the render folder as GATE3.md links it, relative to where GATE3.md is written (v2: ../integrated/render/)'
RENDER_HINT = 'TODO(kvm_01): the command that re-renders, in the form "(`command`; note)."'
DUE_ORIGIN = (50.0, 150.0)                                       # the Due frame, as v2
RULE_DOC = 'docs/afe.md'

SECTION_SOURCES = (
    ('1 Renders', 'TODO(kvm_01): where the renders are (not regenerated here; checked for existence and age against the board)'),
    ('2 LR table', '`pcbtools.rules.ROWS` on the board with `boards/v1r.py`; LR-10 from kicad-cli; rule text from `docs/afe.md`'),
    ('3 DRC', 'kicad-cli `pcb drc --severity-all` on a work copy of the board and its project file'),
    ('4 Bridges and hops', 'board arrays (pads, tracks, vias) via `gate3.bridge_table` / `hop_table`; justifications from TODO(kvm_01): the v1 bridge table'),
    ('5 Deviations', 'rule figures, board (power caps, outline), project file rules; cited spec text is quoted from the named file; the running record is `kicad/wip/gate3-notes.md`'),
    ('6 Cap and ripple rows', 'TODO(kvm_01): the v1 study result files'),
    ('7 BOM and cost', 'TODO(kvm_01): v1 prices and the cost model'),
)

# ---------------------------------------------------------------------------------------------------- section 2: the LR table (as v2)
LR_HEADING = '## 2. LR table (rules LR-1 to LR-11 on the integrated board)'
LR_INTRO = ('Verdicts are the checker\'s own (`python3 -B -m pcbtools.check BOARD --config {config} --drc`, called through the library so the figures are kept). '
            'The rule text is `docs/afe.md`\'s, shortened to its first sentence; the full text is there. '
            'The supply-pin decoupling distance is a sub-check of **LR-4** ("each supply pin has its 100 nF within a few millimetres", `docs/afe.md`), printed here as '
            '"LR-4 decoupling" with the config\'s limit; the checker\'s own name for that row is `LR-12 DECOUP_MAX` (`pcbtools/rules.py`; tests and goldens key on it), '
            'and `docs/afe.md` has no LR-12 row. The rule numbers in this table are `docs/afe.md`\'s.\n')
LR_DOC_ROWS = ('LR-1', 'LR-2', 'LR-3', 'LR-4', 'LR-5', 'LR-6', 'LR-7', 'LR-8', 'LR-9', 'LR-10', 'LR-11')
LR_RENAMES = (('LR-12 DECOUP_MAX', 'LR-4 decoupling (DECOUP_MAX {:.1f} mm)', 'DECOUP_MAX'),)
LR_SUBCHECKS = (('INV_MAX', '(LR-4 sub-check) the inverting-node trace is the shortest of the stage'),
                ('LR-4 decoupling', '(LR-4 sub-check) each supply pin has its 100 nF within a few millimetres'))
DRC_ROW = 'LR-10'

# ---------------------------------------------------------------------------------------------------- section 3: DRC
DRC_DOCUMENTED = (('courtyards_overlap', 'MH602'),)              # kicad/wip/README.md: the J607 / MH602 / J605 courtyard overlaps are the Due's own geometry
DRC_DOCUMENTED_LABEL = 'MH602 courtyards'
DRC_DOCUMENTED_NOTE = ('**The MH602 courtyard overlaps** (MH602 with the sockets J607 and J605) are the Due\'s own geometry: MH602 is the optional M2.5 standoff position beside the socket '
                       'rows. **The owner\'s caliper check of the socket clearance is pending**, and the screw is optional, so the overlap costs nothing if the screw is left out. '
                       '(The caliper status is the gate brief\'s statement, not a repo file *(check)*.)')
RULE_DIFF_TEXT = ("**The project file next to the board does not carry the design's rules.** `{n}` rule value(s) in the project file differ from `BOARD_SETUP` in the board config "
                  "(`pcbtools/boards/v1.py`). **Restore the file's rules before the gate.** LR-10 in section 2 is the checker's, at the file as it stands (run A). "
                  "Run B repeats DRC with the design's rules applied to a scratch copy of the project file.\n")

# ---------------------------------------------------------------------------------------------------- section 4: bridges and hops
BRIDGE_REF_PATTERN = 'TODO(kvm_01): regular expression of the bridge references on the v1 board (re.fullmatch); v2 uses one prefix + digits'
BRIDGES_SOURCE = ('TODO(kvm_01): module', 'TODO(kvm_01): attribute path of a list of (ref, net a, net b, block, justification) tuples, net names without the leading slash (boards/v1.py BRIDGES has only (ref, /net a, /net b))')
NET_CLASS_FIELDS = dict(adc=('CHANNELS.out_nets', 'ADC_NETS'), divider=('HIZ', 'DIVIDER_GROUPS'), vref_prefix='VREF_NET', other=('XSENS', 'HIZ'))
D24_ROW_PATTERN = r'\| D24 \|[^\n]*'
D24_QUOTE_PATTERN = r'The "1 to 3" first estimated was wrong[^|]*?which is where the count is reviewed'
D24_FOUND = ('`docs/afe.md` (row D24) says, quoted from the file: "{quote}". The sentence arrived on main with commit 446bb68, which the document does not name; '
             'it is cited here as the file\'s text. ')
D24_MISSING = ('The spec lead\'s message records that D24 was updated on main in commit 446bb68: the "1 to 3 in all" was an estimate, and the count is now reviewed in this table. '
               '(`docs/afe.md` in this tree does not carry that wording, so it is cited as quoted from the spec lead\'s message, not as a repo file.) *(check)* ')
BRIDGE_ACCEPT = ('TODO(kvm_01): the acceptance wording under v1\'s standing rules (a) and (b), in `kicad/wip/gate3-notes.md`. Placeholders: {nb} {nover} {over} {parts} {div}. '
                 'v2 reads: " **All {nb} bridges are accepted, including the {nover} over ADC or VREF lines** ({over}): ... {parts}; {div}. ..."')

# ---------------------------------------------------------------------------------------------------- section 5: deviations
POWER_CAPS = dict(ic='U401', caps=('TODO(kvm_01): the v1 generator capacitors, e.g. C401 to C410',), far_mm=5.0)
POWER_CAPS_CAPTION = 'TODO(kvm_01): caption of the capacitor-distance table (v2 names the flying capacitor)'
CFG_QUOTED = ('HOP_MAX', 'HOP_MAX_VIAS')                         # config fields quoted; boards/v1.py has no designator waivers, so those rows are off (None below)
CFG_FOREIGN_WAIVED = 'DESIGNATOR_FOREIGN_WAIVED'
CFG_GAP_WAIVED = 'DESIGNATOR_GAP_WAIVED'
CFG_GAP_MIN = 'DESIGNATOR_GAP_MIN'
CFG_GAP_ONE_LABEL = 'DESIGNATOR_GAP_ONE_LABEL'
DEV_COURT = ('DRC / courtyards', '{items}: courtyards overlap', 'documented; owner caliper check pending, screw optional (section 3)')
DEV_POWER = ('LR-5 (generator caps at their pins)',
             'capacitors more than {far_mm:n3} mm from their {ic} pad: {far}; the nearer ones: {near} mm (all measured here, pad centre to pad centre; full list below)',
             'TODO(kvm_01): authority for the far capacitors (gate-3-notes.md row 5 says "to be judged")')
DEV_FOREIGN = None                                               # no designator waivers in boards/v1.py: no row
DEV_FOREIGN_EMPTY = ''
DEV_GAP = None
DEV_OUTLINE = ('MC-1 board outline',
               'the board overhangs the Due by {overhang} mm on the analog-header edge: {w:.2f} x {h:.2f} mm against the {max0} x {max1} mm bound; the band is a copper keep-out ({band})',
               None)
MC1_COMMIT = 'caba9c8'
MC1_PATTERN = r'Amended by the owner, 2026-11-13[^|]*overhangs the Due by 5 mm'
MC1_FOUND = ('owner ruling 2026-11-13, in `docs/afe.md` row MC-1 ("Amended by the owner, 2026-11-13 ... the outline overhangs the Due by 5 mm", '
             'read from the file at run time; amendment commit caba9c8, not named in the document)')
MC1_MISSING = 'owner ruling 2026-11-13, MC-1 amended on main (`caba9c8`); `docs/afe.md` in this tree does not carry the wording *(check)*'
DEV_EDGE = ('copper-to-edge', 'min_copper_edge_clearance {edge_rule} mm in the project file (config says {edge_cfg} mm)',
            'fabricator minimum 0.2 mm *(check)*, outline tolerance 0.2 mm, so 0.45 leaves 0.25 mm worst case (spec team ruling, gate-3-notes.md row 9)')
DEV_PROOF = ('TODO(kvm_01): rule / item name of the connectivity row', 'TODO(kvm_01): text with {tracks} {length:.1f} {vias} {zones} {pads} {result}', 'TODO(kvm_01): authority')
DEV_PROOF_JOINED = 'TODO(kvm_01): the sentence when every proved pin is joined'
DEV_PROOF_NOT = 'TODO(kvm_01): the sentence when one is not'
MARGINS = (
    dict(rule='LR-5', what='sensitive copper to the generator (mm)', row='LR-5', key='min_distance_mm', limit='KEEPOUT', kind='min'),
    dict(rule='LR-1', what='longest bottom hop (mm)', row='LR-1', key='max_run_mm', limit='HOP_MAX', kind='max'),
    dict(rule='LR-1', what='vias on the longest hop', row='LR-1', key='max_run_vias', limit='HOP_MAX_VIAS', kind='max'),
    dict(rule='LR-4 INV_MAX', what='AWG_FB inverting node (mm)', row='LR-4 INV_MAX', key='AWG_FB', limit='INV_MAX', kind='max'),
    dict(rule='LR-4 INV_MAX', what='CH1_OUT (mm)', row='LR-4 INV_MAX', key='CH1_OUT', limit='INV_MAX', kind='max'),
    dict(rule='LR-4 INV_MAX', what='CH2_OUT (mm)', row='LR-4 INV_MAX', key='CH2_OUT', limit='INV_MAX', kind='max'),
    dict(rule='LR-4', what='AWG_FB node track length (mm; FB_MAX)', row='LR-4', key='fb_mm', limit='FB_MAX', kind='max'),
    dict(rule='LR-4 decoupling', each_of='LR-12 DECOUP_MAX', limit='DECOUP_MAX', kind='max'),
)

# ---------------------------------------------------------------------------------------------------- section 5.1: the connectivity proof
# The v2 table proves the filtered 5 V feed of the LM27762: which pins join which source pad by copper alone, with one-track cuts checked against DRC.
PROOF = dict(net='TODO(kvm_01): the net to prove (the +5V_F analogue)', source='TODO(kvm_01): the source pad, REF.PIN',
             pins=('TODO(kvm_01): REF.PIN to prove joined', 'TODO(kvm_01): REF.PIN'), upstream=('TODO(kvm_01): upstream net', 'TODO(kvm_01): REF.PIN', 'TODO(kvm_01): REF.PIN'),
             on_net_head='TODO(kvm_01): column head', arms=(('TODO(kvm_01): arm label', 'TODO(kvm_01): REF.PIN', 'first'),))
PROOF_PATH_ORDER = ('TODO(kvm_01): REF.PIN in the order the paths are listed',)
PROOF_HEADING = 'TODO(kvm_01): heading with {status}'
PROOF_INTRO = 'TODO(kvm_01): intro, placeholder {net}'
PROOF_COPPER = 'TODO(kvm_01): placeholders {tracks} {length:.1f} {vias} {npads} {pads} {arcs} {zones_on_net} {nzones}'
PROOF_RESULT = 'TODO(kvm_01): placeholders {ncomp} {net} {pieces} {same} {src} {j_a} {j_b}'
PROOF_PATH_HEAD = 'TODO(kvm_01): placeholders {ref} {pin} {src}'
PROOF_HISTORY = 'TODO(kvm_01): history paragraph, or an empty string'
PROOF_UPSTREAM = 'TODO(kvm_01): placeholders {n} {tracks} {vias} {fills} {chain}'
PROOF_UPSTREAM_NONE = 'TODO(kvm_01): the sentence when the upstream pads are not joined'
PROOF_DRC = 'TODO(kvm_01): placeholder {n}'
PROOF_RULE = 'TODO(kvm_01): which LR row sees this net, and which does not'

# ---------------------------------------------------------------------------------------------------- section 6: evidence rows
EVIDENCE_HEADING = '## 6. Capacitance, LR-3 evidence and ripple rows'
EVIDENCE_DATA = (dict(name='TODO(kvm_01): name used in templates', json='TODO(kvm_01): study result file, relative to the repository root'),)
EVIDENCE_DERIVED = ()
EVIDENCE = (dict(kind='text', text='TODO(kvm_01): the v1 evidence rows: blocks of kind text / table / cap_table / matrix (README.md)'),)

# ---------------------------------------------------------------------------------------------------- section 7: BOM and cost
BOM_ENGINE = AFE + 'v2/bom/bom.py'
BOM_DATA_DIR = 'TODO(kvm_01): the folder of the v1 BOM data (catalog.csv, intl.csv, extra.csv, blocks.csv, ...) the engine reads; v1 has none yet'
BOM_EXTRA_CSV = 'TODO(kvm_01): extra.csv path as the text names it'
BOARD_COUNTS = (5, 10, 20, 100)
REPORT_BOARDS = 20
TARGET_BOARDS = (20, 100)
OWNER_FITTED_LCSC = ('C2837587',)                                # the BNC, as v2
BRIDGE_PART = dict(lcsc='C21189', footprint_prefix='Resistor_SMD:R_0603')      # gate-3-notes.md: the existing 0603 0R bridge type (0Rb)
WATCH_PACKAGES = ('2512', '2010')
BOM_INTRO = 'TODO(kvm_01): BOM sources paragraph, placeholder {fx}'
BOM_UNIT_NOTE = ('Unit prices are the quantity tier holding (boards, capped at one 50-board order, x parts per board) pieces, as the engine does; the BNC is owner-fitted and tiered on all boards. ')
BOM_RECONCILE_NOTE = 'TODO(kvm_01): what the engine lists omit on the v1 board (bridges, R520, mounting holes)'
BRIDGE_PART_TEXT = 'TODO(kvm_01): placeholders {n} {c} {mfr} {cls} {read_utc} {ratio} {u:n4} {stock} {unpriced} {dnp}'
BOM_PCB_NOTE = 'The PCB row is the published rule (engineering fee + CNY/m2 x area), **not a quote**; the header price is a retail listing with its tail length unchecked *(check)*; the calibration jumper pins are unpriced and in no total (all per `bom.md`).'
COST_TARGET = 'TODO(kvm_01): the cost-target sentence'
COST_TARGET_RESULT = (' Version 1 as above is ${a_lo:.2f} / ${a_hi:.2f} at {a} boards and ${b_lo:.2f} / ${b_hi:.2f} at {b} '
                      '(board-adjusted, bridges included).')
GAPS = ('TODO(kvm_01): what this package could not source',)
