#!/usr/bin/env python3
"""Screen the exported Stage A driver and one candidate; not a release gate."""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from run import executable, kicad_cli

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
ADC_CLOCK = 19.5e6
ACQUISITION = 15 / ADC_CLOCK
LSB = 3 / 4096
# A first-order surrogate fitted to t_ns = 0.054 * Z_ohm + 205.
# Half-LSB settling of a full-scale 12-bit step is an explicit assumption.
CSAMPLE = 0.054e-9 / math.log(8192)
RON = 205 / 0.054
MODELS = {'mcp6024': 'MCP6024_VENDOR', 'opa4350': 'OPA4350_CANDIDATE'}


class SettlingNotEstablished(ValueError):
    """A valid capture failed to establish a settled plateau."""


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Expected exactly one {old!r}; schematic/fixture changed')
    return text.replace(old, new)


def read_data(path, columns):
    lines = path.read_text().splitlines()
    data = [list(map(float, line.split())) for line in lines[1:] if line.strip()]
    if len(data) < 2 or any(len(row) != columns or
                            not all(math.isfinite(x) for x in row) for row in data):
        raise ValueError(f'Invalid or incomplete data: {path}')
    if any(b[0] <= a[0] for a, b in zip(data, data[1:])):
        raise ValueError(f'Non-increasing independent variable: {path}')
    return data


def interpolate(data, at, column):
    times = [row[0] for row in data]
    if not times[0] <= at <= times[-1]:
        raise ValueError(f'Missing coverage at {at}')
    i = bisect.bisect_left(times, at)
    if times[i] == at:
        return data[i][column]
    a, b = data[i-1], data[i]
    return a[column] + (b[column]-a[column]) * (at-a[0]) / (b[0]-a[0])


def settling(data, edge, stop, column, band=LSB):
    window = [r for r in data if edge <= r[0] <= stop]
    if len(window) < 10 or window[-1][0] < stop - 5e-9:
        raise ValueError('Insufficient step-response coverage')
    tail = [r[column] for r in window if r[0] >= stop - 0.5e-6]
    final = sum(tail) / len(tail)
    if max(tail)-min(tail) > band / 4:
        raise SettlingNotEstablished('Final plateau is not stable enough to measure settling')
    outside = [i for i, r in enumerate(window) if abs(r[column]-final) > band]
    if outside and outside[-1] == len(window)-1:
        raise SettlingNotEstablished('Response never settles within the observation window')
    # First known in-band sample after the LAST excursion: a conservative bound.
    index = outside[-1]+1 if outside else 0
    return window[index][0]-edge


def sources(vdd, low, high, sampling, wire_l):
    dac0 = f'DC {high}' if sampling else f'DC 1.5 AC 1 PULSE({low} {high} 2u 1n 1n 3u 10u)'
    dac1 = f'DC {low}' if sampling else 'DC 1.5'
    return f'''* JP1 open: no ADVREF load is connected in this driver screen.
V3V3 +3V3 0 {vdd}
VDAC0 /DAC0 0 {dac0}
VDAC1 /DAC1 0 {dac1}
VBUFFER buffer Net-_U1C--_ 0
* Wiring sensitivity values are assumptions, not extracted board geometry.
RWIRE0 /A0 wire0 0.1
LWIRE0 wire0 adc0 {wire_l}
RWIRE1 /A1 wire1 0.1
LWIRE1 wire1 adc1 {wire_l}
* 8 pF pin-load allowance; do not identify this with Csample.
CPIN0 adc0 0 8p
CPIN1 adc1 0 8p
'''


def acquisition_fixture(low, high, tacq):
    return f'''* Sampling-only experiment: two independent surrogate loads.
* Not a cycle-accurate model of the shared SAM3X multiplexer or ADC.
.model SAMPLE SW(Ron={RON} Roff=1e15 Vt=0.5 Vh=0)
.model PRECHARGE SW(Ron=1 Roff=1e15 Vt=0.5 Vh=0)
VTRACK track 0 PULSE(0 1 5u 100p 100p {tacq} 20u)
VRESET reset 0 PULSE(1 0 4u 100p 100p 10u 20u)
VPREV0 previous0 0 {low}
VPREV1 previous1 0 {high}
SPRE0 sample0 previous0 reset 0 PRECHARGE
SPRE1 sample1 previous1 reset 0 PRECHARGE
SADC0 adc0 sample0 track 0 SAMPLE
SADC1 adc1 sample1 track 0 SAMPLE
CSAMPLE0 sample0 0 {CSAMPLE}
CSAMPLE1 sample1 0 {CSAMPLE}
'''


def deck(exported, model, vdd=3.3, temp=27, low=0.5, high=2.5,
         r_scale=1, c_scale=1, wire_l=1e-12, sampling=False,
         tacq=ACQUISITION, timestep=2e-9):
    circuit = replace_once(exported, '.include "sim/sources.cir"', '')
    circuit = '\n'.join(line for line in circuit.splitlines()
                        if line.strip().lower() != '.end' and
                        not line.lower().startswith('.title'))
    circuit = replace_once(circuit, ' MCP6024_VENDOR', f' {MODELS[model]}')
    for ref, value, scale in [('R5', '68', r_scale), ('R6', '68', r_scale),
                              ('C5', '470p', c_scale), ('C6', '470p', c_scale)]:
        lines = [line for line in circuit.splitlines() if line.startswith(ref+' ')]
        if len(lines) != 1 or lines[0].split()[-1] != value:
            raise ValueError(f'{ref} changed; review screening assumptions')
        amount = (470e-12 if value == '470p' else 68) * scale
        circuit = replace_once(circuit, lines[0],
                               ' '.join(lines[0].split()[:-1]) + f' {amount}')
    stimulus = sources(vdd, low, high, sampling, wire_l)
    if sampling:
        stimulus += acquisition_fixture(low, high, tacq)
        analysis = f'''tran {timestep} 7u 0 {timestep}
wrdata sample.dat v(adc0) v(sample0) v(adc1) v(sample1)
'''
    else:
        analysis = f'''op
wrdata op.dat v(/reference/VREF3V0) v(/VREF1V5) i(V3V3)
ac dec 100 1k 100meg
let adc_db = db(v(adc0))
let buffer_db = db(v(buffer))
wrdata ac.dat adc_db buffer_db
tran {timestep} 8u 0 {timestep}
wrdata step.dat v(/DAC0) v(adc0)
'''
    return f'''Stage A driver screen - evaluation, not qualification
{circuit}
.include "{PROJECT / 'models/candidates.lib'}"
.temp {temp}
.options reltol=1e-5 abstol=1e-12 vntol=1e-8 rshunt=1e12
.nodeset v(/reference/VREF3V0)=3 v(/VREF1V5)=1.5
.nodeset v(Net-_U1C--_)=1.5 v(Net-_U1D--_)=1.5
{stimulus}
.control
set wr_vecnames
set wr_singlescale
set numdgt=12
{analysis}
quit
.endc
.end
'''


def simulate(spice, directory, text, sampling):
    directory.mkdir(parents=True, exist_ok=True)
    files = ['sample.dat'] if sampling else ['op.dat', 'ac.dat', 'step.dat']
    for name in files:
        (directory / name).unlink(missing_ok=True)
    (directory / 'screen.cir').write_text(text)
    with (directory/'screen.log').open('w') as log:
        proc = subprocess.run([spice, '-n', '-D', 'ngbehavior=ps', '-b', 'screen.cir'],
                              cwd=directory, text=True, stdout=log,
                              stderr=subprocess.STDOUT, timeout=120)
    diagnostic = (directory/'screen.log').read_text().lower()
    if proc.returncode or any(s in diagnostic for s in
                              ('error:', 'fatal error', 'timestep too small', 'no such vector')):
        raise RuntimeError(f'Simulation failed: {directory / "screen.log"}')
    if any(not (directory/name).is_file() for name in files):
        raise RuntimeError(f'Simulation outputs missing: {directory}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['all', *MODELS], default='mcp6024')
    parser.add_argument('--quick', action='store_true', help='nominal comparison only')
    args = parser.parse_args()
    cli, spice = kicad_cli(), executable('ngspice')
    output = HERE / 'screen-output' / args.model
    output.mkdir(parents=True, exist_ok=True)
    # Remove the old summary BEFORE running: failure cannot leave a stale verdict.
    (output/'summary.json').unlink(missing_ok=True)
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'spice',
                    '-o', str(output/'schematic.net'),
                    str(PROJECT/'afe-shield.kicad_sch')], check=True)
    exported = (output/'schematic.net').read_text()
    cases = [('nominal', {})]
    if not args.quick:
        cases += [('supply-low', {'vdd': 3.135}), ('supply-high', {'vdd': 3.465}),
                  ('cold', {'temp': -20}), ('hot', {'temp': 70}),
                  ('rc-low', {'r_scale': .99, 'c_scale': .95}),
                  ('rc-high', {'r_scale': 1.01, 'c_scale': 1.05}),
                  ('wire-100nH', {'wire_l': 100e-9}),
                  ('wire-1uH', {'wire_l': 1e-6}),
                  ('wire-1uH-fine', {'wire_l': 1e-6, 'timestep': 1e-9}),
                  ('stock-dac', {'low': .55, 'high': 2.75})]
    results = []
    models = MODELS if args.model == 'all' else [args.model]
    for model in models:
        for name, params in cases:
            directory = output / f'{model}-{name}'
            simulate(spice, directory, deck(exported, model, **params), False)
            ac = read_data(directory/'ac.dat', 3)
            transient = read_data(directory/'step.dat', 3)
            op = list(map(float, (directory/'op.dat').read_text().splitlines()[1].split()))
            if len(op) != 4 or not all(map(math.isfinite, op)):
                raise ValueError('Invalid operating-point data')
            row = {'model': model, 'case': name, 'conditions': params,
                   'buffer_5MHz_db': interpolate(ac, 5e6, 2),
                   'adc_5MHz_db': interpolate(ac, 5e6, 1),
                   'supply_current_A': -op[3]}
            for label, edge, stop in [('rise', 2e-6, 4.9e-6), ('fall', 5.001e-6, 7.9e-6)]:
                try:
                    row[f'{label}_settle_s'] = settling(transient, edge, stop, 2)
                except SettlingNotEstablished as exc:
                    row[f'{label}_settle_s'] = None
                    row[f'{label}_finding'] = str(exc)
            settling_times = [row['rise_settle_s'], row['fall_settle_s']]
            settled = all(t is not None for t in settling_times)
            row['screen_checks'] = {
                'buffer_within_1dB_at_5MHz': abs(row['buffer_5MHz_db']) <= 1,
                'step_within_886ksps_interval': settled and max(settling_times) <= 1/886000,
            }
            results.append(row)
            settle_label = f'{max(settling_times)*1e9:.1f} ns' if settled else 'NOT ESTABLISHED'
            print(f'{model}/{name}: buffer@5MHz={row["buffer_5MHz_db"]:.3f} dB; '
                  f'settle={settle_label}; '
                  f'supply={row["supply_current_A"]*1e3:.2f} mA', flush=True)
        for name, tacq, timestep, wire_l in [('datasheet', ACQUISITION, 2e-9, 1e-12),
                                            ('short-210ns', 210e-9, 2e-9, 1e-12),
                                            ('convergence', ACQUISITION, 1e-9, 1e-12),
                                            ('wire-1uH', ACQUISITION, 2e-9, 1e-6)]:
            directory = output / f'{model}-sample-{name}'
            simulate(spice, directory, deck(exported, model, sampling=True,
                     tacq=tacq, timestep=timestep, wire_l=wire_l), True)
            data = read_data(directory/'sample.dat', 5)
            # Sample immediately BEFORE the switch begins opening, not after hold.
            at = 5e-6 + tacq
            errors = [interpolate(data, at, col)-interpolate(data, 4.9e-6, pin)
                      for col, pin in [(2, 1), (4, 3)]]
            total = [interpolate(data, at, col)-target
                     for col, target in [(2, 2.5), (4, .5)]]
            row = {'model': model, 'case': f'sample-{name}', 'acquisition_s': tacq,
                   'timestep_s': timestep, 'wire_H': wire_l,
                   'dynamic_error_V': errors, 'total_error_V': total}
            row['screen_checks'] = {
                'dynamic_error_within_half_LSB': max(map(abs, errors)) <= LSB/2,
                'total_error_within_one_LSB': max(map(abs, total)) <= LSB,
            }
            results.append(row)
            print(f'{model}/sample-{name}: dynamic={[round(x/LSB, 4) for x in errors]} LSB; '
                  f'total={[round(x/LSB, 4) for x in total]} LSB', flush=True)
    source_files = [*PROJECT.glob('*.kicad_sch'),
                    *PROJECT.glob('models/**/*.lib'), *PROJECT.glob('models/**/*.LIB'),
                    *PROJECT.glob('models/vendor/microchip/*.txt'),
                    Path(__file__), HERE/'run.py']
    report = {'purpose': 'engineering screen; NOT a fabrication or hardware qualification',
              'scope': 'one-factor sensitivities, not combined worst-case corners; JP1 open',
              'thresholds': 'diagnostic allocations, not newly approved system specifications',
              'source_sha256': {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(source_files)},
              'netlist_sha256': hashlib.sha256(exported.encode()).hexdigest(),
              'kicad': subprocess.check_output([cli, '--version'], text=True).strip(),
              'ngspice': subprocess.check_output([spice, '--version'], text=True).strip(),
              'sampling_model': {'CSAMPLE_F': CSAMPLE, 'RON_ohm': RON,
                                 'basis': 'SAM3X 11057C section 45.7.2.1, first-order fit; not silicon values'},
              'results': results}
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    failed = sum(not passed for row in results for passed in row['screen_checks'].values())
    print(f'Diagnostic checks outside limits: {failed}. Stress cases are not release specifications.')
    print(f'Completed screen: {output / "summary.json"}. No BOM change or release implied.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
