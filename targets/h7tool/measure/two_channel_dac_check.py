"""CH1 and CH2 follow DAC0 and DAC1 independently (level pairs, swapped).

Backs a figure in targets/h7tool/docs/11-*.md. Needs: Due DAC0 on CH1 and DAC1 on CH2, Due daemon, H7 image8a or later.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, time, struct, subprocess, re
sys.path.insert(0, "host")
from daemon.client import Client
CHK = [".venv/bin/python", "targets/h7tool/tools/h7_stream_check.py", "--adc", "--seconds", "2"]
def pair(c0, c1): return b"".join(struct.pack("<H", v) for v in ((0 << 12) | c0, (1 << 12) | c1)) * 2000
with Client("127.0.0.1", 45454, timeout=30) as cl:
    cl.hello("control")
    for c0, c1 in ((512, 3584), (3584, 512), (1536, 2560), (2048, 2048)):
        try: cl.call("stop")
        except Exception: pass
        cl.send_awg(pair(c0, c1)); time.sleep(0.3)
        cl.call("start", mode="play", dac_sps=200000, adc_hz=200000, channels=1); time.sleep(1.5)
        out = subprocess.run(CHK, capture_output=True, text=True).stdout
        print("DAC0", c0, "DAC1", c1, "|", re.findall(r"ch\d=.*?(?= \w+=|$)", out.replace("\n"," ")), re.findall(r"gaps=\d+|lost=\d+|bad_crc=\d+|rate_ok=\w+|clean=\w+", out), flush=True)
    cl.call("stop")
