"""The differences between the new rules and the OLD tools' recorded output (tests/golden/v2-8a1f7ac, which stays as it is) that
are IMPROVEMENTS, as data. test_rules_equivalence treats exactly these - and only these - as explained: a (board, row) whose
verdict or text differs from the golden and is not listed here fails, and so does a listed one that no longer differs.

Each entry: (board, row) -> dict(old, new, finding, contains, why). `finding` is the number in the review of the port; `contains`
a phrase the new detail must hold, so the entry cannot be satisfied by any other change of the same row.

The finding numbers:
  1  LR-6 / LR-8 resolve the bridge-joined nets (BR parts) into one electrical net before grouping: the SCOPE group had no pad on
     /+3V3A at all (its parts sit on /+3V3A_U, _S, _K behind BR101, BR102, BR509), so the old LR-6 could not see it
  2  an unrouted net passed LR-6 and LR-8: every group / branch must now reach its star / source pad through copper
  3  connectivity covers B.Cu and zone fills as well as F.Cu (not visible on these boards' verdicts: the integrated board's bottom
     hop turns 8 pieces into 7, in a figure; and the family joins add refs to the 'share copper' text)
  6  an arm on a rule that already fails on the clean board is 'NOT TESTABLE', not 'caught'
  9  LR-4's pour keep-back is the exact copper-edge to pour-edge distance, not four axial probes from a pad centre (and it judges
     /AWG_FB only: the divider nodes /CHn_N want pour near them under LR-3, and /CHn_OUT is covered by the capacitance budget;
     so the verdicts on the six boards are the old tool's, and nothing is listed for it above)
"""

KNOWN = {
    # LR-6: these boards place the consumers' parts and route no supply copper to them
    ('v2-awg-bc96e334', 'LR-6'): dict(old='PASS', new='FAIL', finding=2, contains='consumer group awg is not connected to the star',
                                       why='AWG, ADC and VNEG_G consumers are placed and unrouted'),
    ('v2-power-a5605a04', 'LR-6'): dict(old='PASS', new='FAIL', finding=2, contains='consumer group scope is not connected to the star',
                                         why='the power block is routed; no consumer is'),
    ('v2-power3-7c838703', 'LR-6'): dict(old='PASS', new='FAIL', finding=2, contains='consumer group scope is not connected to the star',
                                          why='the power block is routed; no consumer is'),
    ('v2-refcal-326f141b', 'LR-6'): dict(old='PASS', new='FAIL', finding=2, contains='consumer group scope is not connected to the star',
                                          why='scope, AWG and ADC supply copper is unrouted'),
    ('v2-scope2east-05ee441f', 'LR-6'): dict(old='PASS', new='FAIL', finding=2, contains='consumer group awg is not connected to the star',
                                              why='the scope is routed; the AWG and ADC consumers are not'),
    # LR-8
    ('v2-refcal-326f141b', 'LR-8'): dict(old='PASS', new='FAIL', finding=2, contains='branch 0 (J602.1) is not connected to the source',
                                          why='J602.1, R305.1 and the CH1 branch are not routed to the reference'),
    ('v2-awg-bc96e334', 'LR-8'): dict(old='FAIL', new='FAIL', finding=1, contains='BR504',
                                       why='still failing; the bridged VREF_M / VREF_P copper is now part of the piece, and R305.1 is unrouted'),
    **{(b, 'LR-8'): dict(old='FAIL', new='FAIL', finding=1, contains='BR504',
                         why='still failing; the bridged VREF_M / VREF_P copper is now part of the piece')
       for b in ('v2-power-a5605a04', 'v2-power3-7c838703', 'v2-scope2east-05ee441f')},
}

# --mutate lines of the integrated board whose text changes: the old tool printed '[FAILED AS REQUIRED] ... (clean board: fail)'
# for an arm on a rule that fails before the arm (finding 6)
ARM_NOT_TESTABLE = {
    'LR-11 part out of its outline': 6, 'LR-11 missing designator': 6, 'LR-11 missing test point': 6,
    'LR-11 wrong-numbered designator': 6, 'LR-11 block without a TP': 6,
}

# --mutate lines that are still 'FAILED AS REQUIRED' but whose text changed: two crossing bottom segments of one net are ONE run now
# (finding 5, so the 'under [...]' lists merge), and LR-5's figure is the copper EDGE's distance (finding 10: the arm's 0.2 mm track
# is 0.1 mm nearer than its centre line)
ARM_TEXT = {'LR-1 SCL under AREF': 5, 'LR-1 +3V3A under AREF': 5, 'LR-5': 10}
