"""the two controls that must fail: a starved ring fires the underrun counter, an out-of-range code trips the firmware guard.

Backs a figure in targets/h7tool/docs/14-*.md. Needs: VOUT on CH2, H7 image10a only (image11 has no firmware guard; the host cap replaced it).
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, struct, time
sys.path.insert(0, ".")
sys.path.insert(0, "/tmp/claude-1000/-home-jerry-MCU-Projects-due-oscilloscope/6b9bc5f2-fd36-4e08-a917-b3aeaa01a909/scratchpad")
import play_test as pt
fs = 200e6 / 800
good = pt.sine(32000, 1000, fs, 300)
print("CONTROL 1: host stops writing for 1 s (ring must run dry)")
buf, wrote, st, end = pt.session(good, 4, gap=(1.0, 2.0))
print("  ", st)
bad = bytearray(good); struct.pack_into("<H", bad, 2000, 3000)      # one code far outside the swing cap
print("CONTROL 2: one out-of-range code (3000, about +5.8 V) in the stream")
buf, wrote, st, end = pt.session(bytes(bad), 2)
print("  ", st); print("   after stop:", end); print("   generator:", pt.run("gen").strip()[:60])
