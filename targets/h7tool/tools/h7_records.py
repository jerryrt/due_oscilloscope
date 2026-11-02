"""Append-only provenance records for the H7 AWG measurements (targets/h7tool/records/awg.jsonl).

A figure with no bench, commit, firmware build or observer attached cannot be compared with anything, and a record
that carries only its numbers cannot say whether it was a valid capture. Every measurement the sweep takes is written
here, valid or not, with the reasons it was rejected and how many tries it needed.
"""
import json
import os
import socket
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "..", "records", "awg.jsonl")


def _git(*args):
    try:
        return subprocess.run(["git", "-C", HERE] + list(args), capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def provenance():
    return dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), bench=socket.gethostname(),
                commit=_git("rev-parse", "--short", "HEAD"), dirty=bool(_git("status", "--porcelain", "--", HERE)))


def record(kind, params, metrics, valid, reasons=(), tries=1, fw_build=None, observer=None, path=None):
    """Append one record; returns it. `observer` is a dict (channel, adc_period_ticks, gain code, zero, codes per volt)."""
    rec = dict(provenance(), kind=kind, params=params, metrics=metrics, valid=bool(valid), reasons=list(reasons),
               tries=tries, fw_build=fw_build, observer=observer)
    path = path or DEFAULT_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=float) + "\n")
    return rec
