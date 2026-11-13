"""Compare two result trees (the JSON a study writes) number by number, with a stated tolerance.

    diffs = compare_trees(golden_dir, new_dir, rtol=1e-6, atol=1e-12)

A study is kept on the shared tools only where its numbers reproduce to this tolerance. The comparison
reports every difference with its path; a missing file, a missing key, a different length or a different
non-numeric value is a difference, and a tree with no JSON file in it is an error, never a pass.
"""
import json
import math
from pathlib import Path


def compare_values(a, b, path="", rtol=1e-6, atol=1e-12, out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append((f"{path}/{k}", "key present in only one tree", None))
            else:
                compare_values(a[k], b[k], f"{path}/{k}", rtol, atol, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"length {len(a)} vs {len(b)}", None))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                compare_values(x, y, f"{path}[{i}]", rtol, atol, out)
    elif isinstance(a, bool) or isinstance(b, bool) or not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        if type(a) is not type(b) or a != b:                # True == 1 in Python; here it is a difference
            out.append((path, a, b))
    elif isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        pass                                                # a NaN written by a study is the same NaN
    elif not math.isclose(a, b, rel_tol=rtol, abs_tol=atol):
        out.append((path, a, b))
    return out


def compare_trees(golden, new, rtol=1e-6, atol=1e-12, pattern="*.json"):
    golden, new = Path(golden), Path(new)
    files = sorted(p.relative_to(golden) for p in golden.rglob(pattern))
    if not files:
        raise ValueError(f"{golden}: no {pattern} files to compare against")
    diffs = []
    for rel in files:
        other = new / rel
        if not other.exists():
            diffs.append((str(rel), "missing in the new tree", None))
            continue
        for path, x, y in compare_values(json.loads((golden / rel).read_text()), json.loads(other.read_text()), "", rtol, atol):
            diffs.append((f"{rel}:{path}", x, y))
    return diffs
