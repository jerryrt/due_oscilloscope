"""tools/h7_250m.py against a simulated module: framing, the enable sequence, the settings block, capture and read-out, the exceptions a module that is not ready gives, and the
glitches the notes warn about. The same checks run on mutated copies of the client, and each mutant must fail one of them. No hardware: the real thing is the board tier."""
import importlib.util, os, struct, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "targets", "h7tool", "tools", "h7_250m.py")


def load(path, name="h7_250m_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m


class SimTransport:
    """A stock-protocol device: address 1 is the H7-TOOL (supply, enable, generator), 0x10 the module, which answers only when TVCC is 3.3 V and it has been enabled."""
    def __init__(self, h, tvcc=3300, glitch_first_read=False, never_done=False, flaky_blocks=False, bad_count_once=False, bad_crc_once=False):
        self.h, self.tvcc, self.enable, self.cfg, self.done, self.gen = h, tvcc, 0, [0, 1, 1, 4, 4, 0, 0, 12, 0, 0, 0, 0, 0, 0, 1, 0, 1], 0, None
        self.up, self.replies, self.log, self.glitch, self.never_done, self.flaky, self.block_reads = False, [], [], glitch_first_read, never_done, flaky_blocks, 0
        self.bad_count, self.bad_crc = bad_count_once, bad_crc_once

    def sample(self, ch, k, i): return (ch * 50 + k * 7 + i) & 0xFF

    def send(self, frame):
        frame = bytes(frame).rstrip(b"\0") if len(frame) > 8 + 2 * 17 + 3 else bytes(frame)
        for n in range(8, len(frame) + 1):                               # the CRC closes the frame: find where it does
            if frame[n - 2:n] == self.h.crc16(frame[:n - 2]): body = frame[:n - 2]; break
        else: raise AssertionError("a request with a bad CRC went out: %s" % frame.hex())
        self.log.append(body); self.replies = self.reply(body)

    def recv(self, n_reports=1, timeout=None): return self.replies[:n_reports]

    def exc(self, addr, fc, code): b = bytes([addr, fc | 0x80, code]); return [b + self.h.crc16(b)]

    def reply(self, body):
        addr, fc = body[0], body[1]
        reg = struct.unpack(">H", body[2:4])[0]
        if addr == 1:
            if fc == 3:
                v = {0x0085: self.tvcc, 0x0212: self.enable}.get(reg, 0)
                b = bytes([1, 3, 2]) + struct.pack(">H", v); return [b + self.h.crc16(b)]
            if fc == 6:
                val = struct.unpack(">H", body[4:6])[0]
                if reg == 0x0085: self.tvcc = val
                if reg == 0x0212:
                    self.enable = val; self.up = (val == 1 and abs(self.tvcc - 3300) < 100)
                return [bytes(body) + self.h.crc16(body)]
            if fc == 0x10:
                n = body[5]; self.gen = list(struct.unpack(">%dH" % n, body[7:7 + 2 * n]))
                b = body[:6]; return [b + self.h.crc16(b)]
        if addr == 0x10:
            if not self.up: return self.exc(0x10, fc, 3)
            if fc == 0x10:
                n = body[5]; self.cfg = list(struct.unpack(">%dH" % n, body[7:7 + 2 * n])); self.done = 0 if self.never_done else 1
                b = body[:6]; return [b + self.h.crc16(b)]
            if fc == 6:
                if reg == 0x021C: self.done = 0
                return [bytes(body) + self.h.crc16(body)]
            if fc == 3:
                n = struct.unpack(">H", body[4:6])[0]
                if reg == 0x0100 and n == 17: data = struct.pack(">17H", *self.cfg)
                elif reg == 0x021C: data = struct.pack(">H", self.done)
                elif reg == 0xC100: data = struct.pack(">8f", 114.9, 0, 212.7, 1.699, 125.55, 0, 223.4, 1.699)
                elif reg & 0xE000 in (0x2000, 0x4000) and n == 0x200:
                    ch, k = (0 if reg < 0x4000 else 1), reg & 0x3FF
                    self.block_reads += 1
                    data = bytes(self.sample(ch, k, i) for i in range(1024))
                    if self.flaky and self.block_reads % 2 == 0: data = bytes([data[0] ^ 1]) + data[1:]
                    full = bytes([0x10, 3, n & 0xFF]) + data; full += self.h.crc16(full)
                    if self.bad_crc: self.bad_crc = False; full = full[:103] + bytes([full[103] ^ 0x55]) + full[104:]   # a corrupted data byte under an unchanged CRC, once
                    return [full[:1024], full[1024:].ljust(1024, b"\0")]
                else: return self.exc(0x10, 3, 2)
                if self.glitch: self.glitch = False; return [b"\xff" * 16]            # a misframed report first, as the notes warn
                if self.bad_count:                                                      # a reply whose byte count is not what was asked for (a stale answer), once
                    self.bad_count = False; b = bytes([0x10, 3, 2, 0xDE, 0xAD]); return [b + self.h.crc16(b)]   # a stale answer to some other, one-register read
                b = bytes([0x10, 3, len(data)]) + data; return [b + self.h.crc16(b)]
        return []


def run_checks(h):
    """Every behaviour of the client that the notes rely on; returns the list of failed checks (empty when all hold)."""
    bad = []
    def check(ok, what):
        if not ok: bad.append(what)
    # framing
    check(h.read_request(1, 0xFF00, 6).hex() == "0103ff000006f5dc", "the read request is the stock example frame")
    check(h.write1_request(1, 0x0212, 2)[:6] == bytes([1, 6, 2, 0x12, 0, 2]), "write-one request layout")
    check(h.write_n_request(0x10, 0x0100, [1, 2])[:9] == bytes([0x10, 0x10, 1, 0, 0, 2, 4, 0, 1]), "block write request layout")
    check(h.f32_regs(1.0) == [int("3F80", 16), 0], "a float32 is two registers, high first")
    s = h.settings_block(12, 1, range1=6, range2=7, trig_level_v=-0.1, trig_pos=40, trig_mode=2, trig_ch=0, edge=0, chmask=3, coupling=(1, 0))
    check(len(s) == 17 and s[0] == 0 and s[1:3] == [1, 0] and s[3:5] == [6, 7] and s[7:9] == [12, 1] and s[11:16] == [40, 2, 0, 0, 3] and s[16] == 1, "settings block layout")
    check(s[9:11] == h.f32_regs(-0.1), "the trigger level sits in registers 9 and 10")
    check(h.generator_block(3, -200, 200, 1000) == [1, 3, 0xFF38, 200, 0, 1000, 50, 0, 0, 1], "generator block with a negative level and the frequency split in two words")
    check(h.generator_block(2, 0, 0, 70000)[4:6] == [1, 4464], "frequency high word")
    check(abs(h.codes_to_volts([h.ZERO_CODE[6] + h.CODES_PER_V[6] * 0.1], 6)[0] - 0.1) < 1e-9, "codes to volts inverts the range table")
    # a module that is not ready
    sim = SimTransport(h, tvcc=1400); m = h.Module(sim, sleep=lambda s: None)
    try: m.settings(); check(False, "reads at 0x10 raise while TVCC is 1.4 V")
    except h.ModuleNotReady: pass
    m.enable(); check(sim.up is False, "the enable sequence does not bring the module up at TVCC 1.4 V")
    m.set_tvcc_mv(3300); check(m.tvcc_mv() == 3300, "TVCC is read back after being set")
    # the enable sequence
    sleeps = []; sim = SimTransport(h, tvcc=3300); m = h.Module(sim, sleep=sleeps.append)
    m.enable()
    writes = [(b[2:4].hex(), b[5]) for b in sim.log if b[1] == 6]
    check(writes == [("0212", 2), ("0212", 1)] and sleeps == [1.0, 1.5] and sim.up, "enable: 0x0212 = 2, 1 s, = 1, 1.5 s, and the module is up")
    check(m.settings() == [0, 1, 1, 4, 4, 0, 0, 12, 0, 0, 0, 0, 0, 0, 1, 0, 1], "the defaults read back")
    check([round(x, 3) for x in m.status()][:4] == [114.9, 0.0, 212.7, 1.699], "the status floats decode")
    # capture
    sim = SimTransport(h, tvcc=3300); m = h.Module(sim, sleep=lambda s: None)
    x = m.capture(12, 1, range_code=6, trig_level_v=0.0, trig_pos=50, trig_mode=2)
    check(len(x) == 2 * 1024 - h.JUNK_HEAD, "a depth-1 capture is two blocks without the junk head")
    check(x[0] == sim.sample(0, 0, h.JUNK_HEAD) and x[1024 - h.JUNK_HEAD] == sim.sample(0, 1, 0) and x[-1] == sim.sample(0, 1, 1023), "blocks are read in order, from the right register")
    check(sim.cfg[7:9] == [12, 1] and sim.cfg[12] == 2, "the settings block reached the module")
    check(sim.done == 0, "the capture-done flag is acknowledged")
    ch2 = m.capture(12, 0, ch=1)
    check(ch2[0] == sim.sample(1, 0, h.JUNK_HEAD), "channel 2 is read from 0x4000")
    sim = SimTransport(h, tvcc=3300); m = h.Module(sim, sleep=lambda s: None)
    check(len(m.capture(12, 0)) == 1024 - h.JUNK_HEAD and sim.up, "a capture on a module that was not enabled enables it and goes on")
    # glitches and verification
    sim = SimTransport(h, tvcc=3300, glitch_first_read=True); m = h.Module(sim, sleep=lambda s: None); m.enable()
    check(m.settings()[7] == 12, "a misframed first report is retried")
    sim = SimTransport(h, tvcc=3300, bad_count_once=True); m = h.Module(sim, sleep=lambda s: None); m.enable()
    check(m.settings()[7] == 12, "a reply with the wrong byte count is retried")
    sim = SimTransport(h, tvcc=3300, bad_crc_once=True); m = h.Module(sim, sleep=lambda s: None); m.enable()
    check(m.capture(12, 0)[0] == sim.sample(0, 0, h.JUNK_HEAD), "a block with a bad CRC is read again")
    sim = SimTransport(h, tvcc=3300, flaky_blocks=True); m = h.Module(sim, sleep=lambda s: None); m.enable()
    try: m.capture(12, 0, verify=True); check(False, "verify catches two reads that differ")
    except h.ProtocolError: pass
    sim = SimTransport(h, tvcc=3300, never_done=True); m = h.Module(sim, sleep=lambda s: None); m.enable()
    try: m.capture(12, 0, ready_timeout=0.05); check(False, "a capture that never completes times out")
    except TimeoutError: pass
    return bad


def test_the_client_does_what_the_notes_rely_on():
    h = load(TOOL)
    assert run_checks(h) == []


@pytest.mark.parametrize("old, new, what", [
    ("c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1", "c = (c >> 1) ^ 0xA000 if c & 1 else c >> 1", "CRC polynomial"),
    ("return out[JUNK_HEAD:]", "return out[JUNK_HEAD - 1:]", "junk head length"),
    ("(REG_CH1 if ch == 0 else REG_CH2) + k", "(REG_CH1 if ch == 0 else REG_CH1) + k", "channel 2 register base"),
    ("self.write1(MODULE, REG_DONE, 1)\n        out = []", "out = []", "capture-done acknowledge"),
    ("self.write1(TOOL, REG_ENABLE, 2); self.sleep(1.0); self.write1(TOOL, REG_ENABLE, 1); self.sleep(1.5)", "self.write1(TOOL, REG_ENABLE, 1); self.sleep(1.5)", "enable cycle"),
    ("list(struct.unpack(\">2H\", struct.pack(\">f\", x)))", "list(struct.unpack(\">2H\", struct.pack(\">f\", x)))[::-1]", "float register order"),
    ("if reps[0][1] == 3 and reps[0][2] == 2 * n:", "if reps[0][1] == 3:", "reply byte count check"),
    ("except ModuleNotReady: self.enable(); self.write_n(MODULE, REG_CFG, cfg)", "except ModuleNotReady: raise", "capture enables a module that is not up"),
    ("if verify and self.block(k, ch) != b:", "if False and self.block(k, ch) != b:", "verified read-out"),
    ("full[1027:1029] == crc16(full[:1027])", "True", "block CRC check"),
    ("for _ in range(retries):", "for _ in range(1):", "retry on a misframed reply"),
    ("lo_mv & 0xFFFF, hi_mv & 0xFFFF", "lo_mv & 0x7FFF, hi_mv & 0xFFFF", "negative generator level"),
])
def test_a_fault_in_the_client_is_caught(tmp_path, old, new, what):
    src = open(TOOL, encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_250m_mut.py"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    h = load(str(bad), "h7_250m_mutant")
    try: failures = run_checks(h)
    except Exception: failures = ["raised"]
    assert failures, what
