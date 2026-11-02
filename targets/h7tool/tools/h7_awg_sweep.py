"""AWG performance sweep for the H7 generator (image11+). VOUT must be wired to CH2 and CH2 is the
instrument (2 Msps, gain 0, DC). Everything played passes h7_awg.check_codes. Run with the venv
that has numpy and pyserial (.venv-gui). The observer limits what this can see: CH2's own bandwidth
and noise are in every number, and it samples at 2 Msps (Nyquist 1 MHz).

    h7_awg_sweep.py ladder     # update-rate ladder at a fixed 10 kHz sine
    h7_awg_sweep.py bandwidth  # frequency sweep at 5 MS/s update
    h7_awg_sweep.py square     # edge time at 5 MS/s update
"""
import array, os, struct, subprocess, sys, threading, time, zlib
import numpy as np
import serial
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import h7_awg as awg
import h7_stream_check as chk
import h7_ets as ets

PROBE = ["sudo", "-n", "python3", os.path.join(HERE, "h7_usb_probe.py")]
ADC_FS = 2.0e6      # observer rate: 0.8 of the 2.5 Msps cliff, never at it (docs/10)
ZERO, CPV = 32750.0, 2301.0       # CH2 zero code and codes per volt at gain 0 (docs/12)


WRITER = ("import ctypes, os, sys\nctypes.CDLL(None).prctl(1, 9)   # PR_SET_PDEATHSIG = SIGKILL: never outlive the harness\nfd = os.open(sys.argv[1], os.O_WRONLY | os.O_NOCTTY)\n"
          "buf = open(sys.argv[2], 'rb').read()\n"
          "while True:\n    os.write(fd, buf)\n")


def start_writer(port, buf):
    """The writer is its own process: a writer thread in the reader's process fights it for the GIL,
    the reader falls behind, and the acquisition ring overflows (seen: 480 frames lost at once)."""
    import tempfile
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".bin"); f.write(buf); f.close()
    return subprocess.Popen([sys.executable, "-I", "-c", WRITER, port, f.name]), f.name


def stop_writer(p, name):
    p.kill(); p.wait(); os.unlink(name)


def probe(cmd):
    return subprocess.run(PROBE + cmd.split(), capture_output=True, text=True, check=True).stdout


def counters():
    return dict(kv.split("=") for kv in probe("play").split())


def codes_of(data):
    out = array.array("H"); pos = data.find(b"DUE0")
    while pos >= 0 and pos + 4096 <= len(data):
        h = data[pos:pos + 32]
        if zlib.crc32(h[:28]) & 0xFFFFFFFF != struct.unpack("<I", h[28:])[0]:
            pos = data.find(b"DUE0", pos + 1); continue
        out.frombytes(data[pos + 32:pos + 4096]); pos += 4096
    return np.frombuffer(out, dtype=np.uint16).astype(np.float64)


def play(buf, fs, warm=1.5, seconds=2.0, aperiod=None, raw=False):
    """Play `buf` repeatedly at update rate fs; return (captured CH2 volts, device counters, rate ratio).

    The acquisition stream starts the moment the port opens, so it is drained by a reader thread from
    then on: a host that does not read (while sudo probes run) lets the tty fill, the host stops polling
    the IN endpoint, and the device ring overflows - the intermittent bad rows this tool used to give.
    """
    probe("wave 0 0"); probe("gcenter 2036"); probe(f"gperiod {awg.period_ticks(fs)}")
    probe("chan 2"); probe(f"aperiod {aperiod or int(round(200e6 / ADC_FS))}")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
    data = bytearray(); stop = threading.Event()
    import select
    def reader():
        while not stop.is_set():
            if select.select([s.fd], [], [], 0.05)[0]:
                try: data.extend(os.read(s.fd, 1 << 20))
                except OSError: pass
    rt = threading.Thread(target=reader, daemon=True); rt.start()
    time.sleep(0.3); probe("pstart 2")
    wp, wname = start_writer(s.name, buf)
    time.sleep(warm); start = len(data); c1 = (int(counters()["consumed"]), time.time())
    time.sleep(seconds)
    ctr = counters(); c2 = (int(ctr["consumed"]), time.time())     # before the writer stops: the drain is not an underrun
    a = dict(kv.split("=") for kv in probe("acq").split())
    ctr["acq_tc_missed"] = a["tc_missed"]; ctr["acq_lost"] = a["lost"]; ctr["acq_ovr"] = a["adc_ovr"]; ctr["acq_sent"] = a["sent"]; ctr["acq_frames"] = a["frames_done"]
    ctr["stall"] = {k: a[k] for k in ("dma_err", "dma_err_frame", "stall", "stall_lisr", "stall_cr", "stall_ndtr", "stall_isr", "stall_adccr")}
    stop_writer(wp, wname)
    try: probe("pstop")
    except subprocess.CalledProcessError:
        print("pstop failed; device state:", ctr, flush=True); stop.set(); s.close(); raise
    stop.set(); rt.join(2); s.close()
    ratio = ((c2[0] - c1[0]) & 0xFFFFFFFF) / (c2[1] - c1[1]) / fs
    if raw:
        return bytes(data[start:]), ctr, ratio
    x = codes_of(bytes(data[start:]))
    ctr["capture_samples"] = len(x); ctr["expected_samples"] = int(ADC_FS * seconds)
    return (x - ZERO) / CPV, ctr, ratio


def fit(v, f0, harmonics=5):
    """Least-squares fit of f0 and its harmonics (coherent: both clocks are the same 200 MHz)."""
    n = min(len(v), 1_000_000); v = v[:n]; t = np.arange(n) / ADC_FS
    cols = [np.ones(n)]; ks = []
    for k in range(1, harmonics + 1):
        if k * f0 < ADC_FS / 2:
            cols += [np.cos(2 * np.pi * k * f0 * t), np.sin(2 * np.pi * k * f0 * t)]; ks.append(k)
    A = np.stack(cols, 1); coef, *_ = np.linalg.lstsq(A, v, rcond=None)
    amps = [np.hypot(coef[1 + 2 * i], coef[2 + 2 * i]) for i in range(len(ks))]
    resid = v - A @ coef
    thd = np.sqrt(sum(a * a for a in amps[1:])) / amps[0] if len(amps) > 1 else float("nan")
    return dict(amp=amps[0], mean=coef[0], thd=thd, resid_mv=1000 * float(np.std(resid)))


def feed_only(fs, seconds=3.0):
    """Playback with acquisition off (DTR dropped after open): is the USB feed itself sustaining fs?"""
    buf = awg.sine(round(fs), round(fs) / 500, 100)
    probe("wave 0 0"); probe("gcenter 2036"); probe(f"gperiod {awg.period_ticks(fs)}")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, True)
    s.dtr = False; time.sleep(0.5); probe("pstart 2")
    wp, wname = start_writer(s.name, buf)
    time.sleep(1.0); c1 = (int(counters()["consumed"]), time.time()); time.sleep(seconds); ctr = counters(); c2 = (int(ctr["consumed"]), time.time())
    stop_writer(wp, wname); probe("pstop"); s.close()
    return ctr, ((c2[0] - c1[0]) & 0xFFFFFFFF) / (c2[1] - c1[1]) / fs


def feed():
    print("playback only (acquisition off): does the USB feed sustain the update rate?")
    for fs in (2_000_000, 4_000_000, 4_545_454, 5_000_000):
        try: p = awg.period_ticks(fs)
        except ValueError: fs = 200_000_000 / round(200_000_000 / fs); p = round(200_000_000 / fs)
        buf_fs = 200_000_000 / p
        ctr, r = feed_only(buf_fs)
        print(f"{buf_fs/1e6:6.3f} MS/s: rate ratio {r:.5f}, underruns {ctr['underruns']}, resumes {ctr['resumes']}, min_occ {ctr['min_occ']}, short {ctr['short']}", flush=True)


_warmed = []


def one(fs):
    if not _warmed: warmup(); _warmed.append(1)
    v, c, r = play(awg.sine(fs, fs / 500, 300), fs)
    print(f"{fs/1e6:.2f} MS/s: rate ratio {r:.5f}, underruns {c['underruns']}, capture {c['capture_samples']}/{c['expected_samples']}, acq frames {c['acq_frames']} sent {c['acq_sent']} lost {c['acq_lost']} missed {c['acq_tc_missed']} ovr {c['acq_ovr']}" + (f"  STALL {c['stall']}" if c['stall']['stall'] != '0' or c['stall']['dma_err'] != '0x0' else ""))


def settle(quiet=12.0, limit=120.0):
    """After enumeration something on this host (ModemManager, probably) opens the new ports for a while;
    that starts the acquisition and can overlap a run. Wait until the acquisition start counter has not
    moved for `quiet` seconds."""
    t0 = time.time(); last = None; t_last = time.time()
    while time.time() - t0 < limit:
        st = dict(kv.split("=") for kv in probe("acq").split())["starts"]
        if st != last: last, t_last = st, time.time()
        if time.time() - t_last >= quiet: return int(st)
        time.sleep(1.0)
    raise RuntimeError("the unit never went quiet")


def ets_run(kind, p_a=None, g=None, seconds=4.0):
    """One ETS capture at 5 MS/s update. Returns (wave volts per bin, counts, plan, ctr, expected volts per bin)."""
    fs, p_d = 5_000_000, 40
    if kind == "square": ppc, buf, expect = 50, awg.square(fs, fs / 50, 150), None
    else:                ppc, buf, expect = 500, awg.sine(fs, fs / 500, 300), None
    pl = ets.plan(p_d, ppc, g=g)
    if p_a: pl["p_a"] = p_a
    data, ctr, ratio = play(buf, fs, warm=1.5, seconds=seconds, aperiod=pl["p_a"], raw=True)
    v = (ets.gapless_samples(data) - ZERO) / CPV
    wave, counts = ets.reconstruct(v, pl["p_a"], pl["W"], pl["g"])
    codes = np.frombuffer(buf, dtype="<u2")[:ppc].astype(float)               # one cycle of DAC codes
    idx = (np.arange(pl["bins"]) * pl["g"] // p_d) % ppc
    expected = (codes[idx] - awg.ZERO_CODE) * awg.MV_PER_CODE / 1000
    return wave, counts, pl, ctr, expected, len(v)


def edge_metrics(wave, g):
    lo, hi = np.nanpercentile(wave, 5), np.nanpercentile(wave, 95); span = hi - lo
    t10, t90 = lo + 0.1 * span, lo + 0.9 * span
    up = [i for i in range(1, len(wave)) if wave[i - 1] < t10 <= wave[i]]
    out = {}
    if up:
        i = up[0]; j = i
        while j < len(wave) - 1 and wave[j] < t90: j += 1
        out["rise_ns"] = (j - i) * g * ets.TICK_NS
    out["lo"] = lo; out["hi"] = hi; out["overshoot_pct"] = 100 * (np.nanmax(wave) - hi) / span
    plate = wave[(wave > hi - 0.05 * span)]; out["hi_plateau_std_mv"] = 1000 * float(np.nanstd(plate))
    return out


def ets_bandwidth():
    """Frequency response of DAC + output stage + CH2 input at 5 MS/s update, 100-code sine, by ETS."""
    warmup(); fs, p_d = 5_000_000, 40; ideal = 100 * awg.MV_PER_CODE / 1000
    print(f"5 MS/s update, 100-code sine ({ideal:.3f} V ideal peak); ETS, one cycle rebuilt per row")
    print("   f kHz | pts/cycle | amp V | vs ideal dB | THD % | underruns | min samples/bin")
    ref = None
    for f in (10_000, 50_000, 100_000, 200_000, 250_000, 500_000, 1_000_000):
        ppc = int(fs / f); buf = awg.sine(fs, f, 100); pl = ets.plan(p_d, ppc)
        data, ctr, ratio = play(buf, fs, warm=1.5, seconds=3.0, aperiod=pl["p_a"], raw=True)
        v = (ets.gapless_samples(data) - ZERO) / CPV
        wave, counts = ets.reconstruct(v, pl["p_a"], pl["W"], pl["g"])
        w = np.where(np.isnan(wave), np.nanmean(wave), wave); F = np.abs(np.fft.rfft(w)) * 2 / len(w)
        amp = F[1]; thd = np.sqrt(np.sum(F[2:6] ** 2)) / amp
        ref = ref or amp
        print(f"{f/1e3:8.0f} | {ppc:9d} | {amp:.3f} | {20*np.log10(amp/ideal):+7.2f} | {100*thd:5.2f} | {ctr['underruns']:>4} | {counts.min()}", flush=True)


def ets_cmd():
    warmup()
    for kind, p_a, g in (("square", None, None), ("square", 136, None), ("square", 105, 8), ("sine", None, None)):
        wave, counts, pl, ctr, expected, n = ets_run(kind, p_a, g)
        sh, aligned = ets.align(wave, expected)
        m = edge_metrics(aligned, pl["g"]) if kind == "square" else {}
        err = float(np.sqrt(np.nanmean((aligned - expected) ** 2))) * 1000
        print(f"{kind}: P_a {pl['p_a']} ticks ({200/pl['p_a']:.3f} Msps), W {pl['W']} ticks, {pl['bins']} bins of {pl['g']*ets.TICK_NS:.0f} ns, "
              f"samples {n}, min/mean per bin {counts.min()}/{counts.mean():.0f}, underruns {ctr['underruns']}, "
              f"rms vs ideal staircase {err:.0f} mV; " + ", ".join(f"{k} {v:.3g}" for k, v in m.items()), flush=True)
    return


def warmup():
    """The first run after enumeration is an outlier in this project; throw one away by index."""
    settle()
    play(awg.sine(250_000, 10_000, 100), 250_000, warm=0.5, seconds=0.5)


def ladder():
    warmup()
    ideal = 300 * awg.MV_PER_CODE / 1000
    print(f"10 kHz sine, 300 codes ({ideal:.3f} V ideal), amplitude/THD from CH2 at 2.5 Msps")
    print("update rate | rate ratio | underruns | short | amp V (ratio) | THD % | resid mV")
    for fs in (250_000, 500_000, 1_000_000, 2_000_000, 2_500_000, 4_000_000, 5_000_000):
        v, c, r = play(awg.sine(fs, 10_000, 300), fs)
        m = fit(v, 10_000)
        short = c["capture_samples"] < 0.9 * c["expected_samples"]
        print(f"{fs/1e6:6.2f} MS/s | {r:.5f} | {c['underruns']:>4} | {c['short']:>3} | {m['amp']:.3f} ({m['amp']/ideal:.3f}) | {100*m['thd']:.2f} | {m['resid_mv']:.1f} | capture {c['capture_samples']}/{c['expected_samples']}{'  SHORT CAPTURE' if short else ''} | acq missed/lost/ovr {c['acq_tc_missed']}/{c['acq_lost']}/{c['acq_ovr']}", flush=True)


def bandwidth():
    warmup()
    fs = 5_000_000; ideal = 100 * awg.MV_PER_CODE / 1000
    print(f"5 MS/s update, 100-code sine ({ideal:.3f} V ideal)")
    ref = None
    for f0 in (1_000, 10_000, 50_000, 100_000, 250_000, 400_000):
        v, c, r = play(awg.sine(fs, f0, 100), fs)
        m = fit(v, f0, harmonics=3)
        ref = ref or m["amp"]
        print(f"{f0/1e3:8.0f} kHz | underruns {c['underruns']:>3} | amp {m['amp']:.3f} V | rel {20*np.log10(m['amp']/ref):+.2f} dB | resid {m['resid_mv']:.1f} mV", flush=True)


def square():
    warmup()
    for fs, f0 in ((5_000_000, 10_000), (5_000_000, 100_000), (2_500_000, 10_000)):
        v, c, r = play(awg.square(fs, f0, 300), fs)
        lo, hi = np.percentile(v, 2), np.percentile(v, 98); t10, t90 = lo + .1 * (hi - lo), lo + .9 * (hi - lo)
        edges = []; i = 1
        while i < len(v) - 80:
            if v[i - 1] < t10 <= v[i]:
                j = i
                while j < len(v) - 1 and v[j] < t90: j += 1
                edges.append(j - i + 1); i = j + 20
            else: i += 1
        med = float(np.median(edges)) if edges else float("nan")
        print(f"square {f0/1e3:.0f} kHz at {fs/1e6:.1f} MS/s: swing {hi-lo:.2f} V, rising 10-90 % in {med:.1f} samples = {med/ADC_FS*1e6:.2f} us (observer resolution 0.4 us), underruns {c['underruns']}", flush=True)


if __name__ == "__main__":
    {"etsbw": ets_bandwidth, "ets": ets_cmd, "repeat": lambda: [one(float(sys.argv[2])) for _ in range(int(sys.argv[3]))], "one": lambda: one(float(sys.argv[2])), "feed": feed, "ladder": ladder, "bandwidth": bandwidth, "square": square}[sys.argv[1]]()
