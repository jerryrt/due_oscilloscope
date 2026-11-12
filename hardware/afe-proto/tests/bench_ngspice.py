"""A fixed small ngspice job for the bench: the shared runner on an RC ladder, tran + ac."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simtools import ngspice_run as nr

DECK = """bench rc ladder
V1 in 0 PULSE(0 1 0 1n 1n 5u 10u) AC 1
R1 in out 1k
C1 out 0 1n
R2 out x 1k
C2 x 0 1n
.tran 0.01u 200u
.ac dec 50 1k 1meg
.end
"""
with tempfile.TemporaryDirectory() as d:
    run = nr.run(DECK, save=["v(out)", "v(x)"], workdir=d, name="bench", timeout=120)
    run.plots()
