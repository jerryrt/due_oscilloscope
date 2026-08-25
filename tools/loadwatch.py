"""Poll main-loop load over the control channel and log every sample.

Runs beside the test suite. The point is that the control channel is a
different endpoint pair on a different interface, so it keeps answering
while the sample path is blocked - which is exactly the window nobody
has ever been able to see into during objective 0c.
"""
import os, sys, time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host"))
import control  # noqa: E402

if len(sys.argv) != 4:
    sys.exit("usage: loadwatch.py <command-port> <logfile> <stopfile>\n"
             "  discover the port with: python3 host/ports.py")

PATH, OUT, STOP = sys.argv[1], sys.argv[2], sys.argv[3]

log = open(OUT, "w", buffering=1)
prev = None
c = None
while not os.path.exists(STOP):
    try:
        if c is None:
            c = control.Control(PATH, timeout=1.0)
            log.write(f"{time.time():.3f} OPEN\n")
        r = c.load()
        if prev is not None:
            dt = (r["dev_us"] - prev["dev_us"]) / 1e6
            dp = r["passes"] - prev["passes"]
            if dt > 0:
                grew = r["max_cycles"] > prev["max_cycles"]
                log.write(f"{time.time():.3f} rate={dp/dt/1000:7.1f}k "
                          f"dt={dt:.3f} worst={r['max_us']/1000:9.3f}ms"
                          f"{' NEW-WORST' if grew else ''}\n")
        prev = r
        time.sleep(0.1)
    except Exception as e:                                   # noqa: BLE001
        log.write(f"{time.time():.3f} ERR {e!r}\n")
        try:
            if c: c.close(wedge_s=2.0)
        except Exception: pass
        c = None
        prev = None
        time.sleep(0.5)
log.write(f"{time.time():.3f} STOP\n")
