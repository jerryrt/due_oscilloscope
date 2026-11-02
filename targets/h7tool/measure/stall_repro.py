"""reproduce the CH2 acquisition stall at generator start and dump the DMA state while stalled (fixed in image11l).

Backs a figure in targets/h7tool/docs/15-*.md. Needs: VOUT on CH2, H7 image11h to image11k to see it; image11l no longer stalls.
Run from the repository root with the venv that has numpy and pyserial (.venv-gui) and sudo -n for the vendor requests.
Written as a bench script on 2026-11-02 and kept as run; the wiring it assumes is NOT the current one unless the line above says so.
"""
import sys, os, time, select, threading, serial
sys.path.insert(0, "targets/h7tool/tools")
import h7_awg_sweep as sw, h7_awg as awg, h7_stream_check as chk
sw.settle()
for attempt in range(12):
    sw.probe("wave 0 0"); sw.probe("gcenter 2036"); sw.probe("gperiod 40"); sw.probe("chan 2"); sw.probe("aperiod 100")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
    n = [0]; stop = threading.Event()
    def reader():
        while not stop.is_set():
            if select.select([s.fd], [], [], 0.05)[0]:
                try: n[0] += len(os.read(s.fd, 1 << 20))
                except OSError: pass
    rt = threading.Thread(target=reader, daemon=True); rt.start()
    time.sleep(0.3); sw.probe("pstart 2"); wp, wn = sw.start_writer(s.name, awg.sine(5000000, 10000, 300))
    time.sleep(1.2); a = n[0]; time.sleep(0.5)
    if n[0] == a:                      # no new data in 0.5 s while the port is open: stalled
        print("STALLED on attempt", attempt, "host bytes", n[0]); print(sw.probe("dbg").strip()); break
    sw.stop_writer(wp, wn); sw.probe("pstop"); stop.set(); rt.join(1); s.close(); time.sleep(0.5)
else:
    print("no stall in 12 attempts")
