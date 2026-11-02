#!/usr/bin/env python3
"""Read the OTG_HS id/config registers from a running image4+ over the vendor
request IN 0xC0/0x01 (no pyusb: the usbdevfs control ioctl). Needs access to
/dev/bus/usb/BBB/DDD, so run it with sudo -n if the node is root-only."""
import ctypes, fcntl, os, struct, sys

VID, PID = 0x1209, 0x0001
NAMES = ["GCCFG... CID", "GSNPSID", "GHWCFG1", "GHWCFG2", "GHWCFG3", "GHWCFG4",
         "GLPMCFG", "GRXFSIZ", "DIEPTXF0"]
NAMES[0] = "CID"

class Ctrl(ctypes.Structure):
    _fields_ = [("bRequestType", ctypes.c_uint8), ("bRequest", ctypes.c_uint8),
                ("wValue", ctypes.c_uint16), ("wIndex", ctypes.c_uint16),
                ("wLength", ctypes.c_uint16), ("timeout", ctypes.c_uint32),
                ("data", ctypes.c_void_p)]

def find():
    for d in os.listdir("/sys/bus/usb/devices"):
        p = f"/sys/bus/usb/devices/{d}/"
        try:
            v = int(open(p + "idVendor").read(), 16); pr = int(open(p + "idProduct").read(), 16)
            if (v, pr) == (VID, PID):
                return "/dev/bus/usb/%03d/%03d" % (int(open(p + "busnum").read()), int(open(p + "devnum").read()))
        except OSError:
            pass
    sys.exit("no 1209:0001 device")

def main():
    fd = os.open(find(), os.O_RDWR)
    buf = ctypes.create_string_buffer(64)
    c = Ctrl(0xC0, 0x01, 0, 0, 36, 1000, ctypes.cast(buf, ctypes.c_void_p).value)
    USBDEVFS_CONTROL = 0xC0185500
    n = fcntl.ioctl(fd, USBDEVFS_CONTROL, c)
    for name, w in zip(NAMES, struct.unpack("<9I", buf.raw[:36])):
        print(f"{name:9s} 0x{w:08X}")
    # decode a few fields (STM32 OTG_HS / Synopsys DWC2 layout; RM0433 *(check)*)
    w = struct.unpack("<9I", buf.raw[:36])
    g2, g3, g4 = w[3], w[4], w[5]
    print("num_dev_ep      ", (g2 >> 10) & 0xF, "(excluding EP0)")
    print("arch (dma)      ", (g2 >> 3) & 3, "(2 = internal DMA)")
    print("dfifo depth     ", g3 >> 16, "words")
    print("num_in_eps      ", ((g4 >> 26) & 0xF), "+1 (g4 bits 29:26: in eps excl. EP0)")
    print("dedicated tx fifo", (g4 >> 25) & 1)

main()
