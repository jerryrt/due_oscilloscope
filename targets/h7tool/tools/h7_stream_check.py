#!/usr/bin/env python3
"""Receive the H7 test stream (frame version 4) and check it.

Checks per frame: magic, version 4, header CRC (zlib crc32 over the first 28
bytes), sequence continuity, and the constant payload (sample i == i). A
device that restarts a run starts again at seq 0, which is counted as a run
start, not a gap. `analyse()` is separate from the port so the tests can break
it on purpose.

    h7_stream_check.py [--seconds 10] [--port /dev/ttyACM3]
"""
import argparse, array, operator, math, glob, os, struct, sys, time, zlib

FRAME = 4096
HDR = 32
SAMPLES = (FRAME - HDR) // 2
MAGIC = b"DUE0"
PAYLOAD = struct.pack("<%dH" % SAMPLES, *range(SAMPLES))


def analyse(data, expect_version=4, pattern=True):
    """Return a dict of counts for a received byte string."""
    r = dict(bytes=len(data), frames=0, bad_crc=0, bad_version=0, gaps=0, lost=0,
             bad_payload=0, resyncs=0, run_starts=0, skipped=0)
    pos, last = 0, None
    while pos + FRAME <= len(data):
        h = data[pos:pos + HDR]
        ok = h[:4] == MAGIC
        if ok:
            magic, ver, flags, mask, seq, rate, ts, ovr, pc, crc = struct.unpack("<4sBBHIIIIII", h)
            ok = zlib.crc32(h[:28]) & 0xFFFFFFFF == crc
            if not ok:
                r["bad_crc"] += 1
        if not ok:                                   # lose sync: look for the next magic
            nxt = data.find(MAGIC, pos + 1)
            if nxt < 0:
                r["skipped"] += len(data) - pos
                break
            r["resyncs"] += 1; r["skipped"] += nxt - pos; pos = nxt; last = None
            continue
        if ver != expect_version:
            r["bad_version"] += 1
        if last is not None:
            if seq == 0:
                r["run_starts"] += 1
            elif seq != last + 1:
                r["gaps"] += 1; r["lost"] += (seq - last - 1) & 0xFFFFFFFF
        last = seq
        if pattern:
            if data[pos + HDR:pos + FRAME] != PAYLOAD:
                r["bad_payload"] += 1
        else:
            w = array.array("H"); w.frombytes(data[pos + HDR:pos + FRAME])
            k = bin(mask & 0xFF).count("1") or 1
            n = len(w) // k                           # planar payload: one block per channel
            chans = [i for i in range(8) if mask >> i & 1] or [0]
            for j, ch in enumerate(chans):
                seg = w[j * n:(j + 1) * n]
                c = r.setdefault("ch", {}).setdefault(ch, dict(lo=65535, hi=0, sum=0, sumsq=0, n=0))
                c["lo"] = min(c["lo"], min(seg)); c["hi"] = max(c["hi"], max(seg))
                c["sum"] += sum(seg); c["sumsq"] += sum(map(operator.mul, seg, seg)); c["n"] += len(seg)
            r["samples"] = r.get("samples", 0) + n    # per channel
            r["rate_hz"] = rate
            r["flag_overrun"] = r.get("flag_overrun", 0) + (flags & 1)
        r["frames"] += 1
        pos += FRAME
    r["clean"] = (r["frames"] > 0 and not (r["bad_crc"] or r["bad_version"] or r["gaps"]
                  or r["bad_payload"] or r["resyncs"]))
    return r


def rate_ok(samples, rate_hz, seconds, tol=0.01):
    """The header's sample_rate_hz must be what arrived: samples / seconds within tol.
    A converter that skips triggers delivers valid frames at the wrong rate."""
    return abs(samples / (rate_hz * seconds) - 1) <= tol


def find_port():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            if (open(d + "/idVendor").read().strip(), open(d + "/idProduct").read().strip()) == ("1209", "0001"):
                t = glob.glob(os.path.basename(d) + ":1.0/tty/*", root_dir=d) or \
                    glob.glob(d + "/" + os.path.basename(d) + ":1.0/tty/*")
                if t:
                    return "/dev/" + os.path.basename(t[0])
        except OSError:
            pass
    sys.exit("no 1209:0001 stream port")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--port")
    ap.add_argument("--adc", action="store_true", help="payload is converter data, not the test pattern")
    a = ap.parse_args()
    import serial
    port = a.port or find_port()
    s = serial.Serial(port, 115200, timeout=0.2)     # opening raises DTR: that starts the stream
    chunks, n, t0 = [], 0, time.monotonic()
    while time.monotonic() - t0 < a.seconds:
        b = os.read(s.fd, 1 << 20)
        if b:
            chunks.append(b); n += len(b)
    dt = time.monotonic() - t0
    s.close()
    r = analyse(b"".join(chunks), pattern=not a.adc)
    if a.adc and r.get("samples"):
        for ch, c in sorted(r.pop("ch").items()):
            m = c["sum"] / c["n"]
            r[f"ch{ch}"] = f"mean {m:.1f} std {math.sqrt(max(c['sumsq'] / c['n'] - m * m, 0)):.1f} lo {c['lo']} hi {c['hi']}"
        r["expected_samples"] = int(r["rate_hz"] * dt)
        r["rate_ok"] = rate_ok(r["samples"], r["rate_hz"], dt)
        r["clean"] = r["clean"] and r["rate_ok"]
    print(f"{port}: {n} bytes in {dt:.2f} s = {n / dt / 1e6:.2f} MB/s")
    print(" ".join(f"{k}={v}" for k, v in r.items()))
    sys.exit(0 if r["clean"] else 1)


if __name__ == "__main__":
    main()
