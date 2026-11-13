"""Mutation arms for a ROUTED v1 board (`python -m pcbtools.check BOARD --config v1r --mutate`): the config is v1's (boards/v1r.py re-exports it).

The arms in v1_arms start from the unrouted baseline: their rows fail there and the preps bring each facet to a clean state. On a board
where LR-6 and LR-8 already pass, those arms are NOT TESTABLE (nothing to prepare, nothing to repair). These break a passing rule
instead, as v2's arms do, so they are caught on a routed board and cannot run on the unrouted one (the nets they name, P33_G, do not
exist there). tests/pcbtools/test_v1_rules.py runs them on the routed WIP board and breaks them on purpose.
"""
from .. import mutate as M
from .. import rules as R


def mut6_routed_share(b, cfg):
    """the AWG's +3V3A branch (P33_G, behind R411) tied by a top track to the REF3030's VIN pad on the star side"""
    return M.add_segment(b, '/P33_G', 'F', M.pad_center(b, 'U301', '8'), M.pad_center(b, 'U501', '1'))


def mut6_routed_unrouted(b, cfg):
    """the AWG branch unrouted: every track end at U301.8 deleted"""
    return M.drop_segments(b, M.segments_at_pad(b, '/P33_G', 'U301', '8'))


def mut8_routed_share(b, cfg):
    return M.add_segment(b, '/VREF', 'F', M.pad_center(b, 'R508', '2'), M.pad_center(b, 'U502', '4'))


def mut8_routed_unrouted(b, cfg):
    """the AWG offset leg unrouted: every VREF track end at R307.1 deleted"""
    return M.drop_segments(b, M.segments_at_pad(b, '/VREF', 'R307', '1'))


ARMS = [
    ('LR-6 AWG branch tied to the REF3030 VIN', R.lr6, mut6_routed_share),
    ('LR-6 AWG branch unrouted', R.lr6, mut6_routed_unrouted),
    ('LR-8 ladder tied to the ADS reference leg', R.lr8, mut8_routed_share),
    ('LR-8 AWG offset leg unrouted', R.lr8, mut8_routed_unrouted),
]
