#!/usr/bin/env python3
"""Assign prepared STEP bodies without rewriting any electrical CAD text."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PREFIX = '${KIPRJMOD}/../models/'


def prepared_assignments():
    records = []
    assignments = {}
    for name in ('alignment.json', 'population.json'):
        evidence_path = ROOT.parent / 'models' / name
        if not evidence_path.exists():
            continue
        records.append('../models/' + name)
        for item in json.loads(evidence_path.read_text())['assignments']:
            assert item['reference'] not in assignments, item['reference']
            assignments[item['reference']] = item
    assert assignments
    return assignments, records


def children(text):
    """Yield immediate child S-expressions, respecting escaped quoted strings."""
    depth = 0
    quoted = False
    escaped = False
    start = None
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == '(':
            if depth == 1:
                start = index
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 1 and start is not None:
                yield start, index + 1, text[start:index + 1]
                start = None
    assert depth == 0 and not quoted


def without_owned_models(text):
    """Remove only the model clauses this script owns, including indentation."""
    removals = []
    for start, end, block in children(text):
        if not block.startswith('(footprint '):
            continue
        for left, right, child in children(block):
            if child.startswith('(model "' + PREFIX):
                # The generated clause starts on its own line.
                begin = block.rfind('\n', 0, left)
                assert block[begin + 1:left].isspace()
                removals.append((start + begin, start + right))
    for start, end in reversed(removals):
        text = text[:start] + text[end:]
    return text


def attach_models():
    path = ROOT / 'Arduino-DUE-V03.kicad_pcb'
    assignments, records = prepared_assignments()
    original = path.read_text()
    base = without_owned_models(original)
    inserts = []
    seen = set()
    for start, end, block in children(base):
        if not block.startswith('(footprint '):
            continue
        match = re.search(r'\(property "Reference" "([^"]+)"', block)
        assert match
        ref = match[1]
        if ref not in assignments:
            continue
        assert not any(child.startswith('(model ') for _, _, child in children(block)), (
            ref, 'Existing model assignment is not owned by this script')
        item = assignments[ref]
        asset = ROOT.parent / 'models' / item['file']
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == item['sha256']
        filename = PREFIX + item['file']
        clause = (f'\n\t\t(model "{filename}"\n'
                  '\t\t\t(offset (xyz 0 0 0))\n'
                  '\t\t\t(scale (xyz 1 1 1))\n'
                  '\t\t\t(rotate (xyz 0 0 0))\n\t\t)')
        # Insert before the footprint's final newline/closing parenthesis.
        closing = start + block.rfind('\n')
        inserts.append((closing, clause))
        seen.add(ref)
    assert seen == set(assignments), (seen, set(assignments))
    updated = base
    for position, clause in reversed(inserts):
        updated = updated[:position] + clause + updated[position:]
    assert without_owned_models(updated) == base
    path.write_text(updated)
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
    evidence = dict(
        assignments=sorted(assignments), model_path_prefix=PREFIX,
        alignment_records=records,
        original_non_model_text_sha256=digest(base),
        updated_non_model_text_sha256=digest(without_owned_models(updated)),
        electrical_cad_text='byte-for-byte unchanged after removing owned model clauses',
        board_sha256=digest(updated),
        qualification=f'{len(seen)} individually assigned visualization bodies. Generic package models and simplified special parts are documented in population.json; not a fabrication-qualified assembly.',
    )
    (ROOT / 'models-3d.json').write_text(json.dumps(evidence,indent=2)+'\n')
    sources_path = ROOT / 'sources.json'
    if sources_path.exists():
        sources = json.loads(sources_path.read_text())
        sources['files'][path.name] = dict(sha256=digest(updated), bytes=path.stat().st_size)
        sources['component_models'] = 'models-3d.json'
        sources_path.write_text(json.dumps(sources,indent=2)+'\n')
    print(f'Attached {len(seen)} models; all non-model PCB text unchanged.')


if __name__ == '__main__':
    attach_models()
