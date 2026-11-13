#!/usr/bin/env python3
"""AN-1 against the datasheet-fitted TPH2502 models is section `beh` (and `stab`) of run.py; this is the same call.
    python3 -I beh_check.py      ==      python3 -I run.py beh
"""
import os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, "-I", os.path.join(HERE, "run.py"), "beh"]))
