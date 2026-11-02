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
import h7_metrics as met
import h7_records as rec

PROBE = ["sudo", "-n", "python3", os.path.join(HERE, "h7_usb_probe.py")]
ADC_FS = 2.0e6      # observer rate: 0.8 of the 2.5 Msps cliff, never at it (docs/10)
OBS = int(os.environ.get("H7_OBS", "2"))        # observer channel: 2 (VOUT wired to CH2) or 1 (VOUT wired to CH1)
ZERO, CPV = (32750.0, 2301.0) if OBS == 2 else (32843.0, 2310.0)   # zero code and codes per volt at gain 0 (docs/12)


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
    """Play `buf` repeatedly at update rate fs; return (captured volts or raw bytes, device counters, rate ratio).

    The acquisition stream starts the moment the port opens, so it is drained by a reader thread from
    then on: a host that does not read (while sudo probes run) lets the tty fill, the host stops polling
    the IN endpoint, and the device ring overflows - the intermittent bad rows this tool used to give.
    Whatever happens, the writer is killed, playback stopped and the output switched off before returning.
    """
    import select
    probe("wave 0 0"); probe("gcenter 2036"); probe(f"gperiod {awg.period_ticks(fs)}")
    probe(f"chan {OBS}"); probe(f"aperiod {aperiod or int(round(200e6 / ADC_FS))}")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
    data = bytearray(); stop = threading.Event(); wp = None
    def reader():
        while not stop.is_set():
            if select.select([s.fd], [], [], 0.05)[0]:
                try: data.extend(os.read(s.fd, 1 << 20))
                except OSError: pass
    rt = threading.Thread(target=reader, daemon=True); rt.start()
    try:
        time.sleep(0.3); probe("pstart 2")
        wp, wname = start_writer(s.name, buf)
        time.sleep(warm); start = len(data); c1 = (int(counters()["consumed"]), time.time())
        time.sleep(seconds); end = len(data)          # the measurement window ends HERE: the cleanup below shuts the output down
        ctr = counters(); c2 = (int(ctr["consumed"]), time.time())    # before the writer stops: the drain is not an underrun
        a = dict(kv.split("=") for kv in probe("acq").split())
        ctr["acq_tc_missed"] = a["tc_missed"]; ctr["acq_lost"] = a["lost"]; ctr["acq_ovr"] = a["adc_ovr"]; ctr["acq_sent"] = a["sent"]; ctr["acq_frames"] = a["frames_done"]
        ctr["stall"] = {k: a[k] for k in ("dma_err", "dma_err_frame", "stall", "stall_lisr", "stall_cr", "stall_ndtr", "stall_isr", "stall_adccr")}
    finally:
        if wp is not None: stop_writer(wp, wname)
        try: probe("pstop"); probe("wave 0 0")
        except Exception as e: print("cleanup: could not stop playback:", e, flush=True)
        stop.set(); rt.join(2); s.close()
    ratio = ((c2[0] - c1[0]) & 0xFFFFFFFF) / (c2[1] - c1[1]) / fs
    if raw:
        return bytes(data[start:end]), ctr, ratio
    x = codes_of(bytes(data[start:end]))
    ctr["capture_samples"] = len(x); ctr["expected_samples"] = int(ADC_FS * seconds)
    return (x - ZERO) / CPV, ctr, ratio


def fw_build():
    """Build id of the image on the unit (vendor dbg request, image11j and later); None if it does not answer."""
    try:
        return int(dict(kv.split("=") for kv in probe("dbg").split())["build"], 16)
    except Exception:
        return None


MIN_BUILD = 12                       # image11l: the generator-start stall fix


def ready():
    """Refuse to measure on an image older than the stall fix, then settle and discard the first run."""
    b = fw_build()
    if b is None or b < MIN_BUILD:
        raise RuntimeError(f"unit reports build {b}; need >= {MIN_BUILD} (image11l or later)")
    warmup()
    return b


def ets_measure(kind, buf, fs, ppc, seconds=3.0, tries=3, p_a=None, g=None):
    """One ETS capture that is checked before it is believed: no underruns, a full-length gapless capture,
    and split-half agreement (h7_ets.integrity). A failing capture is retried, up to `tries`; the reasons of
    every failed try are kept. Returns a dict with `valid`, `reasons`, `tries`, the rebuilt wave and the plan."""
    pl = ets.plan(200_000_000 // fs, ppc, g=g)
    if p_a: pl["p_a"] = p_a
    reasons = []
    for t in range(1, tries + 1):
        data, ctr, ratio = play(buf, fs, warm=1.5, seconds=seconds, aperiod=pl["p_a"], raw=True)
        v = (ets.gapless_samples(data) - ZERO) / CPV
        bad = []
        if int(ctr["underruns"]) or int(ctr["short"]): bad.append(f"playback underruns {ctr['underruns']} short {ctr['short']}")
        if len(v) < 0.9 * ADC_FS * seconds * 100 / pl["p_a"]: bad.append(f"short or gappy capture: {len(v)} gapless samples")
        if ctr["stall"]["dma_err"] != "0x0": bad.append(f"ADC DMA error {ctr['stall']['dma_err']}")
        if not bad:
            ig = ets.integrity(v, pl["p_a"], pl["W"], pl["g"])
            if not ig["ok"]: bad.append(ig["reason"])
        if not bad:
            wave, counts = ets.reconstruct(v, pl["p_a"], pl["W"], pl["g"])
            return dict(valid=True, reasons=reasons, tries=t, wave=wave, counts=counts, plan=pl, ctr=ctr, integrity=ig, samples=len(v), ratio=ratio)
        reasons.append(f"try {t}: " + "; ".join(bad)); print("  rejected:", reasons[-1], flush=True)
    return dict(valid=False, reasons=reasons, tries=tries, wave=None, plan=pl, ctr=ctr, samples=len(v), ratio=ratio)


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


edge_metrics = met.edge_metrics


def ets_bandwidth(amp_codes=100):
    """Frequency response of DAC + output stage + the observer at 5 MS/s update, by ETS; every row checked and recorded."""
    build = ready(); fs = 5_000_000; ideal = amp_codes * awg.MV_PER_CODE / 1000
    obs = dict(channel=OBS, adc_period_ticks=int(round(200e6 / ADC_FS)), gain_code=0, zero_code=ZERO, codes_per_volt=CPV)
    print(f"5 MS/s update, {amp_codes}-code sine ({ideal:.3f} V ideal peak); ETS, one cycle rebuilt per row")
    print("   f kHz | pts/cycle | amp V | vs ideal dB | THD % | tries | min samples/bin")
    for f in (10_000, 50_000, 100_000, 200_000, 250_000, 500_000, 1_000_000):
        ppc = fs // f; r = ets_measure("sine", awg.sine(fs, f, amp_codes), fs, ppc)
        if not r["valid"]:
            rec.record("sine_bw", dict(f_hz=f, amp_codes=amp_codes, update_hz=fs), {}, False, r["reasons"], r["tries"], build, obs)
            print(f"{f/1e3:8.0f} | {ppc:9d} | INVALID after {r['tries']} tries", flush=True); continue
        sm = met.sine_metrics(r["wave"])
        rec.record("sine_bw", dict(f_hz=f, amp_codes=amp_codes, update_hz=fs, p_a=r["plan"]["p_a"]), dict(sm, ideal=ideal, db=20*np.log10(sm["amp"]/ideal)), True, r["reasons"], r["tries"], build, obs)
        print(f"{f/1e3:8.0f} | {ppc:9d} | {sm['amp']:.3f} | {20*np.log10(sm['amp']/ideal):+7.2f} | {100*sm['thd']:5.2f} | {r['tries']:>3} | {r['counts'].min()}", flush=True)


def ets_rate():
    """Is there an update-rate effect where it can show? A tone whose staircase the output stage has not already
    removed: 100 and 200 kHz at several update rates, same amplitude, ETS, each row twice (checked and recorded)."""
    build = ready(); ideal = 100 * awg.MV_PER_CODE / 1000
    obs = dict(channel=OBS, adc_period_ticks=int(round(200e6 / ADC_FS)), gain_code=0, zero_code=ZERO, codes_per_volt=CPV)
    print(f"100-code sine ({ideal:.3f} V ideal peak); ETS; each row twice to show the repeatability")
    print("   f kHz | update MS/s | pts/cycle | amp V | dB vs ideal | H2..H5 % of fundamental | tries")
    for f in (100_000, 200_000):
        for fs in (1_000_000, 2_000_000, 5_000_000):
            ppc = fs // f
            for rep in (1, 2):
                r = ets_measure("sine", awg.sine(fs, f, 100), fs, ppc)
                if not r["valid"]:
                    rec.record("sine_rate", dict(f_hz=f, amp_codes=100, update_hz=fs), {}, False, r["reasons"], r["tries"], build, obs)
                    print(f"{f/1e3:8.0f} | {fs/1e6:11.1f} | {ppc:9d} | INVALID after {r['tries']} tries", flush=True); continue
                sm = met.sine_metrics(r["wave"])
                rec.record("sine_rate", dict(f_hz=f, amp_codes=100, update_hz=fs, p_a=r["plan"]["p_a"], rep=rep), dict(sm, ideal=ideal), True, r["reasons"], r["tries"], build, obs)
                print(f"{f/1e3:8.0f} | {fs/1e6:11.1f} | {ppc:9d} | {sm['amp']:.4f} | {20*np.log10(sm['amp']/ideal):+6.2f} | {100*sm['thd']:6.3f} | {r['tries']}", flush=True)


def ets_amp():
    """Linear bandwidth or slew limit? The same tone at several amplitudes: a linear roll-off gives the same gain
    at every amplitude, a slew limit loses gain (and adds harmonics) as the amplitude grows."""
    warmup(); fs, p_d = 5_000_000, 40
    print("5 MS/s update, ETS; gain = measured peak / ideal peak, per amplitude, twice each")
    print("   f kHz | amp codes | ideal V | amp V | dB vs ideal | H2-H5 % | peak slew V/us")
    for f in (50_000, 100_000, 200_000):
        for amp in (20, 60, 150, 300):
            ppc = int(fs / f); pl = ets.plan(p_d, ppc); ideal = amp * awg.MV_PER_CODE / 1000
            buf = awg.sine(fs, f, amp)
            for rep in (1, 2):
                data, ctr, ratio = play(buf, fs, warm=1.5, seconds=3.0, aperiod=pl["p_a"], raw=True)
                v = (ets.gapless_samples(data) - ZERO) / CPV
                wave, counts = ets.reconstruct(v, pl["p_a"], pl["W"], pl["g"])
                w = np.where(np.isnan(wave), np.nanmean(wave), wave); F = np.abs(np.fft.rfft(w)) * 2 / len(w)
                slew = float(np.nanmax(np.abs(np.diff(w))) / (pl["g"] * ets.TICK_NS * 1e-3))
                print(f"{f/1e3:8.0f} | {amp:9d} | {ideal:.3f} | {F[1]:.4f} | {20*np.log10(F[1]/ideal):+6.2f} | {100*np.sqrt(np.sum(F[2:6]**2))/F[1]:6.3f} | {slew:.2f}", flush=True)


def dc_measure(code, seconds=1.5):
    """Mean level of a DC output, checked like the ETS captures (no underruns, a full-length gapless capture)."""
    data, ctr, _ = play(awg.dc(code), 1_000_000, warm=1.5, seconds=seconds, raw=True)
    x = ets.gapless_samples(data); bad = []
    if int(ctr["underruns"]): bad.append(f"underruns {ctr['underruns']}")
    if len(x) < 0.9 * ADC_FS * seconds: bad.append(f"short capture {len(x)}")
    v = (x.mean() - ZERO) / CPV if len(x) else float("nan")
    return dict(valid=not bad, reasons=bad, volts=float(v), std_mv=float(1000 * x.std() / CPV) if len(x) else float("nan"))


def large(steps=(4.0, 6.0, 8.0, 9.5)):
    """Raise the host-enforced swing cap in steps and measure large-signal behaviour at each. VOUT must be on the
    observer channel (H7_OBS). Every measurement is integrity-checked and recorded (h7_records); a step that fails
    its checks, or has a measurement that stays invalid after retries, stops the run before the next, larger one."""
    build = ready(); fs = 5_000_000
    obs = dict(channel=OBS, adc_period_ticks=int(round(200e6 / ADC_FS)), gain_code=0, zero_code=ZERO, codes_per_volt=CPV)
    for vpk in steps:
        A = int(vpk * 1000 / awg.MV_PER_CODE); awg.set_swing_limit(A)
        print(f"\n== cap +-{vpk} V = +-{A} codes ==", flush=True)
        ok = True
        for code in (awg.ZERO_CODE - A, awg.ZERO_CODE, awg.ZERO_CODE + A):          # DC against the stock calibration
            r = dc_measure(code); want = awg.stock_mv(code) / 1000
            rec.record("dc", dict(code=code, cap_codes=A), dict(volts=r["volts"], stock_volts=want, std_mv=r["std_mv"]), r["valid"], r["reasons"], 1, build, obs)
            print(f"  DC code {code}: reads {r['volts']:+.3f} V, stock calibration {want:+.3f} V, difference {1000*(r['volts']-want):+.0f} mV  (std {r['std_mv']:.0f} mV)" + ("" if r["valid"] else f"  INVALID {r['reasons']}"), flush=True)
            if not r["valid"] or abs(r["volts"] - want) > 0.30: ok = False; print("  ** DC invalid or more than 0.3 V from the stock calibration", flush=True)
        for f in (10_000, 50_000, 100_000):                                            # large sine
            ppc = fs // f; ideal = A * awg.MV_PER_CODE / 1000
            r = ets_measure("sine", awg.sine(fs, f, A), fs, ppc)
            if r["valid"]:
                sm = met.sine_metrics(r["wave"])
                rec.record("sine", dict(f_hz=f, amp_codes=A, update_hz=fs, p_a=r["plan"]["p_a"]), dict(sm, ideal=ideal, db=20*np.log10(sm["amp"]/ideal), half_rms_mv=1000*r["integrity"]["half_rms"]), True, r["reasons"], r["tries"], build, obs)
                print(f"  sine {f/1e3:5.0f} kHz: peak {sm['amp']:.3f} V (ideal {ideal:.3f}, {20*np.log10(sm['amp']/ideal):+.2f} dB), THD {100*sm['thd']:.2f} %, cycle {sm['lo']:+.2f}/{sm['hi']:+.2f} V, tries {r['tries']}", flush=True)
                if f == 10_000 and not (0.95 < sm["amp"] / ideal < 1.05 and sm["thd"] < 0.03): ok = False; print("  ** 10 kHz amplitude or distortion outside 5 % / 3 %", flush=True)
            else:
                rec.record("sine", dict(f_hz=f, amp_codes=A, update_hz=fs), {}, False, r["reasons"], r["tries"], build, obs); ok = False
                print(f"  sine {f/1e3:5.0f} kHz: INVALID after {r['tries']} tries", flush=True)
        r = ets_measure("square", awg.square(fs, 10_000, A), fs, 500)                   # large square: edge speed
        if r["valid"]:
            e = met.edge_metrics(r["wave"], r["plan"]["g"])
            rec.record("square", dict(f_hz=10_000, amp_codes=A, update_hz=fs, p_a=r["plan"]["p_a"]), e, e["valid"], ([e["reason"]] if e["reason"] else []) + r["reasons"], r["tries"], build, obs)
            if e["valid"]:
                print(f"  square 10 kHz: low {e['lo']:+.2f} V high {e['hi']:+.2f} V (span {e['span']:.2f}, ideal {2*A*awg.MV_PER_CODE/1000:.2f}), 10-90 % rise {e['rise_ns']:.0f} ns / fall {e['fall_ns']:.0f} ns "
                      f"=> {0.8*e['span']/(e['rise_ns']*1e-3):.2f} / {0.8*e['span']/(e['fall_ns']*1e-3):.2f} V/us, overshoot {e['overshoot_pct']:.1f} %, tries {r['tries']}", flush=True)
            else:
                ok = False; print(f"  square 10 kHz: edge metric INVALID: {e['reason']}", flush=True)
        else:
            rec.record("square", dict(f_hz=10_000, amp_codes=A, update_hz=fs), {}, False, r["reasons"], r["tries"], build, obs); ok = False
            print(f"  square 10 kHz: INVALID after {r['tries']} tries", flush=True)
        if not ok: print("  STOPPED: this step failed its checks; not going further.", flush=True); break
    awg.set_swing_limit(330)


def amp_for(f_hz, vpp, fs=5_000_000, tol=0.01):
    """The drive (DAC codes, peak) that makes the OUTPUT a sine of `vpp` volts peak-to-peak at f_hz, found by measuring:
    start from the small-signal gain at that frequency, then correct by the ratio of target to measured peak until
    within `tol`. Every measurement is integrity-checked and recorded; the host swing cap is respected."""
    build = ready(); ppc = fs // f_hz; target = vpp / 2
    obs = dict(channel=OBS, adc_period_ticks=int(round(200e6 / ADC_FS)), gain_code=0, zero_code=ZERO, codes_per_volt=CPV)
    if fs % f_hz: raise ValueError("f must divide the update rate")
    def peak(amp):
        awg.set_swing_limit(max(amp, 1))
        r = ets_measure("sine", awg.sine(fs, f_hz, amp), fs, ppc)
        if not r["valid"]: raise RuntimeError(f"measurement invalid at {amp} codes: {r['reasons']}")
        sm = met.sine_metrics(r["wave"])
        rec.record("amp_for", dict(f_hz=f_hz, amp_codes=amp, update_hz=fs, target_vpp=vpp), sm, True, r["reasons"], r["tries"], build, obs)
        return sm
    try:
        a = 100; sm = peak(a); g = sm["amp"] / (a * awg.MV_PER_CODE / 1000)
        print(f"small-signal gain at {f_hz/1e3:.0f} kHz: {g:.4f} ({20*np.log10(g):+.2f} dB)", flush=True)
        a = int(round(target / (g * awg.MV_PER_CODE / 1000)))
        for it in range(4):
            if a > awg.HARD_LIMIT_CODES: raise RuntimeError(f"needs {a} codes, over the ceiling {awg.HARD_LIMIT_CODES}")
            sm = peak(a); out = sm["amp"]
            print(f"  drive {a} codes peak (DAC pin {a*2.5/4096:.3f} V peak *(assumes a 2.5 V reference)*): output {2*out:.4f} Vpp, THD {100*sm['thd']:.2f} %", flush=True)
            if abs(out / target - 1) < tol: return a, sm
            a = int(round(a * target / out))
        return a, sm
    finally:
        awg.set_swing_limit(330)


def acquire(seconds, mask, aperiod, settle_s=0.4):
    """Acquire `seconds` of both/either channel with nothing playing; returns the per-channel sample arrays (raw codes)."""
    import select
    probe("wave 0 0"); probe(f"chan {mask}"); probe(f"aperiod {aperiod}")
    s = serial.Serial(chk.find_port(), 115200, timeout=0.2); os.set_blocking(s.fd, False)
    data = bytearray(); stop = threading.Event()
    def reader():
        while not stop.is_set():
            if select.select([s.fd], [], [], 0.05)[0]:
                try: data.extend(os.read(s.fd, 1 << 20))
                except OSError: pass
    rt = threading.Thread(target=reader, daemon=True); rt.start()
    try:
        time.sleep(settle_s); start = len(data); time.sleep(seconds); end = len(data)
    finally:
        stop.set(); rt.join(2); s.close()
    nch = bin(mask).count("1")
    return ets.gapless_planes(bytes(data[start:end]), nch)


def zero_noise(periods=(200, 100)):
    """Inputs shorted to ground (CH1 and CH2 each to their GND pin): zero code and noise of both channels at every gain
    code, DC coupled. Needs nothing playing and nothing on the inputs. Recorded."""
    build = fw_build()
    if build is None or build < MIN_BUILD: raise RuntimeError(f"unit reports build {build}")
    settle()
    import h7_cal
    cal = h7_cal.Calibration.load()
    print("inputs shorted; per gain code, per ADC period: zero code (std, high-frequency std) | factory zero | difference in volts")
    for per in periods:
        print(f"-- ADC period {per} ticks ({200/per:.1f} Msps)")
        for g in range(8):
            probe(f"fe {hex(0x88 | g | (g << 4))}"); time.sleep(0.3)
            planes = acquire(3.0, 3, per); row = []
            for ch, x in enumerate(planes, start=1):
                if len(x) < 0.8 * (200e6 / per) * 3.0:
                    row.append(f"CH{ch}: short capture {len(x)}"); rec.record("zero_noise", dict(channel=ch, gain=g, adc_period=per), {}, False, ["short capture"], 1, build, None); continue
                m, sd = float(x.mean()), float(x.std()); hf = float(np.std(np.diff(x)) / np.sqrt(2))
                z = cal.zero_code(ch, g); cpv = cal.codes_per_volt(ch, g)
                rec.record("zero_noise", dict(channel=ch, gain=g, adc_period=per, samples=len(x)),
                           dict(mean_code=m, std_code=sd, hf_std_code=hf, factory_zero=z, codes_per_volt=cpv, zero_diff_v=(m - z) / cpv, noise_mv_rms=1000 * sd / cpv), True, [], 1, build, dict(channel=ch, gain_code=g, adc_period_ticks=per, inputs="shorted to GND"))
                row.append(f"CH{ch}: {m:9.1f} ({sd:6.1f}, {hf:6.1f}) | {z:9.1f} | {1000*(m - z)/cpv:+8.2f} mV, noise {1000*sd/cpv:6.2f} mV")
            print(f"  gain {g}: " + "   ".join(row), flush=True)
    probe("fe 0x88")


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
    {"zeronoise": zero_noise, "ampfor": lambda: amp_for(int(float(sys.argv[2])), float(sys.argv[3])), "large": lambda: large(tuple(float(x) for x in sys.argv[2:]) or (4.0, 6.0, 8.0, 9.5)), "etsamp": ets_amp, "etsrate": ets_rate, "etsbw": ets_bandwidth, "ets": ets_cmd, "repeat": lambda: [one(float(sys.argv[2])) for _ in range(int(sys.argv[3]))], "one": lambda: one(float(sys.argv[2])), "feed": feed, "ladder": ladder, "bandwidth": bandwidth, "square": square}[sys.argv[1]]()
