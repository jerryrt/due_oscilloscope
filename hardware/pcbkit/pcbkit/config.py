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
    """a project name the rule needs is missing from the configuration"""


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


def _get(cfg, key):
    if isinstance(cfg, dict):
        return cfg[key] if key in cfg else _REQUIRED
    return getattr(cfg, key, _REQUIRED)


def resolve(cfg, names, rule='', report=None):
    """the effective values of `names` (a sequence of Name) in `cfg`, as a namespace; `report`, a list, receives (key, value, source)
    rows. A project name missing from `cfg` raises ConfigError naming the rule and the key."""
    out = {}
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
