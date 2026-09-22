#!/usr/bin/env python3
"""Export and exercise the actual schematic; no third-party Python packages."""
import argparse
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

def executable(name, mac_fallback=None):
    path = os.environ.get(name.upper().replace('-', '_')) or shutil.which(name)
    if not path and mac_fallback and Path(mac_fallback).is_file():
        path = mac_fallback
    if not path:
        raise RuntimeError(f'{name} is required; install it or add it to PATH')
    return path

def kicad_cli():
    path = executable('kicad-cli', '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
    version = subprocess.check_output([path, '--version'], text=True).strip()
    if not re.match(r'^10\.', version):
        raise RuntimeError(f'KiCad 10.x is the project standard; found {version!r} at {path}. '
                           'Install KiCad 10 and set KICAD_CLI to its kicad-cli executable.')
    print(f'Using KiCad {version}: {path}', flush=True)
    return path

def rows(name):
    result = [list(map(float, line.split())) for line in
              (HERE / name).read_text().splitlines()[1:] if line.strip()]
    if not result or not all(math.isfinite(x) for r in result for x in r):
        raise RuntimeError(f'Missing or non-finite simulation data: {name}')
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', action='store_true',
                        help='exit 2 when an existing performance review check fails; '
                             'exit 0 still does not qualify hardware')
    args = parser.parse_args()
    findings = []
    cli = kicad_cli()
    spice = executable('ngspice')
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'spice',
                    '-o', str(HERE / 'stage_a.net.raw'),
                    str(PROJECT / 'afe-shield.kicad_sch')], check=True)
    exported = (HERE / 'stage_a.net.raw').read_text()
    # CLI leaves schematic-text includes relative; the GUI's full-path option resolves them.
    exported = exported.replace('.include "sim/sources.cir"',
                                f'.include "{HERE / "sources.cir"}"')
    if 'MCP6024_VENDOR' not in exported or 'XD1 ' not in exported:
        raise RuntimeError('Export is incomplete or does not use the vendor models')
    (HERE / 'stage_a.net').write_text('\n'.join(
        line for line in exported.splitlines()
        if not line.lower().startswith('.title') and line.strip().lower() != '.end') + '\n')
    data_files = ['op.dat', 'dc.dat', 'ac.dat', 'tran.dat', 'aref_load.dat']
    for name in data_files:
        (HERE / name).unlink(missing_ok=True)
    proc = subprocess.run([spice, '-n', '-D', 'ngbehavior=ps', '-b', 'stage_a.cir'],
                          cwd=HERE, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (HERE / 'stage_a.log').write_text(proc.stdout)
    if proc.returncode or any(token in proc.stdout.lower() for token in
                              ['error:', 'fatal error', 'timestep too small', 'no such vector']):
        print(proc.stdout)
        raise RuntimeError('ngspice failed; see sim/stage_a.log')
    op, dc, ac, tran, load = [rows(name) for name in data_files]
    print('Nominal vendor-model results (not a hardware qualification):')
    print(f'VREF3V0={op[0][1]:.6f} V; VREF1V5={op[0][2]:.6f} V')
    print(f'DAC0 follower maximum DC error: {max(abs(r[3]) for r in dc)*1e3:.3f} mV')
    at5 = min(ac, key=lambda r: abs(r[0]-5e6))
    corner = next((r[0] for r in ac if r[1] <= -3), math.nan)
    print(f'Gain at {at5[0]/1e6:.3f} MHz: {at5[1]:.3f} dB; first -3 dB crossing: {corner/1e6:.3f} MHz')
    print(f'Follower before the 68 ohm resistor at that frequency: {at5[2]:.3f} dB')
    for edge, stop, label in [(20e-6, 29e-6, 'rising'), (30.001e-6, 39e-6, 'falling')]:
        window = [r for r in tran if edge <= r[0] <= stop]
        final = sum(r[2] for r in window[-100:])/len(window[-100:])
        outside = [r[0] for r in window if abs(r[2]-final) > 3.0/4096]
        settling = (max(outside)-edge) if outside else 0
        print(f'DAC0 {label} settling to final plateau +/-1 LSB: {settling*1e9:.1f} ns')
        if settling > 1/886000:
            findings.append(f'{label} settling exceeds one 886 ksps conversion interval')
    tail = [r[1] for r in load if r[0] > 30e-6]
    print(f'200 nF AREF + 100 uA load steps, final 10 us excursion: {(max(tail)-min(tail))*1e3:.3f} mV p-p')
    if not 2.97 < op[0][1] < 3.03 or not 1.47 < op[0][2] < 1.53:
        raise RuntimeError('Reference operating point outside broad sanity limits')
    if at5[2] < -1:
        findings.append('>1 dB loss at 5 MHz; Phase A1 flatness is not demonstrated')
    if max(tail)-min(tail) > 3.0/4096:
        findings.append('AREF transient exceeds 1 LSB; compensation/bench validation needed, keep JP1 open')
    for finding in findings:
        print(f'REVIEW: {finding}')
    print('All five analyses completed. See sim/*.dat and stage_a.log.')
    if args.strict and findings:
        print(f'FAIL: {len(findings)} performance review checks remain open.')
        return 2
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
