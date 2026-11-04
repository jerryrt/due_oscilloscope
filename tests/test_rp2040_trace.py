"""tools/rp2040_trace.py: the register naming, the PIO instruction decoder and the summary of a register-write log, which are pure and tested here with
encodings checked by hand against the RP2040 datasheet. The emulation itself needs `unicorn` and the module's flash backup (outside the repo): its test
SKIPS with that reason, and a skip there is not a pass."""
import os, shutil, subprocess, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "targets", "h7tool", "tools", "rp2040_trace.py")
sys.path.insert(0, os.path.dirname(TOOL))
import rp2040_trace as rt

BACKUP = os.path.expanduser("~/MCU.Projects/h7tool_backup/rp2040_module/module_flash_2048KB.bin")
ROM = os.path.expanduser("~/MCU.Projects/h7tool_backup/rp2040_module/rp2040_bootrom_16KB_partial.bin")


@pytest.mark.parametrize("word, text", [
    ("4010", "in pins, 16"), ("4001", "in pins, 1"), ("4000", "in pins, 32"), ("E081", "set pindirs, 1"), ("E000", "set pins, 0"), ("80A0", "pull block"),
    ("6040", "out y, 32"), ("A022", "mov x, y"), ("0054", "jmp x-- 20"), ("C020", "irq wait 0"), ("201D", "wait 0 gpio 29"), ("2092", "wait 1 gpio 18"),
    ("00D2", "jmp pin 18"), ("6001", "out pins, 1"), ("8000", "push noblock"), ("8020", "push block"),
])
def test_pio_words_decode_to_the_instruction_they_encode(word, text):
    assert rt.decode_pio(int(word, 16)) == text


def test_the_delay_and_side_set_bits_do_not_change_the_instruction():
    assert rt.decode_pio(int("3819", 16)) == rt.decode_pio(int("2019", 16)) == "wait 0 gpio 25"


@pytest.mark.parametrize("addr, name", [
    (0x40014004 + 8 * 21, "IO_BANK0.GPIO21_CTRL"), (0x40014000, "IO_BANK0.GPIO0_STATUS"), (0x4001C004 + 4 * 29, "PADS_BANK0.GPIO29"),
    (0x50200048 + 4 * 30, "PIO0.INSTR_MEM30"), (0x50300000 + 0xC8 + 0x18 + 20, "PIO1.SM1_PINCTRL"), (0x50200000 + 0xC8, "PIO0.SM0_CLKDIV"),
    (0xD0000024, "SIO.GPIO_OE_SET"), (0x50000000 + 0x40 * 3 + 4, "DMA.CH3_WRITE_ADDR"), (0x40028008, "PLL_SYS+0x8"), (0x12345678, "0x12345678"),
])
def test_register_addresses_get_their_names(addr, name):
    assert rt.reg_name(addr) == name


def synthetic_log():
    w = lambda a, n: (0, "w", a, 0, n)
    log = [w(0x40028008, 125), w(0x4002800C, 0x32000)]                              # 12 MHz x 125 / (3 x 2)
    log += [w(0x40014004 + 8 * 16, 7), w(0x4001C004 + 4 * 16, 0x40), w(0x40014004 + 8 * 20, 5), w(0xD0000024, 1 << 20)]
    log += [w(0x50300048 + 4 * 30, 0x4001), w(0x50300048 + 4 * 31, 0x00DA), w(0x50300000 + 0xC8 + 0x14, 19 | (1 << 20) | (16 << 15))]
    log += [w(0x50300000 + 0xC8, (125 << 16) | (128 << 8))]
    log += [w(0x50000000 + 0x40 * 2, 0x50200020), w(0x50000000 + 0x40 * 2 + 4, 0x20010000), w(0x50000000 + 0x40 * 2 + 8, 16384)]
    return log


def test_the_summary_reports_clock_pins_programs_and_dma():
    s = "\n".join(rt.summarize(synthetic_log()))
    assert "PLL_SYS: 12 MHz x 125 / (3 x 2) = 250.0 MHz" in s
    assert "GPIO16 funcsel=PIO1" in s and "GPIO20 funcsel=SIO" in s and "SIO outputs enabled: [20]" in s
    assert "30: 4001  in pins, 1" in s and "31: 00da  jmp pin 26" in s
    assert "in_base 16" in s and "out_base 19 x1" in s and "clkdiv=125.500" in s and "GPIO16 funcsel=PIO1 pad=0x40 [IE ]" in s
    assert "DMA ch2: read 0x50200020 write 0x20010000 count 16384" in s


@pytest.mark.parametrize("old, new, what", [
    ('{0: "XIP", 1: "SPI", 2: "UART", 3: "I2C", 4: "PWM", 5: "SIO", 6: "PIO0", 7: "PIO1"', '{0: "XIP", 1: "SPI", 2: "UART", 3: "I2C", 4: "PWM", 5: "SIO", 6: "PIO1", 7: "PIO0"', "PIO function numbers swapped"),
    ("12.0 * fb / (d1 * d2)", "12.0 * fb / (d1 + d2)", "PLL arithmetic"),
    ("(prim >> 16) & 7, (prim >> 12) & 7", "(prim >> 17) & 7, (prim >> 12) & 7", "post-divider 1 field position"),
    ('if op == 2: return "in %s, %d"', 'if op == 3: return "in %s, %d"', "PIO in opcode"),
    ("0x4001C004 + 4 * n", "0x4001C000 + 4 * n", "pad register base"),
    ("(cd >> 16) + ((cd >> 8) & 255) / 256.0", "(cd >> 16)", "clock divider fraction"),
    ("in_base %d\" % (pcr & 31", "in_base %d\" % ((pcr >> 5) & 31", "PINCTRL field"),
])
def test_a_fault_in_the_trace_summary_is_caught(tmp_path, old, new, what):
    src = open(TOOL, encoding="utf-8").read()
    assert src.count(old) >= 1, what
    bad = tmp_path / "rp2040_trace_mut.py"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    ns = {"__name__": "mut"}
    exec(compile(bad.read_text(encoding="utf-8"), str(bad), "exec"), ns)
    broken = False
    try:
        s = "\n".join(ns["summarize"](synthetic_log()))
        broken = not ("250.0 MHz" in s and "GPIO16 funcsel=PIO1" in s and "in_base 16" in s and "30: 4001  in pins, 1" in s and "SIO outputs enabled: [20]" in s
                      and "out_base 19 x1" in s and "clkdiv=125.500" in s and "GPIO16 funcsel=PIO1 pad=0x40 [IE ]" in s)
        broken |= ns["decode_pio"](int("4010", 16)) != "in pins, 16" or ns["reg_name"](0x4001C004 + 4 * 29) != "PADS_BANK0.GPIO29"
    except Exception:
        broken = True
    assert broken, what


@pytest.mark.skipif(not (os.path.exists(BACKUP) and os.path.exists(ROM)), reason="the module's flash and boot ROM backups are not on this machine; this skip is NOT a pass")
def test_the_emulation_reaches_the_clock_setup_of_the_real_image():
    pytest.importorskip("unicorn", reason="unicorn is not installed in this venv; this skip is NOT a pass")
    log, pc, why = rt.emulate(BACKUP, ROM, budget=2_000_000)
    s = "\n".join(rt.summarize(log))
    assert "PLL_SYS: 12 MHz x 125 / (3 x 2) = 250.0 MHz" in s, s[:400]
