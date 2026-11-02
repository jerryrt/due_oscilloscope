"""same stall with the internal table generator and no USB OUT traffic.

Backs a figure in targets/h7tool/docs/15-*.md. Needs: as stall_repro.py.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, os, time, select, threading, serial
sys.path.insert(0, "targets/h7tool/tools")
import h7_awg_sweep as sw, h7_stream_check as chk
period = sys.argv[1]
for rep in range(4):
    sw.probe("wave 0 0"); sw.probe("gcenter 2036"); sw.probe(f"gperiod {period}"); sw.probe("chan 2"); sw.probe("aperiod 100")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
    n = [0]; stop = threading.Event()
    def reader():
        while not stop.is_set():
            if select.select([s.fd], [], [], 0.05)[0]:
                try: n[0] += len(os.read(s.fd, 1 << 20))
                except OSError: pass
    rt = threading.Thread(target=reader, daemon=True); rt.start()
    time.sleep(0.3); sw.probe("wave 2 100"); time.sleep(2.5)
    a = sw.probe("acq"); import re
    fr = re.search(r"frames_done=(\d+)", a).group(1); ov = re.search(r"adc_ovr=(\d+)", a).group(1)
    print(f"gen table, DAC period {period}: host bytes {n[0]}  frames {fr} ovr {ov}", flush=True)
    sw.probe("wave 0 0"); stop.set(); rt.join(1); s.close(); time.sleep(0.5)
