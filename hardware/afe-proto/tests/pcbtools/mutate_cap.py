"""Mutation proof for pcbtools.cap: copy the package to a scratch dir, break one line of the solver at a time with a text
edit, run tests/pcbtools/test_cap.py against the broken copy (PCBTOOLS_ROOT points the suite at it, `-x`) and require it to
FAIL. The unmutated copy must pass first. Each child runs under a 3 GB address-space limit and a 300 s timeout, one at a time.

    python tests/pcbtools/mutate_cap.py [--record]    (--record writes tests/golden/cap_mutation_result.txt: then update the manifest)
    exit 1 if any mutant survives or any pattern is not found exactly once
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))              # hardware/afe-proto
SCR = os.path.join(ROOT, 'pcbtools', '.scratch', 'mutc')
RESULT = os.path.join(ROOT, 'tests', 'golden', 'cap_mutation_result.txt')

C = 'cap.py'
MUTANTS = [
    # boundary conditions
    (C, 'lid no longer grounded', "    fixed[-1] = True", "    pass"),
    (C, 'ground plane no longer grounded', "    fixed[0] = True", "    pass"),
    (C, 'no x-direction coupling (side faces)', "for a, b in ((np.s_[:, :, :-1], np.s_[:, :, 1:]), ", "for a, b in ("),
    # permittivity
    (C, 'substrate permittivity 1', "    eps[:nzb + 1] = stack.er\n", "    eps[:nzb + 1] = 1.0\n"),
    (C, 'copper-layer interface permittivity not averaged', "    eps[nzb] = (stack.er + 1) / 2", "    eps[nzb] = stack.er"),
    (C, 'air permittivity 2', "    eps = np.ones(shape)\n", "    eps = np.full(shape, 2.0)\n"),
    (C, 'face permittivity: arithmetic instead of harmonic mean', "w.append((2 * ea * eb / (ea + eb)).ravel())", "w.append(((ea + eb) / 2).ravel())"),
    # cell size scaling, capacitance from flux
    (C, 'cell size enters twice', "return q * h * 1e-3 * E0 * 1e12", "return q * h * h * 1e-3 * E0 * 1e12"),
    (C, 'cell size dropped', "return q * h * 1e-3 * E0 * 1e12", "return q * 1e-3 * E0 * 1e12"),
    (C, 'mutual capacitance sign', "res[(i, j)] = -to_pF(", "res[(i, j)] = to_pF("),
    (C, 'charge is a mean, not a sum', ".reshape(self.shape)[mask].sum())", ".reshape(self.shape)[mask].mean())"),
    (C, 'charge read on the whole grid', ".reshape(self.shape)[mask].sum())", ".reshape(self.shape).sum())"),
    (C, 'drive 2 V', "        v[nzb][masks[i]] = 1.0", "        v[nzb][masks[i]] = 2.0"),
    # solver
    (C, 'solver tolerance 0.5', "rtol=self.tol, atol=0.0", "rtol=0.5, atol=0.0"),
    # geometry
    (C, 'capsule radius is the full width', "        r = w / 2\n", "        r = w\n"),
    (C, 'rect is open at its edges', "(X >= rects[k, 0]) & (X <= rects[k, 2])", "(X > rects[k, 0]) & (X < rects[k, 2])"),
    (C, 'ragged expansion swaps row and column', "yield item, i0[item] + local // w, j0[item] + local % w", "yield item, i0[item] + local % w, j0[item] + local // w"),
    (C, 'coordinates not rounded to the nanometre', "return np.round(kx, boardio.ND) + 0.0, np.round(ky, boardio.ND) + 0.0", "return kx, ky"),
    (C, 'B.Cu tracks counted as top copper', "    top_s = b.s_layer == 0", "    top_s = b.s_layer >= 0"),
    (C, 'arcs dropped', "        seg = np.vstack([seg, c1, c2])", "        pass"),
    (C, 'window ignores its pad', "return kx.min() - pad, ky.min() - pad, kx.max() + pad, ky.max() + pad", "return kx.min() - pad, ky.min() - pad, kx.max() + pad, ky.max() + pad * 0"),
    # the grid-size guard (review finding 17)
    (C, 'grid guard never refuses', "    if n > lim:\n", "    if n > lim * 10 ** 9:\n"),
    (C, 'grid guard after the allocation', "    check_grid(nx, ny, nz)\n    eps = _eps((nz, ny, nx), nzb, stack)\n    masks", "    eps = _eps((nz, ny, nx), nzb, stack)\n    check_grid(nx, ny, nz)\n    masks"),
    # pour and the other nets
    (C, 'no pour keep-back radius', "    k = int(round(clear / h))\n", "    k = 0\n"),
    (C, 'pour case without the pour', "            g = g | ~keep_back(m | other, stack.pour_clear, h)", "            g = g"),
    (C, 'other nets float instead of 0 V (pair)', "    cond[nzb] = gnd | other\n", "    cond[nzb] = gnd\n"),
    (C, 'ground treated as any other net', "code[b.net_id(gnd)] = len(nets) + 1", "code[b.net_id(gnd)] = len(nets)"),
    (C, 'keep-back wraps round the window (np.roll)', "return ndi.binary_dilation(occupied, structure=(xx * xx + yy * yy <= k * k)) if k else occupied.copy()",
     "return ndi.binary_dilation(occupied, structure=(xx * xx + yy * yy <= k * k), border_value=1) if k else occupied.copy()"),
    # the config entry (stage 4b): the report must use every CAP_SELF entry
    ('boards/v2.py', 'CAP_SELF without the divider nodes', "CAP_SELF = (('/AWG_FB', 3.0, 0.1), ('/CH1_N', 3.0, 0.1), ('/CH2_N', 3.0, 0.1))", "CAP_SELF = (('/AWG_FB', 3.0, 0.1),)"),
    ('boards/v2.py', 'CAP_SELF /CH2_N dropped', "('/CH1_N', 3.0, 0.1), ('/CH2_N', 3.0, 0.1))", "('/CH1_N', 3.0, 0.1))"),
]


def run(tag, edit):
    d = os.path.join(SCR, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    shutil.copytree(os.path.join(ROOT, 'pcbtools'), os.path.join(d, 'pcbtools'), ignore=shutil.ignore_patterns('.scratch', '__pycache__'))
    os.symlink(os.path.join(ROOT, 'tests'), os.path.join(d, 'tests'))            # boards/v2.py finds its fixtures relative to the package
    if edit:
        f, old, new = edit
        p = os.path.join(d, 'pcbtools', f)
        s = open(p).read()
        if s.count(old) != 1:
            return 'BAD-MUTANT (pattern found %d times)' % s.count(old)
        open(p, 'w').write(s.replace(old, new))

    def limit():
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))
    p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', '-c', os.path.join(ROOT, 'tests', 'pytest.ini'),
                        os.path.join(HERE, 'test_cap.py')], capture_output=True, text=True, cwd=ROOT, timeout=300, preexec_fn=limit,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PCBTOOLS_ROOT=d))
    lines = p.stdout.strip().splitlines()
    first = next((ln for ln in lines if ln.startswith('FAILED')), '')
    tail = lines[-1] if lines else p.stderr[-200:]
    return ('PASSED' if p.returncode == 0 else 'FAILED') + ' | ' + tail + ((' | first ' + first.split('::')[-1].split(' ')[0]) if first else '')


def main(argv):
    out, bad = [], []
    r = run('clean', None)
    out.append('unmutated copy: ' + r)
    print(out[-1], flush=True)
    if not r.startswith('PASSED'):
        return 2
    for i, (f, name, old, new) in enumerate(MUTANTS):
        r = run(f'm{i}', (f, old, new))
        ok = r.startswith('FAILED')
        out.append(('caught   ' if ok else 'SURVIVED ') + name + '  [' + r + ']')
        print(out[-1], flush=True)
        if not ok:
            bad.append(name)
    out.append(f'{len(MUTANTS)} mutants: ' + ('every mutant caught' if not bad else 'SURVIVORS: ' + '; '.join(bad)))
    print(out[-1], flush=True)
    if '--record' in argv:
        with open(RESULT, 'w') as f:
            f.write('working reference, host .venv-pcb\n' + '\n'.join(out) + '\n')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
