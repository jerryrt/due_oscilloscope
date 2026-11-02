"""CH1 and CH2 gain table: AC-coupled 1 kHz sines from both Due DACs, noise subtracted, codes per volt per gain code.

Backs a figure in targets/h7tool/docs/12-*.md. Needs: Due DAC0 on CH1 and DAC1 on CH2, shared GND, Due daemon, H7 image8d or later.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, time, struct, math, subprocess, re
sys.path.insert(0, "host")
from daemon.client import Client
PROBE = ["sudo", "-n", "python3", "targets/h7tool/tools/h7_usb_probe.py"]
CHK = [".venv/bin/python", "targets/h7tool/tools/h7_stream_check.py", "--adc", "--seconds", "1.5"]
FACT = [2284.9, 4584.8, 9198.6, 18433, 36982, 74017, 148187, 296687]
VLSB = 0.53722e-3                      # H7 session's DAC0 fit, assumed for DAC1 too
def cap():
    out = subprocess.run(CHK, capture_output=True, text=True).stdout
    return [(float(m), float(s)) for m, s in re.findall(r"ch\d=mean ([-0-9.]+) std ([-0-9.]+)", out)]
def wave(a):
    pts = [int(round(2048 + a * math.sin(2 * math.pi * i / 100))) for i in range(100)]
    return b"".join(struct.pack("<H", (t << 12) | v) for v in pts for t in (0, 1)) * 20
amp_v = [1.0, 1.0, 1.0, 0.7, 0.35, 0.17, 0.08, 0.04]
subprocess.run(PROBE + ["chan", "3"], check=True)
with Client("127.0.0.1", 45454, timeout=30) as cl:
    cl.hello("control")
    for g in range(8):
        subprocess.run(PROBE + ["fe", hex(g | (g << 4))], check=True)          # AC coupling, gain g on both
        a_codes = amp_v[g] / VLSB / 1.0
        res = []
        for label, data in (("dc", wave(0)), ("sine", wave(a_codes))):
            try: cl.call("stop")
            except Exception: pass
            cl.send_awg(data); time.sleep(0.3)
            cl.call("start", mode="play", dac_sps=200000, adc_hz=200000, channels=1); time.sleep(1.2)
            res.append(cap())
        out = []
        for ch in (0, 1):
            sd, ss = res[0][ch][1], res[1][ch][1]
            sig = math.sqrt(max(ss * ss - sd * sd, 0))
            out.append(sig * math.sqrt(2) / amp_v[g])         # codes per volt (peak)
        print(f"gain {g}: CH1 {out[0]:9.0f}  CH2 {out[1]:9.0f}  codes/V   factory {FACT[g]:9.0f}  ratio {out[0]/FACT[g]:.3f} {out[1]/FACT[g]:.3f}   noise std {res[0][0][1]:.0f} {res[0][1][1]:.0f}", flush=True)
    cl.call("stop")
subprocess.run(PROBE + ["fe", "0x88"])
