"""observer (H7 CH1) frequency response using the Due DAC as an independent source.

Backs a figure in targets/h7tool/docs/15-*.md. Needs: Due DAC0 on CH1, Due daemon, H7 image11 or later.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, os, time, math, struct, select, threading, serial
sys.path.insert(0, "targets/h7tool/tools"); sys.path.insert(0, "host")
import numpy as np
import h7_awg_sweep as sw, h7_stream_check as chk, h7_ets as ets
from daemon.client import Client
ZERO1, CPV1 = 32843.0, 2310.0          # CH1 zero and codes/V at gain 0 (docs/12)
sw.probe("wave 0 0"); sw.probe("chan 1"); sw.probe("aperiod 100")
sw.settle()
def due_sine(ppc, amp=800):
    n = ppc * max(1, 4000 // ppc)
    return b"".join(struct.pack("<H", (0 << 12) | int(round(2048 + amp * math.sin(2 * math.pi * i / ppc)))) for i in range(n))
rows = []
with Client("127.0.0.1", 45454, timeout=30) as cl:
    cl.hello("control")
    for f, ppc in ((10_000, 100), (20_000, 50), (50_000, 20), (100_000, 10), (125_000, 8), (200_000, 5)):
        try: cl.call("stop")
        except Exception: pass
        cl.send_awg(due_sine(ppc)); time.sleep(0.3)
        cl.call("start", mode="play", dac_sps=1_000_000, adc_hz=200000, channels=1); time.sleep(1.0)
        s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
        data = bytearray(); stop = threading.Event()
        def reader():
            while not stop.is_set():
                if select.select([s.fd], [], [], 0.05)[0]:
                    try: data.extend(os.read(s.fd, 1 << 20))
                    except OSError: pass
        rt = threading.Thread(target=reader, daemon=True); rt.start(); time.sleep(1.5); stop.set(); rt.join(1); s.close()
        v = (ets.gapless_samples(bytes(data)) - ZERO1) / CPV1
        v = v[len(v) // 4:]; n = min(len(v), 1 << 20); v = v[:n] - v[:n].mean()
        F = np.abs(np.fft.rfft(v * np.hanning(n))) * 2 / (0.5 * n); fs = 2e6 / 1.04     # ADC period 100 -> 2 Msps
        k0 = int(f / (2e6 / n)); lo, hi = int(k0 * 0.97), int(k0 * 1.03) + 2
        amp = F[lo:hi].max()
        rows.append((f, amp)); print(f"Due tone {f/1e3:5.0f} kHz ({ppc} pts/period at 1 MS/s): H7 CH1 reads {amp:.3f} V peak, {len(v)} samples", flush=True)
    cl.call("stop")
ref = rows[0][1]
for f, a in rows:
    droop = 20 * math.log10(math.sin(math.pi * f / 1e6) / (math.pi * f / 1e6)) if f else 0      # Due zero-order-hold sinc
    print(f"{f/1e3:6.0f} kHz: observer(CH1) vs 10 kHz {20*math.log10(a/ref):+6.2f} dB;  expected from the Due's own hold {droop:+6.2f} dB")
