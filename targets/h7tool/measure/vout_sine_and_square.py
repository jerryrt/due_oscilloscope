"""H7 VOUT sine amplitude (300 codes) and square edge, read on CH2 at 2.5 Msps (the first, coarse measurement; superseded by the ETS sweeps).

Backs a figure in targets/h7tool/docs/13-*.md. Needs: VOUT wired to CH2, H7 image9a or later.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import os, sys, time, struct, math, array, serial, subprocess, zlib
sys.path.insert(0, "targets/h7tool/tools")
PROBE = ["sudo", "-n", "python3", "targets/h7tool/tools/h7_usb_probe.py"]
def grab(sec):
    p = [d for d in os.listdir("/dev") if d.startswith("ttyACM")]
    import h7_stream_check as c
    s = serial.Serial(c.find_port(), 115200, timeout=0.2); buf = bytearray(); t = time.time()
    while time.time() - t < sec: buf += os.read(s.fd, 1 << 20)
    s.close(); return bytes(buf)
def samples(data):
    out = array.array("H"); pos = data.find(b"DUE0")
    while pos >= 0 and pos + 4096 <= len(data):
        h = data[pos:pos + 32]
        if zlib.crc32(h[:28]) & 0xFFFFFFFF != struct.unpack("<I", h[28:])[0]: pos = data.find(b"DUE0", pos + 1); continue
        out.frombytes(data[pos + 32:pos + 4096]); pos += 4096
    return out
def run(p): subprocess.run(PROBE + p.split(), check=True)
run("wave 0 0"); run("gcenter 2036"); run("chan 2"); run("rate 2500000")
ZERO, CPV = 32750.0, 2301.0           # CH2 zero code and codes/V at gain 0 (docs/12)
for wave, amp, period in (("2 300", 300, 800), ("2 300", 300, 400), ("3 300", 300, 800), ("4 300", 300, 800)):
    run("wave 0 0"); run(f"gperiod {period}"); run(f"wave {wave}"); time.sleep(0.6)
    x = samples(grab(1.5))[200000:]            # drop the start
    v = [(a - ZERO) / CPV for a in x]
    n = len(v); fs = 2.5e6; f = 200e6 / period / 256
    re_ = sum(v[i] * math.cos(2 * math.pi * f * i / fs) for i in range(n)) * 2 / n
    im_ = sum(v[i] * math.sin(2 * math.pi * f * i / fs) for i in range(n)) * 2 / n
    print(f"wave {wave} period {period}: f={f:.1f} Hz  min {min(v):+.3f} V  max {max(v):+.3f} V  mean {sum(v)/n:+.3f} V  fundamental {math.hypot(re_, im_):.3f} V (ideal {amp * 5.983e-3:.3f} for sine)", flush=True)
    if wave.startswith("3"):                     # edge time: samples between 10 % and 90 % of the swing
        lo, hi = min(v), max(v); t10, t90 = lo + 0.1 * (hi - lo), lo + 0.9 * (hi - lo); runs = []
        i = 1
        while i < n - 60:
            if v[i - 1] < t10 <= v[i] or v[i - 1] > t90 >= v[i]:
                j = i
                while j < n - 1 and t10 < v[j] < t90: j += 1
                runs.append(j - i + 1); i = j + 40
            else: i += 1
        print(f"   edges seen {len(runs)}; 10-90 % transition lasts {sorted(runs)[len(runs)//2] if runs else None} samples at 400 ns each")
run("wave 0 0")
