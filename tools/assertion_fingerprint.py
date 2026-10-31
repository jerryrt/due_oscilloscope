#!/usr/bin/env python3
"""Fingerprint what each test asserts, so a change that is only about time
can be shown not to have touched a check.

A fingerprint is a hash of the assertion text of a test: its `assert`
statements, the calls to `assert_*` helpers (which carry the thresholds as
arguments), and the `pytest.raises` it expects. A level from host/pacing.py
is replaced by its value first, so converting `window(seconds, 2.0)` to
`window(seconds, pacing.SHORT)` hashes the same, and changing what SHORT
means does not. Top-level numeric constants of a file are fingerprinted
too, because a test asserts against them by name.

    python3 tools/assertion_fingerprint.py                 # write to stdout
    python3 tools/assertion_fingerprint.py --check FILE    # compare, exit 1
    python3 tools/assertion_fingerprint.py --root DIR      # another checkout

It is deliberately blind to run lengths, which the levels name and a review
reads: the owner's rule is that a fingerprint covers the assertions only.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "host"))
import pacing  # noqa: E402

VALUES = {}
for _table in (pacing.DELAYS, pacing.READS, pacing.LIMITS, pacing.RUNS):
    VALUES.update(_table)
VALUES["FEED_PACE_CAP"] = pacing.FEED_PACE_CAP
VALUES["SILENCE"] = pacing.SILENCE


class _Resolve(ast.NodeTransformer):
    """pacing.NAME and a module-level numeric name -> the number, so the hash
    is of the value and a constant moved into a name hashes the same."""

    def __init__(self, names=None):
        self.names = names or {}

    def visit_Constant(self, node):
        # 6 and 6.0 are the same number; a level is always a float
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return ast.copy_location(ast.Constant(float(node.value)), node)
        return node

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.names:
            return ast.copy_location(ast.Constant(float(self.names[node.id])), node)
        return node

    def visit_Attribute(self, node):
        if (isinstance(node.value, ast.Name) and node.value.id == "pacing"
                and node.attr in VALUES):
            return ast.copy_location(ast.Constant(float(VALUES[node.attr])), node)
        return self.generic_visit(node)


def _dump(node, names=None):
    return ast.dump(_Resolve(names).visit(ast.parse(ast.unparse(node), mode="eval"
                                                    if isinstance(node, ast.expr) else "exec")))


def _is_assertion_call(call):
    f = call.func
    name = getattr(f, "attr", getattr(f, "id", ""))
    return name.startswith("assert_") or name == "raises"


def _assertions(fn, names=None):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assert):
            out.append(_dump(n, names))
        elif isinstance(n, ast.Call) and _is_assertion_call(n):
            out.append(_dump(n, names))
    return out


def _hash(parts):
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def fingerprint(root):
    root = pathlib.Path(root)
    result = {}
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.name
        names = {}
        for n in tree.body:
            if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)):
                continue
            v = n.value
            if (isinstance(v, ast.Constant) and isinstance(v.value, (int, float))
                    and not isinstance(v.value, bool)):
                names[n.targets[0].id] = v.value
            elif (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
                    and v.value.id == "pacing" and v.attr in VALUES):
                names[n.targets[0].id] = VALUES[v.attr]
        consts = []
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Constant, ast.List,
                                                                  ast.Tuple, ast.Dict)):
                consts.append(_dump(n))
        result[f"{rel}::<module constants>"] = _hash(consts)

        def walk(body, prefix):
            for n in body:
                if isinstance(n, ast.ClassDef):
                    walk(n.body, prefix + n.name + "::")
                elif isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
                    result[f"{rel}::{prefix}{n.name}"] = _hash(_assertions(n, names))
        walk(tree.body, "")
    return result


def compare(old, new):
    changed = sorted(k for k in old if k in new and old[k] != new[k])
    removed = sorted(k for k in old if k not in new)
    added = sorted(k for k in new if k not in old)
    return changed, removed, added


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--check", metavar="FILE")
    a = ap.parse_args(argv)
    now = fingerprint(a.root)
    if not a.check:
        json.dump(now, sys.stdout, indent=1, sort_keys=True)
        print()
        return 0
    old = json.load(open(a.check, encoding="utf-8"))
    changed, removed, added = compare(old, now)
    for label, items in (("changed", changed), ("removed", removed), ("added", added)):
        for k in items:
            print(f"{label}: {k}")
    print(f"{len(now)} fingerprints; {len(changed)} changed, {len(removed)} removed, {len(added)} added")
    return 1 if changed or removed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
