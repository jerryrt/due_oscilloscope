"""Shared helpers of the golden-capture scripts. Importing this module has no side effect.

Rule of this folder: a script writes only to a path given on the command line. The default is
pcbtools/.scratch/golden_out/ (ignored by git); tests/golden/ is written only with `--into-golden`, and the
committed goldens are then protected by tests/golden/MANIFEST.sha256 (see tests/golden/update_manifest.py).
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)                                   # hardware/afe-proto
GOLDEN = os.path.join(TESTS, 'golden')
GOLDEN_V2 = os.path.join(GOLDEN, 'v2-8a1f7ac')
FX = os.path.join(TESTS, 'fixtures', 'v2-8a1f7ac')
FROZEN_TOOLS = os.path.join(FX, 'tools')                         # the old tools, frozen with the fixtures
DEFAULT_OUT = os.path.join(ROOT, 'pcbtools', '.scratch', 'golden_out')
CAPPED = os.environ.get('CAPPED', '')                            # capped.sh path; empty = uncapped (the container caps itself)
# the pinned image's sha256 digest: PCB_IMAGE_ID when given, else what docker/pcb/run.sh puts in the container's env; None on a host
IMAGE_ID = os.environ.get('PCB_IMAGE_ID') or os.environ.get('DUE_PCB_IMAGE_CONTENT')
INSTALLED = os.environ.get('DUE_PCB_IMAGE_INSTALLED')
PY = sys.executable
REMINDER = ('\nthe golden folder was written: its hashes are now stale. Update tests/golden/MANIFEST.sha256 in the same commit:\n'
            '    python tests/golden/update_manifest.py --i-changed-a-golden\n')


def old_tools_dir():
    """the reference tools: OLD_TOOLS_DIR when set, otherwise the frozen copy in the fixture folder"""
    return os.environ.get('OLD_TOOLS_DIR') or FROZEN_TOOLS


def inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def parse_out(doc, argv=None, extra=None):
    """-> (out_dir, args). `--out DIR` (default pcbtools/.scratch/golden_out/); `--into-golden` writes tests/golden/v2-8a1f7ac/.
    An --out inside tests/golden without --into-golden is refused: the committed folder has one door."""
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None, help='output folder (default pcbtools/.scratch/golden_out/)')
    ap.add_argument('--into-golden', action='store_true', help='write tests/golden/v2-8a1f7ac/ (then update the manifest)')
    if extra:
        extra(ap)
    a = ap.parse_args(argv)
    if a.into_golden and a.out:
        ap.error('--into-golden and --out are exclusive')
    out = GOLDEN_V2 if a.into_golden else os.path.abspath(a.out or DEFAULT_OUT)
    if not a.into_golden and inside(out, GOLDEN):
        ap.error(f'{out} is inside tests/golden: pass --into-golden to write the committed goldens')
    os.makedirs(out, exist_ok=True)
    return out, a


def done(a):
    if getattr(a, 'into_golden', False):
        print(REMINDER, flush=True)


def env_record():
    import numpy
    import pcbnew
    return dict(label='working reference, host .venv-pcb' if not IMAGE_ID else 'container', image_id=IMAGE_ID, interpreter=PY,
                python=sys.version.split()[0], numpy=numpy.__version__, kicad=pcbnew.GetBuildVersion(),
                **(dict(installed=INSTALLED) if INSTALLED else {}))


def _wall(s):
    w = 0.0
    for x in s.split(':'):
        w = w * 60 + float(x)
    return w


def run(cmd, mem='3G', tmo=300, env=None):
    """-> (rc, stdout, wall_s, rss_kb, attempts); retries a signal death (a pcbnew start-up segfault) up to 3 times.
    Child processes never write bytecode (the fixtures folder must stay free of it)."""
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', **(env or {}))
    for attempt in range(1, 4):
        p = subprocess.run(([CAPPED, '-m', mem, '-t', str(tmo)] if CAPPED else []) + ['/usr/bin/time', '-v'] + cmd,
                           capture_output=True, text=True, env=e)
        err = p.stderr
        if p.returncode in (139, -11, 134, -6) or 'Command terminated by signal' in err:
            continue
        wall = _wall(re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)', err).group(1))
        rss = int(re.search(r'Maximum resident set size \(kbytes\): (\d+)', err).group(1))
        return p.returncode, p.stdout, wall, rss, attempt
    return p.returncode, p.stdout, None, None, 3
