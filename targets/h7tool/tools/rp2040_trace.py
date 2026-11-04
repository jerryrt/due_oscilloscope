"""What an RP2040 firmware image configures at start-up: run it in an emulator and report the pins, clocks, PIO programs and DMA it sets up (docs/23).

    python3 targets/h7tool/tools/rp2040_trace.py FLASH.bin [BOOTROM.bin] [--budget N] [--log log.json]

FLASH.bin is the QSPI flash from 0x10000000 (tools/rp2040_picoboot.py backs it up); BOOTROM.bin is optional and only needs the first 8 KB. Needs the
`unicorn` package (not a project requirement: install it in a scratch venv). The emulation is a start-up trace, not a model of the chip: peripheral
registers are plain memory with the set/clear/xor aliases; the "is it ready" reads the SDK waits on (resets done, crystal stable, PLL locked, clock
mux selected, timer and SysTick moving, spinlocks, DMA idle) are answered; SysTick is delivered as a function call at intervals. It stops when the
code sits waiting for something outside. The pure functions below (reg_name, decode_pio, summarize) work on a log of (pc, kind, address, old, new)."""
import json, struct, sys, collections

FUNC = {0: "XIP", 1: "SPI", 2: "UART", 3: "I2C", 4: "PWM", 5: "SIO", 6: "PIO0", 7: "PIO1", 8: "CLK", 9: "USB", 31: "none"}
BLOCKS = [(0x40004000, "SYSCFG"), (0x40008000, "CLOCKS"), (0x4000C000, "RESETS"), (0x40014000, "IO_BANK0"), (0x40018000, "TBMAN"), (0x4001C000, "PADS_BANK0"),
          (0x40024000, "XOSC"), (0x40028000, "PLL_SYS"), (0x4002C000, "PLL_USB"), (0x40034000, "UART0"), (0x40038000, "UART1"), (0x4003C000, "SPI0"),
          (0x40040000, "SPI1"), (0x40044000, "I2C0"), (0x40048000, "I2C1"), (0x4004C000, "ADC"), (0x40050000, "PWM"), (0x40054000, "TIMER"),
          (0x40058000, "WATCHDOG"), (0x4005C000, "RTC"), (0x40060000, "ROSC"), (0x40064000, "VREG"), (0x50000000, "DMA"), (0x50100000, "USBCTRL"),
          (0x50200000, "PIO0"), (0x50300000, "PIO1"), (0xD0000000, "SIO"), (0xE0000000, "PPB")]
PIO_SM_REGS = {0: "CLKDIV", 4: "EXECCTRL", 8: "SHIFTCTRL", 12: "ADDR", 16: "INSTR", 20: "PINCTRL"}
SIO_REGS = {0x04: "GPIO_IN", 0x10: "GPIO_OUT", 0x14: "GPIO_OUT_SET", 0x18: "GPIO_OUT_CLR", 0x1C: "GPIO_OUT_XOR", 0x20: "GPIO_OE", 0x24: "GPIO_OE_SET",
            0x28: "GPIO_OE_CLR", 0x2C: "GPIO_OE_XOR"}


def reg_name(a):
    """A register address as BLOCK.NAME where the block's layout is known, else BLOCK+offset or the bare address."""
    for b, n in sorted(BLOCKS, reverse=True):
        if b <= a < b + 0x4000 or (n in ("PIO0", "PIO1", "DMA", "PPB") and b <= a < b + 0x100000):
            off = a - b
            if n == "IO_BANK0" and off < 0xF0: return "IO_BANK0.GPIO%d_%s" % (off // 8, "STATUS" if off % 8 == 0 else "CTRL")
            if n == "PADS_BANK0" and 4 <= off <= 0x78: return "PADS_BANK0.GPIO%d" % ((off - 4) // 4)
            if n in ("PIO0", "PIO1"):
                if off == 0: return n + ".CTRL"
                if 0x10 <= off <= 0x1C: return n + ".TXF%d" % ((off - 0x10) // 4)
                if 0x48 <= off <= 0xC4: return n + ".INSTR_MEM%d" % ((off - 0x48) // 4)
                if 0xC8 <= off < 0x128: return n + ".SM%d_%s" % ((off - 0xC8) // 0x18, PIO_SM_REGS[(off - 0xC8) % 0x18])
            if n == "PWM" and off < 0xA0: return "PWM.CH%d_%s" % (off // 0x14, {0: "CSR", 4: "DIV", 8: "CTR", 12: "CC", 16: "TOP"}[off % 0x14])
            if n == "SIO": return "SIO." + SIO_REGS.get(off, "+0x%x" % off)
            if n == "DMA" and off < 0x300: return "DMA.CH%d_%s" % (off // 0x40, {0: "READ_ADDR", 4: "WRITE_ADDR", 8: "TRANS_COUNT", 12: "CTRL_TRIG"}.get(off % 0x40, "+0x%x" % (off % 0x40)))
            return "%s+0x%x" % (n, off)
    return "0x%08x" % a


def decode_pio(w):
    """One PIO instruction word as text (the delay/side-set bits 12:8 are not shown)."""
    op = w >> 13
    if op == 0: return "jmp %s %d" % (["", "!x", "x--", "!y", "y--", "x!=y", "pin", "!osre"][(w >> 5) & 7], w & 31)
    if op == 1: return "wait %d %s %d" % ((w >> 7) & 1, ["gpio", "pin", "irq", "?"][(w >> 5) & 3], w & 31)
    if op == 2: return "in %s, %d" % (["pins", "x", "y", "null", "?", "?", "isr", "osr"][(w >> 5) & 7], (w & 31) or 32)
    if op == 3: return "out %s, %d" % (["pins", "x", "y", "null", "pindirs", "pc", "isr", "exec"][(w >> 5) & 7], (w & 31) or 32)
    if op == 4: return ("pull" if (w >> 7) & 1 else "push") + (" ifempty/iffull" if (w >> 6) & 1 else "") + (" block" if (w >> 5) & 1 else " noblock")
    if op == 5: return "mov %s, %s%s" % (["pins", "x", "y", "?", "exec", "pc", "isr", "osr"][(w >> 5) & 7], ["", "~", "::", "?"][(w >> 3) & 3], ["pins", "x", "y", "null", "?", "status", "isr", "osr"][w & 7])
    if op == 6: return "irq %s %d%s" % ("clear" if (w >> 6) & 1 else ("wait" if (w >> 5) & 1 else "set"), w & 7, " rel" if w & 16 else "")
    return "set %s, %d" % (["pins", "x", "y", "?", "pindirs", "?", "?", "?"][(w >> 5) & 7], w & 31)


def summarize(log):
    """Lines describing the final configuration a log of register writes leaves: clock, pin functions and pads, outputs, PIO, PWM, DMA, interrupts."""
    out, state = [], {}
    for pc, k, a, o, n in log: state[a] = n
    g = lambda a, d=None: state.get(a, d)
    out.append("== system clock ==")
    fb, prim = g(0x40028008), g(0x4002800C)
    if fb and prim:
        d1, d2 = (prim >> 16) & 7, (prim >> 12) & 7
        out.append("PLL_SYS: 12 MHz x %d / (%d x %d) = %.1f MHz" % (fb, d1, d2, 12.0 * fb / (d1 * d2)))
    out.append("== GPIO functions and pads ==")
    for n in range(30):
        ctrl, pad = g(0x40014004 + 8 * n), g(0x4001C004 + 4 * n)
        if ctrl is None and pad is None: continue
        s = "GPIO%d funcsel=%s" % (n, FUNC.get(ctrl & 31, ctrl & 31) if ctrl is not None else "?")
        if pad is not None: s += " pad=0x%02x [%s%s%s%s]" % (pad, "IE " if pad & 0x40 else "", "OD " if pad & 0x80 else "", "PU " if pad & 8 else "", "PD " if pad & 4 else "")
        out.append(s)
    oe = 0
    for pc, k, a, o, n in log:
        if a == 0xD0000020: oe = n
        elif a == 0xD0000024: oe |= n
        elif a == 0xD0000028: oe &= ~n
        elif a == 0xD000002C: oe ^= n
    out.append("SIO outputs enabled: %s" % [i for i in range(30) if oe >> i & 1])
    for pio, base in (("PIO0", 0x50200000), ("PIO1", 0x50300000)):
        mem = {i: g(base + 0x48 + 4 * i) for i in range(32) if g(base + 0x48 + 4 * i) is not None}
        if not mem: continue
        out.append("== %s program (%d words) ==" % (pio, len(mem)))
        for i in sorted(mem): out.append("%2d: %04x  %s%s" % (i, mem[i], decode_pio(mem[i]), "  [delay/side 0x%02x]" % ((mem[i] >> 8) & 31) if (mem[i] >> 8) & 31 else ""))
        out.append("%s CTRL 0x%x IRQ0_INTE 0x%x IRQ1_INTE 0x%x" % (pio, g(base, 0), g(base + 0x12C, 0), g(base + 0x138, 0)))
        for sm in range(4):
            o = base + 0xC8 + 0x18 * sm
            cd, ex, sh, pcr = g(o), g(o + 4), g(o + 8), g(o + 0x14)
            if cd is None and ex is None and sh is None and pcr is None: continue
            s = "SM%d:" % sm
            if cd is not None: s += " clkdiv=%.3f" % ((cd >> 16) + ((cd >> 8) & 255) / 256.0)
            if ex is not None: s += " wrap %d..%d jmp_pin %d" % ((ex >> 7) & 31, (ex >> 12) & 31, (ex >> 24) & 31)
            if sh is not None: s += " autopush %d/%d autopull %d/%d" % ((sh >> 16) & 1, ((sh >> 20) & 31) or 32, (sh >> 17) & 1, ((sh >> 25) & 31) or 32)
            out.append(s)
            if pcr is not None: out.append("    PINCTRL: out_base %d x%d, set_base %d x%d, sideset_base %d x%d, in_base %d" % (pcr & 31, (pcr >> 20) & 63, (pcr >> 5) & 31, (pcr >> 26) & 7, (pcr >> 10) & 31, (pcr >> 29) & 7, (pcr >> 15) & 31))
    out.append("== DMA ==")
    for ch in range(12):
        b = 0x50000000 + 0x40 * ch
        if g(b) is not None or g(b + 4) is not None: out.append("DMA ch%d: read 0x%08x write 0x%08x count %s" % (ch, g(b, 0), g(b + 4, 0), g(b + 8)))
    out.append("NVIC ISER 0x%x" % g(0xE000E100, 0))
    return out


def emulate(flash_path, rom_path=None, budget=60_000_000):
    """Run the image from its reset vector (the boot stage is skipped) and return (log, final_pc, why_it_stopped)."""
    from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
    from unicorn.arm_const import (UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_CPSR, UC_ARM_REG_R0)
    flash = open(flash_path, "rb").read()
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    uc.mem_map(0x0, 0x4000)
    if rom_path: uc.mem_write(0x0, open(rom_path, "rb").read()[:0x4000])
    uc.mem_map(0x10000000, 0x200000); uc.mem_write(0x10000000, flash.ljust(0x200000, b"\xff")[:0x200000])
    for base, size in ((0x20000000, 0x42000), (0x40000000, 0x80000), (0x50000000, 0x400000), (0xD0000000, 0x1000), (0xE0000000, 0x100000), (0x30000000, 0x1000)):
        uc.mem_map(base, size)
    log, locked, timer, last_pc = [], set(), [0], [0]
    rd = lambda a: struct.unpack("<I", bytes(uc.mem_read(a, 4)))[0]
    wr = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
    periph = lambda a: (0x40000000 <= a < 0x40080000) or (0x50000000 <= a < 0x50400000) or (0xD0000000 <= a < 0xD0001000) or (0xE0000000 <= a < 0xE0100000)

    def on_write(u, access, addr, size, value, ud):
        if not periph(addr): return
        if 0xD0000100 <= addr < 0xD0000180: locked.discard((addr - 0xD0000100) // 4)
        base, alias = addr, 0
        if (0x40000000 <= addr < 0x40080000) or (0x50000000 <= addr < 0x50400000): alias, base = (addr >> 12) & 3, addr & ~0x3000
        pc = uc.reg_read(UC_ARM_REG_PC)
        if size == 4:
            old = rd(base)
            new = (value & 0xFFFFFFFF, old ^ value, old | value, old & ~value)[alias] & 0xFFFFFFFF
            wr(base, new); log.append((pc, "w", base, old, new))
        else:
            cur = bytearray(uc.mem_read(base & ~3, 4)); off = addr & 3
            cur[off:off + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
            uc.mem_write(base & ~3, bytes(cur)); log.append((pc, "w%d" % size, base, None, struct.unpack("<I", bytes(cur))[0]))

    def on_read(u, access, addr, size, value, ud):
        if addr == 0x4000C008: wr(addr, 0xFFFFFFFF)                                  # RESETS.RESET_DONE
        elif addr == 0x40024004: wr(addr, 0x80001000)                                # XOSC stable
        elif addr in (0x40028000, 0x4002C000): wr(addr, rd(addr) | 0x80000000)       # PLL lock
        elif addr == 0x40008038: wr(addr, 1 << (rd(0x40008030) & 3))                 # CLK_REF_SELECTED, one-hot from CTRL.SRC
        elif addr == 0x40008044: wr(addr, 1 << (rd(0x4000803C) & 1))                 # CLK_SYS_SELECTED
        elif addr in (0x4005400C, 0x40054028, 0x40054024, 0x40054008, 0x40054004): timer[0] += 997; wr(addr, timer[0])
        elif addr in (0x50200004, 0x50300004): wr(addr, 0x0F000F00)                  # PIO FSTAT: all RX empty, all TX empty
        elif addr == 0xD0000000: wr(addr, 0)                                         # CPUID
        elif 0xD0000100 <= addr < 0xD0000180:                                        # spinlock: a read takes a free one
            n = (addr - 0xD0000100) // 4
            if n in locked: wr(addr, 0)
            else: locked.add(n); wr(addr, 1 << n)
        elif addr == 0x50000444: wr(addr, 0)                                         # DMA CHAN_ABORT done
        elif 0x50000000 <= addr < 0x50000300 and (addr & 0x3F) in (0x0C, 0x10, 0x14, 0x18, 0x1C, 0x24, 0x28, 0x2C): wr(addr, rd(addr) & ~(1 << 24))   # DMA not busy
        elif addr == 0xE000E018:                                                     # SysTick counts down on every read
            reload = rd(0xE000E014) & 0xFFFFFF or 0xFFFFFF; wr(addr, ((rd(addr) or reload) - 997) % (reload + 1))

    for lo, hi in ((0x40000000, 0x40080000), (0x50000000, 0x50400000), (0xD0000000, 0xD0001000), (0xE0000000, 0xE0100000)):
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write, None, lo, hi - 1); uc.hook_add(UC_HOOK_MEM_READ, on_read, None, lo, hi - 1)
    sp, reset = struct.unpack_from("<II", flash, 0x100)
    systick = struct.unpack_from("<I", flash, 0x100 + 15 * 4)[0] & ~1
    uc.reg_write(UC_ARM_REG_SP, sp)
    regs = [UC_ARM_REG_R0 + i for i in range(13)] + [UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR]
    total, stuck, last_n, cur, why = 0, 0, 0, reset | 1, "budget"
    try:
        while total < budget:
            uc.emu_start(cur, 0, count=20000); total += 20000
            cur = uc.reg_read(UC_ARM_REG_PC) | 1
            if rd(0xE000E010) & 3 == 3:                                              # SysTick enabled with its interrupt: deliver one as a call
                saved = [uc.reg_read(r) for r in regs]
                uc.reg_write(UC_ARM_REG_LR, 0x30000001)
                try: uc.emu_start(systick | 1, 0x30000000, count=200000)
                except UcError: pass
                for r, v in zip(regs, saved): uc.reg_write(r, v)
            stuck = stuck + 1 if len(log) == last_n else 0
            last_n = len(log)
            if stuck >= 60: why = "waiting for something outside (no register writes for %d instructions)" % (stuck * 20000); break
    except UcError as e:
        why = "emulation error: %s" % e
    return log, uc.reg_read(UC_ARM_REG_PC), why


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    budget = int(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 60_000_000
    if "--budget" in sys.argv: args.remove(sys.argv[sys.argv.index("--budget") + 1])
    logfile = sys.argv[sys.argv.index("--log") + 1] if "--log" in sys.argv else None
    if logfile: args.remove(logfile)
    if not args: raise SystemExit(__doc__)
    log, pc, why = emulate(args[0], args[1] if len(args) > 1 else None, budget)
    if logfile: json.dump(log, open(logfile, "w"))
    print("\n".join(summarize(log)))
    print("\nstopped at pc 0x%08x after %d register writes: %s" % (pc, len(log), why))
