"""How a pcbkit rule reads its configuration, and reports what it read.

A configuration is a mapping or an object with upper-case names. A rule declares its names in a table of `Name`s: each is a
PROJECT name (a net, a part, a table, a rectangle, a frame, a prefix: the project must supply it, and a missing one raises
`ConfigError` naming the key) or a TUNABLE (a margin, a limit, a step: it has a documented default, which is used, and recorded
as the default, when the project does not set it). `resolve` returns the effective values and, when asked, appends one
`(name, value, source)` row per name to a report, `source` being "project" or "default". Nothing is read from anywhere else.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace


class ConfigError(ValueError):
    """a configuration problem in any pcbkit module: a project name the rule needs is missing, or a name is a likely typo of a declared one"""


_REQUIRED = object()


@dataclasses.dataclass(frozen=True)
class Name:
    key: str
    kind: str               # 'project' | 'tunable'
    unit: str               # 'mm', 'count', 'net name', ... (documentation, and the report)
    default: object = _REQUIRED
    note: str = ''

    def __post_init__(self):
        if self.kind not in ('project', 'tunable'):
            raise ValueError(self.kind)
        if (self.kind == 'tunable') == (self.default is _REQUIRED):
            raise ValueError(f'{self.key}: a tunable has a default and a project name has none')


def project(key, unit, note=''):
    return Name(key, 'project', unit, _REQUIRED, note)


def tunable(key, default, unit, note=''):
    return Name(key, 'tunable', unit, default, note)


# ------------------------------------------------------------------------------------------- the registry and the typo guard
DECLARED = {}               # every name any pcbkit module declares -> the set of rules (modules) that read it


def declare(rule, names):
    """register the names a rule reads (its Name table, or plain strings); a module calls this once at import"""
    for n in names:
        DECLARED.setdefault(n.key if isinstance(n, Name) else str(n), set()).add(rule)


def distance(a, b):
    """Levenshtein edit distance"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near(a, b):
    """a likely typo: within edit distance 2 when the shorter name has at least 6 characters, within 1 when it has 4 or 5, never for
    shorter names (a 3-letter name is within 2 of half the alphabet)"""
    m = min(len(a), len(b))
    return a != b and ((m >= 6 and distance(a, b) <= 2) or (4 <= m < 6 and distance(a, b) <= 1))


def declared_pairs_near():
    """declared names that are near each other (a legitimate name that is near another one is never reported as a typo: a declared name never raises)"""
    names = sorted(DECLARED)
    return [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if near(a, b)]


def config_names(cfg):
    """the upper-case names a configuration (mapping, module or object) carries"""
    keys = cfg.keys() if isinstance(cfg, dict) else dir(cfg)
    return sorted(k for k in keys if isinstance(k, str) and k.isupper())


def check_names(cfg):
    """(unrecognised names) of `cfg`: names no pcbkit module declares, listed for information only (a project's configuration carries many
    names of its own). A name that is not declared but is near a declared one raises ConfigError naming both: a likely typo (HOP_MAXX)."""
    unknown = []
    for k in config_names(cfg):
        if k in DECLARED:
            continue
        hit = sorted(d for d in DECLARED if near(k, d))
        if hit:
            raise ConfigError(f'{k} is not a configuration name but is near {", ".join(hit)}: a typo? (a name no module declares is '
                              'otherwise listed as unrecognised and ignored)')
        unknown.append(k)
    return unknown


# THE ONE numeric tolerance of the package, declared here once and read by every rule that compares a distance with a threshold (a distance passes when it is within EPS of
# the threshold). It is coordinate and text-box resolution (KiCad's nm grid, pcbnew's stroke boxes), not a loosened margin; a rule that needs it lists EPS_NAME in its names
# table. pcbkit.labels reads this same value.
EPS_DEFAULT = 0.005
EPS_NAME = tunable('EPS', EPS_DEFAULT, 'mm', 'coordinate and text-box resolution (KiCad nm grid, pcbnew stroke boxes): a distance passes a threshold when it is within EPS of it')


def _get(cfg, key):
    if isinstance(cfg, dict):
        return cfg[key] if key in cfg else _REQUIRED
    return getattr(cfg, key, _REQUIRED)


def resolve(cfg, names, rule='', report=None):
    """the effective values of `names` (a sequence of Name) in `cfg`, as a namespace; `report`, a list, receives (key, value, source)
    rows. A project name missing from `cfg` raises ConfigError naming the rule and the key."""
    out = {}
    check_names(cfg)
    for n in names:
        v = _get(cfg, n.key)
        if v is _REQUIRED:
            if n.kind == 'project':
                raise ConfigError(f'{rule or "rule"}: the configuration has no {n.key} ({n.unit}); a project name has no default')
            v, src = n.default, 'default'
        else:
            src = 'project'
        out[n.key] = v
        if report is not None:
            report.append((n.key, v, src))
    return SimpleNamespace(**out)


def format_report(rows, rule=''):
    """the effective-configuration report as text, one name per line: name, where it came from, value (the layout of
    pcbkit.labels.effective_config)"""
    head = [f'effective configuration of {rule}'] if rule else []
    return '\n'.join(head + ['%-28s %-9s %r' % (k, src, v) for k, v, src in rows])
