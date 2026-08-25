#!/usr/bin/env python3
"""Capture and full-loop validation, on any host.

tools/bench.py measures bytes. This measures the *signal*: frame
integrity, sequence continuity, overruns, and - for the full loop - the
tone that came back through the DAC0 -> A0 jumper.

Byte conservation says nothing arrived corrupted. It does not say the
waveform is right: a run can conserve every byte and still be built from
repeated buffers. Only the captured tone settles that, which is why this
exists alongside the byte tests rather than instead of them.

    python3 tools/loop.py --mode capture --secs 5
    python3 tools/loop.py --mode loop --sps 453488 --secs 5
    python3 tools/loop.py --mode loop --nch 2      # A1 should stay flat

Needs the DAC0 -> A0 jumper for --mode loop. Without it A0 reads a
floating pin and the tone amplitude collapses; that is reported as a
missing jumper rather than as a failure, because it is not one.
"""
from __future__ import annotations

import argparse
import math
import os
import struct
import sys
import threading
import time
import zlib
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench                                                # noqa: E402

HDR_FMT = "<4sBBHIIIIII"
HDR_LEN = struct.calcsize(HDR_FMT)          # 32
FRAME_SAMPLES = 2032
FRAME_BYTES = HDR_LEN + FRAME_SAMPLES * 2   # 4096
MAGIC = b"DUE0"
FLAG_OVERRUN = 1 << 0

CH_A0, CH_A1 = 7, 6                         # ADC channel indices, not A-labels

# The DAC's span reaches the ADC at about 0.67 codes per DAC code, so a
# full-scale sine (amplitude 2047) arrives at ~1371. The design holds
# this to +/-2 in every window.
EXPECT_AMPL = 1371.0


def goertzel(samples, fs, ftarget):
    """Single-bin DFT magnitude, normalised to sample count."""
    n = len(samples)
    if n == 0 or fs <= 0:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * ftarget / fs)
    s1 = s2 = 0.0
    mean = sum(samples) / n
    for x in samples:
        s0 = (x - mean) + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(power, 0.0)) * 2.0 / n


def build_waveform(tone_hz, dac_total_sps, cycles=20):
    """Whole cycles of a full-scale sine, every sample tagged for DAC0."""
    per_cycle = int(round(dac_total_sps / tone_hz))
    out = bytearray()
    for i in range(per_cycle * cycles):
        code = int(round(2047.5 + 2047.0 * math.sin(2.0 * math.pi * i / per_cycle)))
        out += struct.pack("<H", max(0, min(4095, code)) & 0xFFF)
    return bytes(out), dac_total_sps / per_cycle


class Stats:
    def __init__(self):
        self.frames = self.bad_crc = self.bad_magic = 0
        self.seq_gaps = self.dropped = self.overrun_frames = 0
        self.resyncs = self.inconsistent = 0
        self.max_overrun = 0
        self.first_seq = self.last_seq = None
        self.rate = self.chmask = None
        self.by_ch = {}
        self.payload_bytes = 0
        self.capped = False
        self.keep_samples = KEEP_SAMPLES


# Per-channel sample cap for the SIGNAL analysis. Frame, CRC and
# sequence counting always cover the whole buffer; only the Goertzel and
# the range/mean are capped, because they are O(n) in Python and a 5 s
# run at 453 ksps is 2.3 M samples per channel.
#
# It used to be silent, which is worse than the cost it saves: a 5 s run
# analysed 0.88 s of tone and a dropout at t=3 s reported clean. It now
# says what it looked at.
KEEP_SAMPLES = 400000


def deframe(buf, keep_samples=KEEP_SAMPLES):
    """Scan for magic, verify the header CRC, then take the payload.

    The CRC is checked rather than the magic trusted: a false magic
    inside payload data is likely at these volumes, and a frame accepted
    on a coincidence would corrupt every count downstream.
    """
    st = Stats()
    pos, n, seq_prev, shape0 = 0, len(buf), None, None
    keep = {}
    while True:
        i = buf.find(MAGIC, pos)
        if i < 0 or n - i < HDR_LEN:
            break
        hdr = bytes(buf[i:i + HDR_LEN])
        (_m, ver, flags, chmask, seq, rate, ts,
         overruns, consumed, crc) = struct.unpack(HDR_FMT, hdr)
        if zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF != crc:
            st.bad_crc += 1
            pos = i + 1                       # skip one byte, not one frame
            continue
        if n - i < FRAME_BYTES:
            break
        body = bytes(buf[i + HDR_LEN:i + FRAME_BYTES])
        pos = i + FRAME_BYTES

        shape = (ver, rate, chmask)
        if st.frames == 0:
            st.first_seq, shape0 = seq, shape
            st.rate, st.chmask = rate, chmask
        elif shape != shape0:
            st.inconsistent += 1
        st.frames += 1
        st.payload_bytes += len(body)
        st.last_seq = seq
        st.max_overrun = max(st.max_overrun, overruns)
        if flags & FLAG_OVERRUN:
            st.overrun_frames += 1
        if seq_prev is not None and seq != seq_prev + 1:
            st.seq_gaps += 1
            st.dropped += (seq - seq_prev - 1) & 0xFFFFFFFF
        seq_prev = seq

        vals = array("H")
        vals.frombytes(body)
        nch = max(1, bin(chmask).count("1"))
        tags = [(v >> 12) & 0xF for v in vals[:nch]]
        if len(set(tags)) == nch:
            for j, tag in enumerate(tags):
                acc = keep.setdefault(tag, [])
                if len(acc) < keep_samples:
                    acc.extend(v & 0x0FFF for v in vals[j::nch])
        else:
            st.resyncs += 1
    st.by_ch = keep
    st.capped = any(len(v) >= keep_samples for v in keep.values())
    st.keep_samples = keep_samples
    return st


def report(st, secs, label):
    print(f"\n--- {label} ---")
    if not st.frames:
        print("  NO FRAMES DECODED")
        return
    expected = (st.last_seq - st.first_seq + 1) & 0xFFFFFFFF
    print(f"  frames {st.frames}  seq {st.first_seq}..{st.last_seq} "
          f"(expected {expected})")
    print(f"  seq_gaps {st.seq_gaps}  dropped {st.dropped}  "
          f"bad_crc {st.bad_crc}  resyncs {st.resyncs}  "
          f"inconsistent {st.inconsistent}")
    print(f"  overrun frames {st.overrun_frames}  overrun_count max "
          f"{st.max_overrun}")
    print(f"  declared rate {st.rate} Hz/ch  chmask 0x{st.chmask:x}  "
          f"payload {st.payload_bytes/1e6:.2f} MB "
          f"({st.payload_bytes/secs/1e6:.2f} MB/s)")
    if st.capped:
        span = st.keep_samples / st.rate if st.rate else 0.0
        print(f"  ! signal analysis capped at {st.keep_samples} samples/ch "
              f"= {span:.2f} s of {secs:.2f} s. Frames, CRC and sequence "
              f"cover the whole run; the tone does not.")


def run_capture(board, secs):
    """Capture-only at the maximum in-spec rate.

    `=<dac>,<adc>,<nch>` applies to L/P/t, not to the numbered stream
    commands, so `5` is sent bare: it selects 453,488 sps/ch on two
    channels itself. Sending the `=` prefix first is what made an earlier
    version read an empty buffer and report no frames at all.
    """
    board.stop()
    nat = board.open_native()
    banner = board.cmd("5", 0.5)
    print(f"\n=== capture: {secs} s ===")
    for line in banner.splitlines():
        if line.startswith("#"):
            print(f"  {line}")
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < secs:
        buf += nat.read(bench.CHUNK)
    secs_real = time.time() - t0
    board.stop()
    nat.close()
    print(f"  read {len(buf)/1e6:.2f} MB")
    st = deframe(buf)
    report(st, secs_real, "capture")
    return st


def feed_wave(nat, wave, byte_rate, stop_evt):
    """The design's feed - 512 B packets against a 20 KB lead - cycling
    the waveform. Returns bytes written."""
    total, pos = 0, 0
    t0 = time.monotonic()
    while not stop_evt.is_set():
        due = int((time.monotonic() - t0) * byte_rate) + bench.LEAD - total
        if due < bench.WRITE_SIZE:
            time.sleep(min(0.005, (bench.WRITE_SIZE - due) / byte_rate))
            continue
        if pos + bench.WRITE_SIZE > len(wave):
            chunk = wave[pos:] + wave[:bench.WRITE_SIZE - (len(wave) - pos)]
            pos = bench.WRITE_SIZE - (len(wave) - pos)
        else:
            chunk = wave[pos:pos + bench.WRITE_SIZE]
            pos += bench.WRITE_SIZE
        total += nat.write(chunk) or 0
    return total


def run_loop(board, sps, secs, nch, tone_hz):
    print(f"\n=== loop: HOST -> DAC -> jumper -> ADC -> HOST   "
          f"{sps} sps each way, {nch} ch, {secs} s ===")
    wave, tone = build_waveform(tone_hz, sps)
    print(f"  waveform {len(wave)} B, DAC0 tone {tone:.2f} Hz")
    board.stop()
    nat = board.open_native()
    board.cmd(f"={sps},{sps},{nch}L", 0.4)

    buf = bytearray()
    stop_evt = threading.Event()
    written = {}

    def feeder():
        written["n"] = feed_wave(nat, wave, sps * 2, stop_evt)

    th = threading.Thread(target=feeder, daemon=True)
    t0 = time.time()
    th.start()
    while time.time() - t0 < secs:
        buf += nat.read(bench.CHUNK)
    stop_evt.set()
    th.join(timeout=3.0)
    secs_real = time.time() - t0
    board.con.write(b"0")
    board.con.flush()
    time.sleep(0.4)
    play = board.play()
    nat.close()
    board.stop()

    st = deframe(buf)
    report(st, secs_real, f"loop {sps} sps")
    print(f"  host fed {written.get('n', 0)/1e6:.2f} MB; device "
          f"under={play.get('under')} partial={play.get('partial')} "
          f"occmin={play.get('occmin')}")

    fs = st.rate or sps
    print(f"  Goertzel at {tone:.2f} Hz (fs = {fs} Hz/ch)")
    for ch, name in ((CH_A0, "A0"), (CH_A1, "A1")):
        s = st.by_ch.get(ch)
        if not s:
            continue
        # Skip the head: the first frames carry the ring still filling.
        # Then trim to a whole number of tone cycles - a trailing partial
        # cycle leaks into the bin and shifts the answer by a few codes,
        # which is enough to matter against a +/-2 specification.
        s = s[len(s) // 10:]
        per_cycle = fs / tone
        s = s[:int(len(s) / per_cycle) * int(round(per_cycle))]
        amp = goertzel(s, fs, tone)
        lo, hi, mean = min(s), max(s), sum(s) / len(s)
        mark = ""
        if ch == CH_A0:
            mark = ("  <-- design: 1371 +/- 2"
                    if abs(amp - EXPECT_AMPL) <= 2 else
                    f"  <-- design 1371, off by {amp - EXPECT_AMPL:+.1f}")
        print(f"    {name} (ch{ch}) n={len(s)} amplitude {amp:8.1f} codes"
              f"   range {lo}..{hi} mean {mean:.0f}{mark}")

    a0 = st.by_ch.get(CH_A0, [])
    if a0:
        amp = goertzel(a0[len(a0)//10:], fs, tone)
        if amp < 100:
            print("  ! amplitude far below 1371: check the DAC0 -> A0 jumper. "
                  "A floating A0 reads noise and looks exactly like this.")
    # Return the tone actually emitted, not the one asked for. See main().
    return st, tone


def windows(st, fs, tone, ms=40.0, settle=0.1):
    """Amplitude per window, so a tone that is right on average but
    intermittent cannot pass. The design holds every window to +/-2.

    The head is discarded first. The run begins with the playback ring
    still filling, so the opening window legitimately carries no tone;
    counting it reports a spread of ~1370 codes and hides whether the
    settled part is steady. The design does the same thing with
    settle_us in host/measure.py - this is that, not a fudge.
    """
    # The window must hold a WHOLE number of tone cycles. 8192 samples at
    # 453,488 Hz is 18.08 cycles of a 1001 Hz tone, and the leftover
    # fraction leaks differently in every window - which shows up as a
    # +/-5 code ripple that is the measurement, not the signal. Round the
    # requested length down to a cycle boundary.
    s = st.by_ch.get(CH_A0, [])
    s = s[int(len(s) * settle):]
    per_cycle = fs / tone
    cycles = max(1, int((ms / 1000.0) * fs / per_cycle))
    size = int(round(cycles * per_cycle))
    return [goertzel(s[i:i + size], fs, tone)
            for i in range(0, len(s) - size, size)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--console")
    ap.add_argument("--native")
    ap.add_argument("--mode", choices=["capture", "loop", "both"],
                    default="both")
    ap.add_argument("--sps", type=int, default=453488)
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--nch", type=int, default=1)
    ap.add_argument("--tone", type=float, default=1000.0)
    args = ap.parse_args()

    console, native = bench.find_ports(args.console, args.native)
    if not console or not native:
        sys.exit(f"ports not found (console={console} native={native})")
    print(f"console {console}   native {native}")
    board = bench.Board(console, native)
    try:
        if args.mode in ("capture", "both"):
            run_capture(board, args.secs)
        if args.mode in ("loop", "both"):
            st, tone = run_loop(board, args.sps, args.secs, args.nch,
                                args.tone)
            fs = st.rate or args.sps
            # The REAL tone, not args.tone.
            #
            # build_waveform picks a whole-sample period, so what the DAC
            # actually emits is sps / round(sps / tone). At 200,000 sps
            # that is exactly 1000 Hz and the distinction is invisible;
            # at 453,488 it is 1001.077 Hz, and analysing at 1000.0 makes
            # the window a non-integer number of real cycles - precisely
            # the leakage the comment in windows() says it exists to
            # prevent. It read as the per-window level sitting ~4 codes
            # under the whole-run aggregate, which was written up as
            # possible ADC track-and-hold settling. It was this.
            w = windows(st, fs, tone)
            if w:
                print(f"  per-window amplitude over {len(w)} windows "
                      f"(head discarded): min {min(w):.1f} max {max(w):.1f} "
                      f"spread {max(w)-min(w):.1f} codes")
                off = [f"{a:.1f}" for a in w if abs(a - EXPECT_AMPL) > 2]
                print(f"  windows outside 1371 +/- 2: {len(off)}"
                      + (f" -> {', '.join(off[:8])}" if off else ""))
    finally:
        board.stop()
        board.con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
