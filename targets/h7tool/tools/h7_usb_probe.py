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

def stats(fd):
    buf = ctypes.create_string_buffer(64)
    c = Ctrl(0xC0, 0x02, 0, 0, 24, 1000, ctypes.cast(buf, ctypes.c_void_p).value)
    fcntl.ioctl(fd, 0xC0185500, c)
    w = struct.unpack('<6I', buf.raw[:24])
    print('next_seq=%d xfers=%d running=%d ms=%d starts=%d DIEPINT2=0x%X' % w)

def clocks(fd):
    buf = ctypes.create_string_buffer(64)
    c = Ctrl(0xC0, 0x03, 0, 0, 32, 1000, ctypes.cast(buf, ctypes.c_void_p).value)
    fcntl.ioctl(fd, 0xC0185500, c)
    cyc, t5, t2, n, win, hz, sws, st = struct.unpack('<8I', buf.raw[:32])
    print(f'windows={win} sofs/window={n} cpu_hz(set)={hz} SWS={sws} pll={st}')
    if win:
        print(f'  cycles/window {cyc}  TIM5 {t5}  TIM2(TIM3 update) {t2}')
        print(f'  ratio to nominal (400e6, 200e6, 1e6 per 8000 SOFs): '
              f'{cyc/400e6:.7f} {t5/200e6:.7f} {t2/1e6:.7f}')

def acq(fd):
    buf = ctypes.create_string_buffer(64)
    c = Ctrl(0xC0, 0x04, 0, 0, 48, 1000, ctypes.cast(buf, ctypes.c_void_p).value)
    fcntl.ioctl(fd, 0xC0185500, c)
    names = "frames_done lost sent xfers tc_missed adc_ovr rev_id starts ct_bad period adc_clk_hz chmask".split()
    print(" ".join(f"{k}={v:#x}" if k == "rev_id" else f"{k}={v}"
                   for k, v in zip(names, struct.unpack('<12I', buf.raw[:48]))))

def rate(fd, hz):
    period = round(200e6 / hz)
    c = Ctrl(0x40, 0x10, period & 0xFFFF, period >> 16, 0, 1000, None)
    fcntl.ioctl(fd, 0xC0185500, c)
    print(f"period {period} ticks = {200e6 / period:.1f} sps")

def adcx(fd, smpr, cont, ckmode, presc):
    c = Ctrl(0x40, 0x11, smpr, cont | (ckmode << 1) | (presc << 3), 0, 1000, None)
    fcntl.ioctl(fd, 0xC0185500, c)

def main():
    fd = os.open(find(), os.O_RDWR)
    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        return stats(fd)
    if len(sys.argv) > 1 and sys.argv[1] == 'pins':
        buf = ctypes.create_string_buffer(64)
        fcntl.ioctl(fd, 0xC0185500, Ctrl(0xC0, 0x05, 0, 0, 36, 1000, ctypes.cast(buf, ctypes.c_void_p).value))
        w = struct.unpack('<9I', buf.raw[:36])
        print('GPIOG MODER %08X ODR %08X IDR %08X OSPEEDR %08X' % w[0:4])
        print('GPIOI MODER %08X ODR %08X IDR %08X OSPEEDR %08X' % w[4:8])
        print('RCC_AHB4ENR %08X' % w[8]); return
    if len(sys.argv) > 1 and sys.argv[1] == 'gen':
        buf = ctypes.create_string_buffer(64)
        fcntl.ioctl(fd, 0xC0185500, Ctrl(0xC0, 0x06, 0, 0, 40, 1000, ctypes.cast(buf, ctypes.c_void_p).value))
        n = 'on PE3 DAC_CR DOR1 NDTR TIM6CNT period center amp type'.split()
        print(' '.join(f'{k}={v:#x}' if k == 'DAC_CR' else f'{k}={v}' for k, v in zip(n, struct.unpack('<10I', buf.raw[:40])))); return
    if len(sys.argv) > 3 and sys.argv[1] == 'wave':      # wave <type> <amp codes>
        return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x20, int(sys.argv[2]), int(sys.argv[3]), 0, 3000, None))
    if len(sys.argv) > 2 and sys.argv[1] == 'gperiod':
        p = int(sys.argv[2]); return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x21, p & 0xFFFF, p >> 16, 0, 1000, None))
    if len(sys.argv) > 2 and sys.argv[1] == 'gcenter':
        return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x22, int(sys.argv[2]), 0, 0, 1000, None))
    if len(sys.argv) > 2 and sys.argv[1] == 'pc3':
        return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x14, int(sys.argv[2]), 0, 0, 1000, None))
    if len(sys.argv) > 2 and sys.argv[1] == 'chan':
        return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x13, int(sys.argv[2]), 0, 0, 1000, None))
    if len(sys.argv) > 2 and sys.argv[1] == 'fe':
        return fcntl.ioctl(fd, 0xC0185500, Ctrl(0x40, 0x12, int(sys.argv[2], 0), 0, 0, 1000, None))
    if len(sys.argv) > 5 and sys.argv[1] == 'adcx':
        return adcx(fd, *map(int, sys.argv[2:6]))
    if len(sys.argv) > 1 and sys.argv[1] == 'acq':
        return acq(fd)
    if len(sys.argv) > 2 and sys.argv[1] == 'rate':
        return rate(fd, float(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == 'clocks':
        return clocks(fd)
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
