"""The stock H7-TOOL protocol for the 250M scope module, and the H7-TOOL's target supply and generator that go with it (docs/23).

Modbus RTU frames in 1024-byte HID reports to the stock app (USB c251:f00a, interface 2): address 1 is the H7-TOOL, 0x10 the module behind it. This is
the host side of what the stock app speaks; it is not the SPI link between the H7 and the module (docs/24). The transport is injectable, so the whole
client is tested against a simulated module (tests/test_h7_250m.py) and a real one is reached with `HidrawTransport`.

    from h7_250m import Module, HidrawTransport
    m = Module(HidrawTransport()); m.set_tvcc_mv(3300); m.enable()
    samples = m.capture(rate_idx=12, depth_idx=1, range_code=6, trig_level_v=0.0, trig_pos=50, trig_mode=2)
"""
import glob, os, select, struct, time

SZ = 1024                                     # one HID report
TOOL, MODULE = 0x01, 0x10                     # Modbus addresses
REG_TVCC_MV, REG_ENABLE, REG_GEN = 0x0085, 0x0212, 0x0100       # on address 1: target supply in mV; 250M path 2 = off, 1 = on; the generator block
REG_CFG, REG_DONE, REG_STATUS, REG_CH1, REG_CH2 = 0x0100, 0x021C, 0xC100, 0x2000, 0x4000   # on address 0x10
RATES_HZ = [100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000,
            20_000_000, 50_000_000, 100_000_000, 125_000_000, 250_000_000]        # sample-rate index 0..20; index 20 is channel 1 only
RATES_VERIFIED = {10: 200_000, 12: 1_000_000, 14: 5_000_000}                         # the indices checked against a known signal (docs/23)
DEPTH_BLOCKS = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16}                                       # depth index -> blocks of 1024 samples
JUNK_HEAD = 100                                                                      # the first samples of block 0 are start-up junk
# Range codes 0..9 at the 1x probe, measured (docs/23): codes per volt, and the code read at 0 V. Code 9 is the most sensitive.
CODES_PER_V = [2.83, 5.74, 14.35, 28.70, 56.93, 133.4, 264.6, 677.0, 1394.0, 2539.0]
ZERO_CODE = [118.0, 118.0, 117.4, 116.4, 114.4, 117.4, 116.5, 113.4, 109.5, 100.1]
OFF_BLOCK = [1, 0, 0, 0, 0, 0, 50, 0, 0, 1]                                          # generator block that switches VOUT off


class ProtocolError(Exception): pass
class ModuleNotReady(ProtocolError): """address 0x10 answered with exception 3: TVCC wrong or the 250M path not enabled."""


def crc16(m):
    """CRC-16/MODBUS, low byte first."""
    c = 0xFFFF
    for x in m:
        c ^= x
        for _ in range(8): c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return struct.pack("<H", c)


def read_request(addr, reg, n): return _frame(struct.pack(">BBHH", addr, 3, reg, n))
def write1_request(addr, reg, val): return _frame(struct.pack(">BBHH", addr, 6, reg, val & 0xFFFF))
def write_n_request(addr, reg, vals): return _frame(struct.pack(">BBHHB", addr, 0x10, reg, len(vals), 2 * len(vals)) + struct.pack(">%dH" % len(vals), *[v & 0xFFFF for v in vals]))
def _frame(body): return body + crc16(body)


def f32_regs(x):
    """A float32 as two big-endian registers, high first (the trigger level)."""
    return list(struct.unpack(">2H", struct.pack(">f", x)))


def settings_block(rate_idx, depth_idx, range_code=None, range1=6, range2=6, trig_level_v=0.0, trig_pos=50, trig_mode=0, trig_ch=0, edge=1, chmask=1, coupling=(1, 1)):
    """The 17 registers written at 0x0100 of the module; the last one starts the capture. range_code sets both channels' ranges (0 widest .. 9 most sensitive).
    trig_mode 2 is the only live trigger, it fires on either edge whatever `edge` says, and a level the signal never reaches never completes (docs/23)."""
    if range_code is not None: range1 = range2 = range_code
    return [0, coupling[0], coupling[1], range1, range2, 0, 0, rate_idx, depth_idx] + f32_regs(trig_level_v) + [trig_pos, trig_mode, trig_ch, edge, chmask, 1]


def generator_block(wave, lo_mv, hi_mv, hz=0, duty=50):
    """The 10 words at address 1, register 0x0100: wave 0 off, 1 DC, 2 square, 3 triangle (docs/23); levels in mV (negative as two's complement)."""
    return [1, wave, lo_mv & 0xFFFF, hi_mv & 0xFFFF, (hz >> 16) & 0xFFFF, hz & 0xFFFF, duty, 0, 0, 1]


def codes_to_volts(codes, range_code):
    return [(c - ZERO_CODE[range_code]) / CODES_PER_V[range_code] for c in codes]


class HidrawTransport:
    """The H7-TOOL's register channel: /dev/hidraw for USB interface 2 of c251:f00a (the node number changes between plug-ins)."""
    def __init__(self, vid="C251", pid="F00A", iface=2):
        node = None
        for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            p = os.path.realpath(d + "/device"); tag = os.path.basename(p).upper()
            if vid in tag and pid in tag and (":1.%d/" % iface) in p + "/": node = "/dev/" + os.path.basename(d)
        if node is None: raise FileNotFoundError("H7-TOOL HID interface %d not found (plugged in? stock app running? udev rule?)" % iface)
        self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)

    def drain(self):
        while select.select([self.fd], [], [], 0)[0]: os.read(self.fd, 2048)

    def send(self, frame): self.drain(); os.write(self.fd, frame.ljust(SZ, b"\0"))

    def recv(self, n_reports=1, timeout=1.0):
        reps, t0 = [], time.time()
        while len(reps) < n_reports and time.time() - t0 < timeout:
            if select.select([self.fd], [], [], 0.2)[0]: reps.append(os.read(self.fd, 2048))
        return reps


class Module:
    """Requests with the checks the notes call for: the reply must echo address and function, large replies join two reports and their CRC must hold."""
    def __init__(self, transport, sleep=time.sleep): self.t, self.sleep = transport, sleep

    def _exchange(self, frame, n_reports=1, timeout=1.0):
        self.t.send(frame); return self.t.recv(n_reports, timeout)

    def read(self, addr, reg, n, retries=3):
        for _ in range(retries):
            reps = self._exchange(read_request(addr, reg, n))
            if not reps or reps[0][0] != addr: continue
            if reps[0][1] == 0x83: raise (ModuleNotReady if addr == MODULE and reps[0][2] == 3 else ProtocolError)("exception %d reading 0x%04x at 0x%02x" % (reps[0][2], reg, addr))
            if reps[0][1] == 3 and reps[0][2] == 2 * n: return list(struct.unpack(">%dH" % n, bytes(reps[0][3:3 + 2 * n])))
        raise ProtocolError("no valid reply reading 0x%04x x%d at 0x%02x" % (reg, n, addr))

    def write1(self, addr, reg, val):
        reps = self._exchange(write1_request(addr, reg, val))
        if not reps or reps[0][:2] != bytes([addr, 6]): raise ProtocolError("write of 0x%04x at 0x%02x not echoed" % (reg, addr))

    def write_n(self, addr, reg, vals):
        reps = self._exchange(write_n_request(addr, reg, vals))
        if reps and reps[0][1] == 0x90: raise ModuleNotReady("write of the settings block refused (module not enabled)")
        if not reps or reps[0][:2] != bytes([addr, 0x10]): raise ProtocolError("block write at 0x%04x not acknowledged" % reg)

    # --- the H7-TOOL itself ---
    def tvcc_mv(self): return self.read(TOOL, REG_TVCC_MV, 1)[0]
    def set_tvcc_mv(self, mv): self.write1(TOOL, REG_TVCC_MV, mv); self.sleep(1.0)       # the module needs 3300; measured one step is 30.7 mV (docs/23)
    def set_generator(self, block): self.write_n(TOOL, REG_GEN, block)
    def generator_off(self): self.set_generator(OFF_BLOCK)

    # --- the module ---
    def enable(self):
        """0x0212 = 2, 1 s, = 1, 1.5 s (the stock sequence); recovers a module that dropped out and resets it to its defaults."""
        self.write1(TOOL, REG_ENABLE, 2); self.sleep(1.0); self.write1(TOOL, REG_ENABLE, 1); self.sleep(1.5)

    def settings(self): return self.read(MODULE, REG_CFG, 17)

    def block(self, k, ch=0, tries=8):
        """One 1 KB block of 8-bit samples (a reply spans two reports: header and 1021 bytes, then the last 3, the CRC and padding)."""
        for _ in range(tries):
            reps = self._exchange(read_request(MODULE, (REG_CH1 if ch == 0 else REG_CH2) + k, 0x200), 2)
            if len(reps) == 2 and reps[0][:2] == bytes([MODULE, 3]):
                full = bytes(reps[0]) + bytes(reps[1])
                if full[1027:1029] == crc16(full[:1027]): return list(full[3:1027])
        raise ProtocolError("block %d could not be read" % k)

    def capture(self, rate_idx, depth_idx, ready_timeout=8.0, ch=0, verify=False, **settings):
        """Configure and start a capture, wait for it, read it back (first JUNK_HEAD samples dropped). With verify, every block is read twice and must agree."""
        cfg = settings_block(rate_idx, depth_idx, **settings)
        try: self.write_n(MODULE, REG_CFG, cfg)
        except ModuleNotReady: self.enable(); self.write_n(MODULE, REG_CFG, cfg)
        t0 = time.time()
        while self.read(MODULE, REG_DONE, 1)[0] != 1:
            if time.time() - t0 > ready_timeout: raise TimeoutError("the capture never became ready (a single-trigger level that the signal does not reach waits for ever)")
            self.sleep(0.03)
        self.write1(MODULE, REG_DONE, 1)
        out = []
        for k in range(DEPTH_BLOCKS[depth_idx]):
            b = self.block(k, ch)
            if verify and self.block(k, ch) != b: raise ProtocolError("block %d read twice and the reads differ" % k)
            out += b
        return out[JUNK_HEAD:]

    def status(self):
        """The 8 floats of the status block 0xC100 (fixed per module: 114.9 0 212.7 1.699 125.55 0 223.4 1.699 on the one measured; meaning unknown)."""
        r = self.read(MODULE, REG_STATUS, 16)
        return [struct.unpack(">f", struct.pack(">HH", r[2 * i], r[2 * i + 1]))[0] for i in range(8)]
