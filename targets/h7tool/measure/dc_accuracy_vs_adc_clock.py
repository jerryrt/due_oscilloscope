"""H7 CH1 DC accuracy against Due DAC0 at four DAC levels and four ADC clock settings (the table in docs/10).

Backs a figure in targets/h7tool/docs/10-*.md. Needs: Due DAC0 wired to H7 CH1, shared GND, Due running Track B, the Due daemon (python -m daemon in host/), H7 image7 or later, H7_OBS not used (CH1 hard-coded).
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, time, subprocess, json, re
sys.path.insert(0, "host"); sys.path.insert(0, "targets/h7tool/tools")
import measure
from daemon.client import Client
PROBE = ["sudo", "-n", "python3", "targets/h7tool/tools/h7_usb_probe.py"]
CHK = [".venv/bin/python", "targets/h7tool/tools/h7_stream_check.py", "--adc", "--seconds", "3"]
codes = [512, 1536, 2560, 3584]
cfgs = [("trig 2.0 Msps ck3", None), ("free ck3 2.5", (0,1,3)), ("free ck2 5.0", (0,1,2)), ("free ck1 10", (0,1,1))]
rows = []
with Client("127.0.0.1", 45454, timeout=30) as cl:
    cl.hello("control")
    for code in codes:
        data, _ = measure.build_dc(code)
        try: cl.call("stop")
        except Exception: pass
        cl.send_awg(data); time.sleep(0.3)
        cl.call("start", mode="play", dac_sps=200000, adc_hz=200000, channels=1)
        time.sleep(1.6)
        for name, cfg in cfgs:
            if cfg is None:
                subprocess.run(PROBE + ["adcx", "0", "0", "3", "0"], check=True)
                subprocess.run(PROBE + ["rate", "2000000"], check=True, stdout=subprocess.DEVNULL)
            else:
                subprocess.run(PROBE + ["adcx", str(cfg[0]), str(cfg[1]), str(cfg[2]), "0"], check=True)
            out = subprocess.run(CHK, capture_output=True, text=True).stdout
            m = {k: float(v) for k, v in re.findall(r"(\w+)=([-0-9.]+)", out)}
            rows.append(dict(due_code=code, cfg=name, mean=m.get("mean"), std=m.get("std"), lo=m.get("lo"), hi=m.get("hi"), gaps=m.get("gaps")))
            print(rows[-1], flush=True)
    cl.call("stop")
json.dump(rows, open(sys.argv[1], "w"))
