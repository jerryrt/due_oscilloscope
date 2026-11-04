"""Read-only PICOBOOT client for an RP2040 in BOOTSEL mode (USB 2e8a:0003), for the 250M module's RP2040 (docs/23).

    sudo .venv/bin/python targets/h7tool/tools/rp2040_picoboot.py OUTDIR      # back up the whole flash, read twice, and the boot ROM

Only four requests can ever be sent: the interface reset, EXIT_XIP and ENTER_CMD_XIP (they set up how the flash is read and write nothing),
and READ. Anything that could erase, write, execute or reboot is refused in `Pico.cmd` before it reaches the bus, which is what
tests/test_rp2040_picoboot.py holds. Needs pyusb and permission to open the device (root, or a udev rule)."""
import hashlib, struct, sys, time

MAGIC = 0x431FD10B
PC_EXIT_XIP, PC_ENTER_CMD_XIP, PC_READ = 0x06, 0x07, 0x84
READ_ONLY = frozenset({PC_EXIT_XIP, PC_ENTER_CMD_XIP, PC_READ})
XIP_BASE, ROM_BASE, CHUNK = 0x10000000, 0x00000000, 4096          # the boot ROM stalls a read of 16 KB; 4 KB works


def pack_command(cid, token, args=b"", length=0, size=0):
    """The 32-byte PICOBOOT command: magic, token, command id, argument size, 0, transfer length, 16 bytes of arguments."""
    return struct.pack("<IIBBHI", MAGIC, token, cid, size, 0, length) + bytes(args).ljust(16, b"\0")


class Pico:
    def __init__(self, dev, out, inp, intf):
        self.dev, self.out, self.inp, self.n, self.token = dev, out, inp, intf, 1

    @classmethod
    def open(cls):
        import usb.core, usb.util
        dev = usb.core.find(idVendor=0x2E8A, idProduct=0x0003)
        if dev is None: raise SystemExit("no RP2040 in BOOTSEL mode (hold BOOT while connecting USB)")
        intf = next(i for i in dev.get_active_configuration() if i.bInterfaceClass == 0xFF)
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
        eps = list(intf)
        out = next(e for e in eps if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT).bEndpointAddress
        inp = next(e for e in eps if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN).bEndpointAddress
        p = cls(dev, out, inp, intf.bInterfaceNumber)
        dev.ctrl_transfer(0x41, 0x41, 0, p.n, None)                 # INTERFACE_RESET: clears any half-finished command
        return p

    def cmd(self, cid, args=b"", length=0, size=0):
        if cid not in READ_ONLY: raise ValueError("PICOBOOT command 0x%02x is refused: this tool only reads" % cid)
        self.dev.write(self.out, pack_command(cid, self.token, args, length, size), timeout=2000)
        self.token += 1
        data = b""
        if cid & 0x80 and length:
            while len(data) < length:
                data += bytes(self.dev.read(self.inp, min(length - len(data), CHUNK), timeout=4000))
            self.dev.write(self.out, b"", timeout=2000)               # the zero-length acknowledge of an IN transfer
        else:
            self.dev.read(self.inp, 64, timeout=2000)                 # the zero-length acknowledge of a command with no data
        return data

    def xip_for_reading(self):
        self.cmd(PC_EXIT_XIP); self.cmd(PC_ENTER_CMD_XIP)             # without this the flash window returns the cache's contents

    def read(self, addr, size):
        if size > CHUNK: raise ValueError("read at most %d bytes at a time" % CHUNK)
        return self.cmd(PC_READ, struct.pack("<II", addr, size), size, 8)

    def read_range(self, addr, size):
        return b"".join(self.read(addr + o, min(CHUNK, size - o)) for o in range(0, size, CHUNK))

    def flash_size(self):
        """Flash size from where the 16 MB window starts to repeat; None if it never does."""
        first = self.read(XIP_BASE, 256)
        return next(((1 << k) for k in range(18, 25) if self.read(XIP_BASE + (1 << k), 256) == first), None)


def backup(p, outdir):
    p.xip_for_reading()
    size = p.flash_size() or (16 << 20)
    a, b = p.read_range(XIP_BASE, size), p.read_range(XIP_BASE, size)
    print("flash %d KB, two reads identical: %s, sha256 %s" % (size // 1024, a == b, hashlib.sha256(a).hexdigest()))
    if a != b: raise SystemExit("the two reads differ: nothing saved")
    open("%s/module_flash_%dKB.bin" % (outdir, size // 1024), "wb").write(a)
    used = max((i for i, v in enumerate(a) if v != 0xFF), default=-1) + 1
    print("used bytes: %d (0x%x); the rest is 0xFF" % (used, used))


if __name__ == "__main__":
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    backup(Pico.open(), sys.argv[1])
