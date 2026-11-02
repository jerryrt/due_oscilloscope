"""74HCT595 coupling bits: DC step visible with Q3=1, blocked with Q3=0.

Backs a figure in targets/h7tool/docs/12-*.md. Needs: Due DAC0 on CH1 (daemon), H7 image8d or later (the GPIOI clock fix).
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, time, subprocess, re
sys.path.insert(0, "host")
import measure
from daemon.client import Client
PROBE = ["sudo", "-n", "python3", "targets/h7tool/tools/h7_usb_probe.py"]
CHK = [".venv/bin/python", "targets/h7tool/tools/h7_stream_check.py", "--adc", "--seconds", "1.5"]
def cap():
    out = subprocess.run(CHK, capture_output=True, text=True).stdout
    m = re.search(r"ch0=mean ([-0-9.]+) std ([-0-9.]+)", out)
    return round(float(m.group(1)), 1), float(m.group(2))
with Client("127.0.0.1", 45454, timeout=30) as cl:
    cl.hello("control")
    for code in (512, 3584):
        data, _ = measure.build_dc(code)
        try: cl.call("stop")
        except Exception: pass
        cl.send_awg(data); time.sleep(0.3)
        cl.call("start", mode="play", dac_sps=200000, adc_hz=200000, channels=1); time.sleep(1.5)
        for fe in ("0x88", "0x00", "0x08", "0x80", "0x88"):
            subprocess.run(PROBE + ["fe", fe], check=True); time.sleep(0.4)
            print("due", code, "fe", fe, cap(), flush=True)
    cl.call("stop")
