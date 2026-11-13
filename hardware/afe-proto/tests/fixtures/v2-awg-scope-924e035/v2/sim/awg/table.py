#!/usr/bin/env python3
"""Writes report_table.md from raw/results.json (python3 -I table.py)."""
import json, os
h = os.path.dirname(os.path.abspath(__file__))
r = json.load(open(os.path.join(h, 'raw/results.json')))
L = ['| | ID | case | limit | result | margin | note |', '|---|---|---|---|---|---|---|']
esc = lambda s: str(s).replace('|', '&#124;')
for x in r['rows']:
    st = 'info' if x.get('info') else ('PASS' if x['ok'] else '**FAIL**')
    L.append(f"| {st} | {x['id']} | {esc(x['case'])} | {esc(x['limit'])} | {esc(x['result'])} | {esc(x['margin'])} | {esc(x['note'])} |")
L += ['', 'Guards (check broken on purpose: must fail broken, pass restored):', '', '| guard | what | broken | restored |', '|---|---|---|---|']
for g in r['guards']:
    L.append(f"| {g['name']} | {esc(g['what'])} | {'pass (BAD)' if g['broken_ok'] else 'fails'} | {'passes' if g['good_ok'] else 'fails (BAD)'} |")
open(os.path.join(h, 'report_table.md'), 'w').write('\n'.join(L) + '\n')
print(len(r['rows']), 'rows')
