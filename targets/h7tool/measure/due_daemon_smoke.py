"""Regression guard for the shared host code: start the REAL Due through the daemon, take frames, stop, and check what a
Due client has always seen (hello description, rates, a v3 frame stream with the Due's tags). Run before and after any change
to host/daemon or gui that the H7 work makes. Writes nothing to the Due's flash; needs the Due attached (programming port and native
pair), the venv with pyserial, and no other process on those ports (stop any daemon first).

    .venv/bin/python targets/h7tool/measure/due_daemon_smoke.py
Exit status is non-zero on any failed check.
"""
import os, struct, subprocess, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "host"))
from daemon.client import Client

HDR = struct.Struct("<4sBBHIIIIII")


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg, flush=True)
    if not ok: sys.exit(1)


def main():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "host"))
    d = subprocess.Popen([sys.executable, "-m", "daemon", "--port", "45499"], cwd=os.path.join(ROOT, "host"), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        cl = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                cl = Client("127.0.0.1", 45499, timeout=20); cl.connect(); break
            except Exception:
                cl = None
        check(cl is not None, "the daemon came up on the real Due")
        h = cl.hello("control"); dev = h.get("device", {})
        print("device:", {k: dev.get(k) for k in ("kind", "track", "frame_bytes", "samples_per_frame")})
        check(dev.get("kind") == "board" and dev.get("frame_bytes") == 4096 and dev.get("samples_per_frame") == 2032, "description: a Due board, 4096-byte frames, 2032 samples")
        r = cl.call("rate", adc_hz=200000, channels=2); check(r["adc"]["actual_hz"] > 0 and "rc" in r["adc"], f"rate snap: {r['adc']}")
        cl.subscribe(True)
        s = cl.call("start", mode="capture", adc_hz=200000, channels=2)
        check(s.get("event") == "started" and "adc" in s["rates"], f"started: {s['rates']}")
        frames = cl.wait_frames(40, timeout=20)
        check(len(frames) >= 40, f"{len(frames)} frames received")
        bad = 0; tags = set(); last = None; gaps = 0
        for f in frames:
            magic, ver, flags, mask, seq, rate, ts, ovr, pc, crc = HDR.unpack_from(f, 0)
            bad += (magic != b"DUE0" or ver != 3 or len(f) != 4096)
            if last is not None and seq != last + 1: gaps += 1
            last = seq
            import array
            a = array.array("H"); a.frombytes(f[32:]); tags |= {v >> 12 for v in a[:64]}
        check(bad == 0, "every frame is magic DUE0, version 3, 4096 bytes")
        check(tags <= {7, 6} and tags, f"sample tags are the Due's A0/A1 tags {sorted(tags)}")
        check(gaps == 0, "sequence numbers continuous")
        cl.call("stop")
        print("Due daemon smoke: all checks passed")
    finally:
        try: cl.close()
        except Exception: pass
        d.terminate()
        try: d.wait(10)
        except Exception: d.kill()


if __name__ == "__main__":
    main()
