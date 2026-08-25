#!/usr/bin/env python3
"""Measure this board against the design's figures, on any host.

host/ is POSIX-only (termios, fcntl), so none of the project's own
measurement tools run on Windows. This is the same experiments over
pyserial, and it follows the two rules the project paid for:

  * **Judge by byte conservation, never by the underrun counter.** The
    counter reads zero straight through a 0.45-0.85% loss and agreed
    with every wrong theory in objective 0a/0b.
  * **A count taken without a drain is not a measurement.** 55-450 KB
    sits in the host's CDC driver when the writer stops. Stop, wait,
    poll until the device's counter stops moving, and only then compare.

Rates are quoted as the device computes them: RC divides 39 MHz (MCK is
78 MHz here so the ADC clock stays inside its 20 MHz limit).

    python3 tools/bench.py                 # everything
    python3 tools/bench.py --only out-dma
    python3 tools/bench.py --only play --mb 8
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("needs pyserial:  pip install pyserial")

VID, PID_CONSOLE, PID_NATIVE = 0x2341, 0x003D, 0x003E
TIMER_HZ = 39_000_000
DRAIN_POLLS, DRAIN_INTERVAL = 8, 1.0
CHUNK = 256 * 1024

# The design's feed policy, from host/measure.py Feeder: whole 512-byte
# packets only, clock-paced against a 20 KB lead. A short packet fragments
# the device's stream DMA span, and the constant size is what stopped the
# macOS byte loss. Reproduced here so "against the design" means the
# design's feed, not merely its rates.
WRITE_SIZE, LEAD = 512, 20480


def find_ports(console=None, native=None):
    cons = [p for p in list_ports.comports()
            if (p.vid, p.pid) == (VID, PID_CONSOLE)]
    nats = [p for p in list_ports.comports()
            if (p.vid, p.pid) == (VID, PID_NATIVE)]
    # Interfaces 0/1 carry samples, 2/3 carry commands.
    #
    # This sort is right on Windows, where pyserial's LOCATION ends in the
    # interface number ("1-5:x.0", "1-5:x.2"). It is INOPERATIVE on macOS:
    # pyserial takes location from the parent USB device there, so both
    # CDC functions report the same string and this falls through to node
    # name - which happens to give the right answer and would stop doing
    # so if the naming ever changed.
    #
    # host/ports.py:native_order() is the rule, and asks IOKit on macOS
    # for exactly this reason. This tool does not import host/ (that is
    # POSIX-only), so it keeps a lesser version and says so rather than
    # claiming a mechanism it does not have.
    nats.sort(key=lambda p: (p.location or "", p.device))
    return (console or (cons[0].device if cons else None),
            native or (nats[0].device if nats else None))


class Board:
    def __init__(self, console, native):
        self.con = serial.Serial(console, 115200, timeout=0.3)
        time.sleep(2.0)                       # opening it resets the board
        self.con.reset_input_buffer()
        self.native_dev = native

    def cmd(self, text, wait=0.35):
        self.con.write(text.encode())
        self.con.flush()
        time.sleep(wait)
        return self.con.read(60000).decode("utf-8", "replace")

    def play(self):
        out = self.cmd("B", 0.6)
        m = re.search(r"# play: in=(\d+) produced=(\d+) consumed=(\d+) "
                      r"under=(\d+) isr=(\d+) endtx=(\d+) spans=(\d+) "
                      r"partial=(\d+) occmin=(\d+)", out)
        keys = ("in", "produced", "consumed", "under", "isr", "endtx",
                "spans", "partial", "occmin")
        return dict(zip(keys, map(int, m.groups()))) if m else {}

    def bench(self):
        out = self.cmd("B", 0.6)
        m = re.search(r"# bench=(\S+)\s+IN (\d+) B\s+OUT (\d+) B\s+"
                      r"passes=(\d+) arms-in=(\d+) arms-out=(\d+)", out)
        if not m:
            return {}
        return {"mode": m.group(1), "in": int(m.group(2)),
                "out": int(m.group(3)), "passes": int(m.group(4)),
                "arms_in": int(m.group(5)), "arms_out": int(m.group(6))}

    def open_native(self):
        s = serial.Serial(self.native_dev, 115200, timeout=0.5,
                          write_timeout=None)
        s.reset_input_buffer()
        return s

    def stop(self):
        self.cmd("0", 0.4)


def drain(read, label):
    """Poll until the device's counter stops moving, then report.

    A frozen counter that is short is loss; a counter still climbing was
    measured too early, which is the mistake behind every withdrawn
    figure in this project.
    """
    last, stable = None, 0
    for i in range(DRAIN_POLLS):
        time.sleep(DRAIN_INTERVAL)
        now = read()
        if now is not None and now == last:
            stable += 1
            if stable >= 2:
                return now, i + 1
        else:
            stable = 0
        last = now
    print(f"    ! {label} never settled (last={last})")
    return last, DRAIN_POLLS


def settle(nat, secs=0.5):
    """Read and discard for a fixed period, then let the caller start.

    NOT "drain until quiet": during a flood the device never goes quiet,
    so that spins forever - it hung the first version of this.

    The point is that the device begins streaming the moment it takes the
    command, and `board.cmd()` then sleeps and reads the console. Those
    bytes land in the host buffer the whole time, so counting them in
    `total` while leaving that time out of `elapsed` over-reads the rate.
    Measured on Windows: IN read 34.14 MB/s that way against 27.75 with a
    settled start - a 23% over-read, not the few percent it looks like,
    because the buffer is megabytes deep.

    A fixed discard window both empties the backlog and skips the
    startup transient, and it terminates whatever the device is doing.
    """
    end = time.monotonic() + secs
    while time.monotonic() < end:
        nat.read(CHUNK)


def human(n):
    return f"{n/1e6:.2f} MB" if n and n >= 1e6 else f"{n} B"


def note_gran(deficit):
    if deficit and deficit % 512 == 0:
        return ", a multiple of 512 (one packet)"
    if deficit and deficit % 128 == 0:
        return ", a multiple of 128"
    return ""


# --------------------------------------------------------------------------


def test_out_dma(board, mb):
    """OUT throughput and byte conservation: no DAC, no ring, no pacing."""
    print(f"\n=== out-dma: host -> device, {mb} MB, device sinks by DMA ===")
    board.stop()
    board.cmd("T", 0.4)
    nat = board.open_native()
    payload = bytes(CHUNK)
    total = 0
    t0 = time.time()
    for _ in range((mb * 1024 * 1024) // CHUNK):
        total += nat.write(payload) or 0
    elapsed = time.time() - t0
    print(f"  host wrote {human(total)} in {elapsed:.3f} s "
          f"= {total/elapsed/1e6:.2f} MB/s offered")
    got, polls = drain(lambda: board.bench().get("out"), "bench out")
    nat.close()
    board.stop()
    deficit = total - (got or 0)
    pct = 100.0 * deficit / total if total else 0.0
    print(f"  device received {human(got)} after {polls}s drain")
    print(f"  deficit {deficit} B ({pct:.3f}%)" + note_gran(deficit))
    print(f"  delivered {(got or 0)/elapsed/1e6:.2f} MB/s")
    return {"test": "out-dma", "offered": total, "delivered": got,
            "elapsed": elapsed, "deficit": deficit, "pct": pct}


def test_in_dma(board, secs):
    print(f"\n=== in-dma: device -> host, {secs} s, sent by DMA ===")
    board.stop()
    nat = board.open_native()
    board.cmd("G", 0.4)
    settle(nat)
    total = 0
    t0 = time.time()
    while time.time() - t0 < secs:
        total += len(nat.read(CHUNK))
    elapsed = time.time() - t0
    board.stop()
    dev = board.bench()
    nat.close()
    print(f"  host read {human(total)} in {elapsed:.3f} s "
          f"= {total/elapsed/1e6:.2f} MB/s")
    print(f"  device sent {human(dev.get('in', 0))}; the difference was in "
          f"flight or dropped at stop, which this test cannot separate")
    return {"test": "in-dma", "host": total, "device": dev.get("in", 0),
            "elapsed": elapsed, "rate": total / elapsed / 1e6}


def test_duplex(board, secs):
    print(f"\n=== duplex-dma: both directions at once, {secs} s ===")
    board.stop()
    nat = board.open_native()
    board.cmd("Y", 0.4)
    settle(nat)
    payload = bytes(CHUNK)
    counts = {"r": 0, "w": 0}
    stop_at = time.time() + secs

    def reader():
        while time.time() < stop_at:
            counts["r"] += len(nat.read(CHUNK))

    t = threading.Thread(target=reader, daemon=True)
    t0 = time.time()
    t.start()
    while time.time() < stop_at:
        counts["w"] += nat.write(payload) or 0
    t.join(timeout=3.0)
    elapsed = time.time() - t0
    board.stop()
    dev = board.bench()
    nat.close()
    agg = (counts["r"] + counts["w"]) / elapsed / 1e6
    print(f"  host read {human(counts['r'])}, wrote {human(counts['w'])} "
          f"in {elapsed:.3f} s")
    print(f"  aggregate {agg:.2f} MB/s  "
          f"(IN {counts['r']/elapsed/1e6:.2f}, "
          f"OUT {counts['w']/elapsed/1e6:.2f})")
    print(f"  device IN {human(dev.get('in', 0))} "
          f"OUT {human(dev.get('out', 0))}")
    return {"test": "duplex", "agg": agg, "elapsed": elapsed, **counts}


def feed_design(nat, byte_rate, want):
    """Clock-paced 512-byte writes against a 20 KB lead - the design's feed.

    No real-time promotion: host/rt.py is Mach-specific and there is no
    equivalent here, so this is the design's policy on an ordinary thread.
    Whatever jitter that leaves in is the host's, and is part of the result.
    """
    packet = bytes(WRITE_SIZE)
    total = 0
    t0 = time.monotonic()
    while total < want:
        due = int((time.monotonic() - t0) * byte_rate) + LEAD - total
        if due < WRITE_SIZE:
            time.sleep(min(0.005, (WRITE_SIZE - due) / byte_rate))
            continue
        total += nat.write(packet) or 0
    return total


def test_play(board, dac_rc, mb, policy="bulk"):
    """Playback byte conservation - the measurement objective 0h is about."""
    dac_hz = TIMER_HZ // dac_rc
    print(f"\n=== play: RC {dac_rc} = {dac_hz} sps "
          f"({dac_hz*2/1e6:.2f} MB/s), {mb} MB, feed={policy} ===")
    board.stop()
    nat = board.open_native()
    board.cmd(f"={dac_hz},{dac_hz//2},2P", 0.4)
    want = mb * 1024 * 1024
    t0 = time.time()
    if policy == "design":
        total = feed_design(nat, dac_hz * 2, want)
    else:
        payload = bytes(CHUNK)
        total = 0
        for _ in range(want // CHUNK):
            total += nat.write(payload) or 0
    elapsed = time.time() - t0
    settled, polls = drain(lambda: board.play().get("in"), "play in")
    nat.close()
    board.stop()

    # Underruns need a SECOND run, stopped the instant the feed ends.
    #
    # Leaving playback running while the counters drain adds a tail: the
    # device empties the ring and then repeats buffers until told to stop,
    # which is ~0.46 s of underrunning at every rate. That reads as 4% at
    # 200 ksps and 24% at 1.39 Msps and is entirely the harness. But a
    # prompt stop discards what is in flight, so it cannot measure bytes.
    # The two questions need two runs; conflating them reports a fault
    # that is not there.
    board.cmd(f"={dac_hz},{dac_hz//2},2P", 0.4)
    nat = board.open_native()
    if policy == "design":
        feed_design(nat, dac_hz * 2, want)
    else:
        payload = bytes(CHUNK)
        for _ in range(want // CHUNK):
            nat.write(payload)
    board.con.write(b"0")
    board.con.flush()
    time.sleep(0.4)
    st = board.play()
    nat.close()
    board.stop()
    deficit = total - (settled or 0)
    pct = 100.0 * deficit / total if total else 0.0
    print(f"  host wrote {human(total)} in {elapsed:.3f} s "
          f"= {total/elapsed/1e6:.2f} MB/s")
    print(f"  device in={settled} after {polls}s drain (frozen)")
    print(f"  deficit {deficit} B ({pct:.3f}%)" + note_gran(deficit))
    print(f"  under={st.get('under')} partial={st.get('partial')} "
          f"occmin={st.get('occmin')} endtx={st.get('endtx')}  "
          f"(second run, stopped promptly)")
    return {"test": "play", "policy": policy,
            "rc": dac_rc, "sps": dac_hz, "written": total,
            "received": settled, "deficit": deficit, "pct": pct,
            "elapsed": elapsed, "under": st.get("under"),
            "partial": st.get("partial"), "occmin": st.get("occmin")}


LADDER = (195, 130, 98, 65, 44, 39, 32, 28)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--console")
    ap.add_argument("--native")
    ap.add_argument("--mb", type=int, default=8)
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--rc", type=int, help="one RC only, for --only play")
    ap.add_argument("--only", choices=["out-dma", "in-dma", "duplex", "play"])
    # The design's feed is the default. `bulk` free-runs 256 KB writes,
    # which is the policy macOS is measured to lose 0.45-0.85% on, and
    # this tool prints the shortfall as the DEVICE's deficit - so the
    # wrong default makes a host defect read as a board defect on the
    # platform that has it.
    ap.add_argument("--policy", choices=["bulk", "design"], default="design",
                    help="design = the Feeder policy (512 B, paced); "
                         "bulk = 256 KB free-run, which loses bytes on macOS")
    args = ap.parse_args()

    console, native = find_ports(args.console, args.native)
    if not console or not native:
        sys.exit(f"ports not found (console={console} native={native})")
    print(f"console {console}   native {native}")
    board = Board(console, native)

    results = []
    try:
        if args.only in (None, "out-dma"):
            results.append(test_out_dma(board, args.mb))
        if args.only in (None, "in-dma"):
            results.append(test_in_dma(board, args.secs))
        if args.only in (None, "duplex"):
            results.append(test_duplex(board, args.secs))
        if args.only in (None, "play"):
            for rc in ([args.rc] if args.rc else LADDER):
                results.append(test_play(board, rc, args.mb, args.policy))
    finally:
        board.stop()
        board.con.close()

    print("\n=== summary ===")
    for r in results:
        if r["test"] == "play":
            print(f"  play[{r['policy'][:3]}] RC {r['rc']:>3} {r['sps']:>7} sps  "
                  f"deficit {r['deficit']:>9} B ({r['pct']:.3f}%)  "
                  f"under={r['under']} partial={r['partial']}")
        elif r["test"] == "out-dma":
            print(f"  out-dma  {r['offered']/r['elapsed']/1e6:.2f} MB/s "
                  f"offered, deficit {r['deficit']} B ({r['pct']:.3f}%)")
        elif r["test"] == "in-dma":
            print(f"  in-dma   {r['rate']:.2f} MB/s")
        elif r["test"] == "duplex":
            print(f"  duplex   {r['agg']:.2f} MB/s aggregate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
