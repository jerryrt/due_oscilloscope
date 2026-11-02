"""Board check of the H7 control function (image12+): talk to the second CDC function with the project's own host/control.py
(unchanged), then run acquisition from a control RUN with the stream port's DTR dropped. Needs sudo -n for the unit's
boot-loader-free vendor requests only if you also use h7_usb_probe; this script itself needs none.

    python h7_ctl_check.py            # exits non-zero on the first failed check
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "host")); sys.path.insert(0, HERE)
import serial
import control as ctl
import h7_ets as ets
import h7_stream_check as chk

CFG = struct.Struct("<IIBBBBHH")
STATUS = struct.Struct("<4B17I")


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond: sys.exit(1)


def main():
    with ctl.Control(chk.find_port(2)) as c:
        print("ping", c.ping())
        ident = c.identity(); print("identity", ident)
        check(ident["track"] == "h" and ident["frame_version"] == 4 and ident["ctl_version"] == 4, "identity: track h, frame version 4, control version 4")
        ops = c.capabilities(); check({0x40, 0x41, 0x42, 0x43} <= ops, f"capabilities list the H7 opcodes {sorted(hex(o) for o in ops)}")
        print("counters", c.counters())
        cfg = CFG.unpack(c.call(0x40).payload); print("config", cfg)
        want = (100, 40, 3, 0, 0, 3, 2036, 0)
        check(CFG.unpack(c.call(0x40, CFG.pack(*want)).payload) == want, "config set and read back")
        try: c.call(0x40, CFG.pack(79, 40, 3, 0, 0, 3, 2036, 0)); bad = False
        except ctl.ControlError as e: bad = e.code == 3
        check(bad, "a period under the proven 80 ticks is refused (CTL_ERR_LENGTH)")
        # acquisition from a control RUN with DTR down: open the stream port, drop DTR, count frames
        s = serial.Serial(chk.find_port(0), 115200, timeout=0.2); s.dtr = False; time.sleep(0.5)
        st = STATUS.unpack(c.call(0x43).payload); check(st[0] == 0, "not running before RUN (DTR is down)")
        check(c.call(0x41, b"\x01").payload == b"\x01", "RUN 1 accepted")
        data = bytearray(); t0 = time.time()
        while time.time() - t0 < 2.0:
            try: data += os.read(s.fd, 1 << 20)
            except OSError: time.sleep(0.01)
        st = STATUS.unpack(c.call(0x43).payload)
        planes = ets.gapless_planes(bytes(data), 2)
        check(st[0] == 1 and len(planes[0]) > 1_000_000, f"frames stream with DTR down: running {st[0]}, {len(planes[0])} samples per channel in 2 s")
        try: c.call(0x40, CFG.pack(*want)); busy = False
        except ctl.ControlError as e: busy = e.code == 5
        check(busy, "config is refused while running (CTL_ERR_BUSY)")
        check(c.call(0x41, b"\x00").payload == b"\x00", "RUN 0 accepted")
        time.sleep(0.3); st = STATUS.unpack(c.call(0x43).payload); check(st[0] == 0, "stopped after RUN 0")
        s.close()
        print("status", st)
    print("all control checks passed")


if __name__ == "__main__":
    main()
