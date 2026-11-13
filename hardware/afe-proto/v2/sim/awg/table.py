#!/usr/bin/env python3
"""Writes report_table.md from raw/results.json (python3 -I table.py [DIR]; DIR defaults to this folder)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ESC = lambda s: str(s).replace('|', '&#124;')


def render(r):
    L = ['| | ID | case | limit | result | margin | note |', '|---|---|---|---|---|---|---|']
    for x in r['rows']:
        st = 'info' if x.get('info') else ('PASS' if x['ok'] else '**FAIL**')
        L.append(f"| {st} | {x['id']} | {ESC(x['case'])} | {ESC(x['limit'])} | {ESC(x['result'])} | {ESC(x['margin'])} | {ESC(x['note'])} |")
    L += ['', 'Guards (check broken on purpose: must fail broken, pass restored):', '', '| guard | what | broken | restored |', '|---|---|---|---|']
    for g in r['guards']:
        L.append(f"| {g['name']} | {ESC(g['what'])} | {'pass (BAD)' if g['broken_ok'] else 'fails'} | {'passes' if g['good_ok'] else 'fails (BAD)'} |")
    return '\n'.join(L) + '\n'


def write(out_dir=HERE):
    with open(os.path.join(out_dir, 'raw', 'results.json')) as f:
        r = json.load(f)
    with open(os.path.join(out_dir, 'report_table.md'), 'w') as f:
        f.write(render(r))
    print(len(r['rows']), 'rows')


if __name__ == '__main__':
    write(os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else HERE)
