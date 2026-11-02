"""Host-fed playback check for image10+: stream a 1 kHz sine to the H7 generator over the stream
port while capturing VOUT on CH2 (VOUT wired to CH2, mask 2), and report the device counters.
Run from anywhere; needs sudo -n for the vendor requests.  stops the writer
between a and b seconds (an underrun control)."""
import os, sys, time, struct, math, array, serial, subprocess, threading, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h7_stream_check as c
PROBE = ["sudo", "-n", "python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "h7_usb_probe.py")]
def run(p, check=True): return subprocess.run(PROBE + p.split(), capture_output=True, text=True, check=check).stdout
def samples(data):
    out = array.array("H"); pos = data.find(b"DUE0")
    while pos >= 0 and pos + 4096 <= len(data):
        h = data[pos:pos + 32]
        if zlib.crc32(h[:28]) & 0xFFFFFFFF != struct.unpack("<I", h[28:])[0]: pos = data.find(b"DUE0", pos + 1); continue
        out.frombytes(data[pos + 32:pos + 4096]); pos += 4096
    return out
def sine(n, f, fs, amp, center=2036):
    return struct.pack("<%dH" % n, *[int(round(center + amp * math.sin(2 * math.pi * f * i / fs))) for i in range(n)])
def session(wavebytes, seconds, gap=None, period=800):
    run("wave 0 0"); run("gcenter 2036"); run(f"gperiod {period}"); run("chan 2"); run("rate 2500000")
    s = serial.Serial(c.find_port(), 115200, timeout=0.2); time.sleep(0.5)
    run("pstart 4"); stop = threading.Event(); wrote = [0]
    def writer():
        t0 = time.time(); i = 0
        while not stop.is_set():
            if gap and gap[0] < time.time() - t0 < gap[1]: time.sleep(0.01); continue
            try: os.write(s.fd, wavebytes); wrote[0] += len(wavebytes)
            except (BlockingIOError, OSError): time.sleep(0.001)
    # blocking writes: make the fd blocking for the writer
    os.set_blocking(s.fd, True)
    th = threading.Thread(target=writer, daemon=True); th.start()
    buf = bytearray(); t0 = time.time()
    while time.time() - t0 < seconds:
        try: buf += os.read(s.fd, 1 << 20)
        except OSError: time.sleep(0.001)
    stop.set(); th.join(15)
    time.sleep(0.2); st = run("play"); run("pstop"); end = run("play"); s.close()
    return bytes(buf), wrote[0], st.strip(), end.strip()
if __name__ == "__main__":
    fs = 200e6 / 800
    wav = sine(32000, 1000, fs, 300)
    buf, wrote, st, end = session(wav, 5)
    print("host wrote", wrote, "bytes;", st)
    x = samples(buf); x = x[len(x) // 4:]
    ZERO, CPV = 32750.0, 2301.0
    v = [(a - ZERO) / CPV for a in x]; n = len(v); f = 1000.0; fsa = 2.5e6
    re_ = sum(v[i] * math.cos(2 * math.pi * f * i / fsa) for i in range(0, n, 1)) * 2 / n
    im_ = sum(v[i] * math.sin(2 * math.pi * f * i / fsa) for i in range(0, n, 1)) * 2 / n
    amp = math.hypot(re_, im_); ph = math.atan2(im_, re_); mean = sum(v) / n
    res = [v[i] - mean - (re_ * math.cos(2 * math.pi * f * i / fsa) + im_ * math.sin(2 * math.pi * f * i / fsa)) for i in range(n)]
    rms = math.sqrt(sum(r * r for r in res) / n)
    print(f"CH2: {n} samples, fundamental {amp:.3f} V (ideal {300 * 5.983e-3:.3f}), mean {mean:+.3f} V, residual rms {rms * 1000:.1f} mV")
