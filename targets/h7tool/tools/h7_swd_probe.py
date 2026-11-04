"""Read-only SWD check (docs/23) through the H7-TOOL's CMSIS-DAP (HID interface 1): is an RP2040 answering on the SWD pins?
Sends: DAP_Info, DAP_Connect(SWD), clock, line reset + JTAG-to-SWD + line reset, TARGETSEL for RP2040 core 0, then reads the DP IDCODE.
Writes nothing to the target apart from the DP TARGETSEL/select handshake; no memory or flash access.
Needs the stock app running (it serves CMSIS-DAP on HID interface 1) and read access to the hidraw node.

    python3 tools/h7_swd_probe.py
"""
import glob, os, select, struct, sys, time
def find_hidraw(iface):
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        p = os.path.realpath(d + "/device"); tag = os.path.basename(p).upper()
        if "C251" in tag and "F00A" in tag and (":1.%d/" % iface) in p + "/": return "/dev/" + os.path.basename(d)
    raise SystemExit("CMSIS-DAP HID interface %d not found" % iface)
fd = os.open(find_hidraw(1), os.O_RDWR | os.O_NONBLOCK)
def xfer(b):
    while select.select([fd], [], [], 0)[0]: os.read(fd, 128)
    os.write(fd, bytes(b).ljust(64, b"\0"))
    t0 = time.time()
    while time.time() - t0 < 1.0:
        if select.select([fd], [], [], 0.1)[0]: return os.read(fd, 128)
    return None
def seq(bits, data):                                   # DAP_SWJ_Sequence
    return xfer([0x12, bits] + list(data))
info = xfer([0x00, 0x01]); print("DAP vendor:", info[2:2 + info[1]] if info else None)
info = xfer([0x00, 0x02]); print("DAP product:", info[2:2 + info[1]] if info else None)
print("connect(SWD):", list(xfer([0x02, 0x01])[:2]))
print("swj clock 1 MHz:", list(xfer([0x11] + list(struct.pack("<I", 1000000)))[:2]))
print("transfer cfg:", list(xfer([0x04, 0x00, 0x80, 0x00, 0x00, 0x00])[:2]))
print("swd cfg:", list(xfer([0x13, 0x00])[:2]))
ones7 = [0xFF] * 7
seq(56, ones7); seq(16, [0x9E, 0xE7]); seq(56, ones7); seq(8, [0x00])            # line reset, JTAG-to-SWD, line reset, idle
# TARGETSEL write (DP 0xC) = 0x01002927 for RP2040 core 0: request 0x99, 5 don't-care bits, 32 data bits, parity (even -> 0)
data = struct.pack("<I", 0x01002927)
seq(8, [0x99]); seq(5, [0x00]); seq(33, list(data) + [0x00]); seq(8, [0x00])
# DAP_Transfer: one DP read of register 0 (IDCODE): request byte = RnW(1) | A[3:2]=0 -> 0x02
r = xfer([0x05, 0x00, 0x01, 0x02])
print("DAP_Transfer reply:", list(r[:8]) if r else None)
if r and r[0] == 0x05 and r[1] == 1:
    ack = r[2] & 7
    print("ACK =", {1: "OK", 2: "WAIT", 4: "FAULT", 7: "no target / protocol error"}.get(ack, ack))
    if ack == 1: print("DP IDCODE = 0x%08X" % struct.unpack("<I", bytes(r[3:7]))[0], "(RP2040 DP is 0x0BC12477)")
xfer([0x03])                                                                      # DAP_Disconnect
