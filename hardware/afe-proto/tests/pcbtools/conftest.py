import os
import pathlib
import sys

# hardware/afe-proto: `import pcbtools`; PCBTOOLS_ROOT points the suite at a copy of the package (the mutation harnesses)
sys.path.insert(0, os.environ.get('PCBTOOLS_ROOT') or str(pathlib.Path(__file__).resolve().parents[2]))
# hardware/pcbkit: `import pcbkit` (a mutation copy of pcbtools sits elsewhere, so the path is taken from this file)
sys.path.insert(1, str(pathlib.Path(__file__).resolve().parents[3] / 'pcbkit'))
