"""The interactive HTML BOM through the pinned InteractiveHtmlBom, headless.

    python3 -m pcbkit.ibom BOARD.kicad_pcb [--dest-dir DIR] [--name-format FMT] [plugin options ...]

InteractiveHtmlBom lives under $IBOM_HOME (its directory holding the package `InteractiveHtmlBom`); the plugin runs with no display and no browser. Every other argument is the plugin's
own. The plugin's log line "Created file <path>" names the output; `run()` returns that path. wx prints "Debug: Adding duplicate image handler" lines on import; only those are dropped.
Exit status is the plugin's; a missing plugin is exit 3 and a message, never a silent skip."""
import os, subprocess, sys

NOISE = 'Debug: Adding duplicate image handler'


def run(board, extra=(), home=None, python=None):
    """(exit code, created path or None, stderr text without the wx noise)"""
    home = home or os.environ.get('IBOM_HOME', '')
    if not os.path.isdir(os.path.join(home, 'InteractiveHtmlBom')):
        return 3, None, 'ibom: InteractiveHtmlBom is not under IBOM_HOME (%r); run it in the PCB image' % home
    env = dict(os.environ, PYTHONPATH=home + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''), INTERACTIVE_HTML_BOM_NO_DISPLAY='1')
    p = subprocess.run([python or sys.executable, '-m', 'InteractiveHtmlBom.generate_interactive_bom', board, '--no-browser', *extra], env=env, capture_output=True, text=True)
    err = '\n'.join(l for l in p.stderr.splitlines() if NOISE not in l)
    created = None
    for l in (p.stdout + '\n' + p.stderr).splitlines():
        if 'Created file' in l:
            created = l.split('Created file', 1)[1].strip()
    return p.returncode, created, err


def main(argv):
    if not argv:
        print('usage: python3 -m pcbkit.ibom BOARD.kicad_pcb [plugin options]', file=sys.stderr)
        return 2
    rc, created, err = run(argv[0], argv[1:])
    if err:
        print(err, file=sys.stderr)
    if created:
        print('Created file', created)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
