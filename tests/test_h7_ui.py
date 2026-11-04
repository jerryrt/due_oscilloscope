"""The H7 display, backlight and LED driver (targets/h7tool/fw/ui/h7_ui.c) built for the host against a fake register
file. A sniffer decodes the hand-clocked SPI the panel would see and a model of the I2C expander answers the soft I2C,
so the test checks the bytes and the pins the driver produces against the values docs/22 records, from the boot
loader's code and from the runs on the unit. It cannot show the glass lights up; it shows the driver says what the
unit was observed to accept, and that it never touches PH9 (the buzzer) or PG1. Needs a host C compiler; without one
every test here SKIPS, which is not a pass (docs/testing.md).

The expected values are written out below on purpose and are not read from the driver. The mutation test at the end
changes one byte of the driver's initialisation table and requires the comparison to fail."""
import os
import shutil
import subprocess

import pytest

import pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, "targets", "h7tool", "fw", "ui")
HARNESS = os.path.join(ROOT, "tests", "h7ui", "harness.c")
CC = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(CC is None, reason="no host C compiler: this skip is NOT a pass")

# The boot loader's model 0/1 table (docs/22), command then data, with MADCTL 0xC0 and the three closing commands.
INIT = [
    (0x36, [0xC0]), (0x3A, [0x05]), (0xB2, [0x0C, 0x0C, 0x00, 0x33, 0x33]), (0xB7, [0x35]), (0xBB, [0x19]),
    (0xC0, [0x2C]), (0xC2, [0x01]), (0xC3, [0x12]), (0xC4, [0x20]), (0xC6, [0x0F]), (0xD0, [0xA4, 0xA1]),
    (0xE0, [0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23]),
    (0xE1, [0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23]),
    (0x21, []), (0x11, []), (0x29, []),
]


def build(tmp, src=None, hw=1):
    src = src or os.path.join(FW, "h7_ui.c")
    exe = os.path.join(tmp, "h7ui_harness_%d" % hw)
    subprocess.run([CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-DH7UI_HOST", "-DH7UI_HW_SPI=%d" % hw, "-I" + FW,
                    "-o", exe, HARNESS, src], check=True)
    return exe


# Both ways of reaching the panel (the SPI5 peripheral and the hand-clocked pins) must send the same bytes, so every
# test below runs against each.
@pytest.fixture(scope="module", params=[1, 0], ids=["spi5", "bitbang"])
def exe(request, tmp_path_factory):
    return build(str(tmp_path_factory.mktemp("h7ui")), hw=request.param)


def run(exe, scenario):
    out = subprocess.run([exe, scenario], check=True, capture_output=True, text=True, timeout=pacing.NORMAL).stdout.splitlines()
    bad = [l for l in out if l.startswith("BAD")]
    assert not bad, bad                            # the fake peripheral objects to a misuse in words
    assert "forbidden 0" in out
    if scenario != "spi_stuck":
        assert "spi_errors 0" in out
    return out


def spi(out):
    """[(is_data, byte)] in order, from the 'S C xx' and 'S D xx' lines."""
    return [(l[2] == "D", int(l[4:], 16)) for l in out if l.startswith("S ")]


def commands(stream):
    """Group a sniffed stream into [(command, [data...])]."""
    groups = []
    for is_data, b in stream:
        if is_data:
            assert groups, "data byte before any command"
            groups[-1][1].append(b)
        else:
            groups.append((b, []))
    return groups


def i2c(out):
    return [l for l in out if l.startswith("I ")]


def test_init_sends_the_boot_loaders_table_in_order(exe):
    out = run(exe, "lcd_init")
    assert commands(spi(out)) == INIT
    assert "forbidden 0" in out


def test_init_waits_the_panels_start_up_times(exe):
    out = run(exe, "lcd_init")
    us = int([l for l in out if l.startswith("delay_us")][0].split()[1])
    assert us >= 170_000 + 120_000 + 20_000          # power-on, sleep-out and display-on waits


def test_a_fill_sets_the_window_and_streams_the_pixels(exe):
    g = commands(spi(run(exe, "fill")))
    assert g == [
        (0x2A, [0x00, 0x02, 0x00, 0x05]),                      # columns 2..5
        (0x2B, [0x00, 0x03, 0x00, 0x04]),                      # rows 3..4
        (0x2C, [0xF8, 0x1F] * 8),                              # 4x2 pixels of 0xF81F, high byte first
    ]


def test_a_fill_that_runs_off_the_glass_is_clipped(exe):
    g = commands(spi(run(exe, "fill_clip")))
    assert g == [
        (0x2A, [0x00, 230, 0x00, 239]),                        # columns 230..239
        (0x2B, [0x01, 0x36, 0x01, 0x3F]),                      # rows 310..319
        (0x2C, [0x12, 0x34] * (10 * 10)),
    ]


def test_windows_outside_the_glass_are_refused_and_send_nothing(exe):
    out = run(exe, "bounds")
    assert "R 0 0 0 0 1" in out            # empty, off to the right, one row too far, one column too wide, valid corner
    g = commands(spi(out))
    assert [c for c, _ in g] == [0x2A, 0x2B, 0x2C]             # exactly the one valid window was opened


def test_expander_init_matches_the_boot_loader_and_the_observed_writes(exe):
    out = run(exe, "expander")
    assert i2c(out) == [
        "I b6 10 b7 -> 23",                                    # presence: the ID register
        "I b6 04 fe", "I b6 05 90", "I b6 11 10", "I b6 12 fe", "I b6 13 f0",
        "I b6 20 00", "I b6 21 00", "I b6 22 00",              # every LED off
        "I b6 24 40",                                          # backlight, P0_0
        "I b6 22 20",                                          # RUN, P1_2
        "I b6 20 10",                                          # CHG green, P1_0
        "I b6 21 00",                                          # CHG red, P1_1
    ]                                                          # the out-of-range LED wrote nothing
    assert "R 1" in out and "forbidden 0" in out


def test_a_missing_chip_stops_after_the_address_and_reports_it(exe):
    out = run(exe, "nochip")
    assert i2c(out) == ["I b6"] and "R 0" in out


def test_the_driver_never_touches_the_buzzer_pin_or_pg1(exe):
    for sc in ("lcd_init", "fill", "expander", "nochip", "fill_clip"):
        out = run(exe, sc)
        assert "forbidden 0" in out, (sc, out)
        assert not any(l.startswith("BAD") for l in out)


def test_a_wrong_byte_in_the_table_is_caught(tmp_path):
    """Break the guarded thing on purpose: one byte of the gamma table. The comparison must fail."""
    src = open(os.path.join(FW, "h7_ui.c"), encoding="utf-8").read()
    needle = "0x0d, 0x11, 0x13, 0x2b, 0x3f, 0x54"
    assert src.count(needle) == 1
    bad = tmp_path / "h7_ui_mut.c"
    bad.write_text(src.replace(needle, "0x0d, 0x11, 0x13, 0x2b, 0x3f, 0x55"), encoding="utf-8")
    mut = build(str(tmp_path), str(bad))
    assert commands(spi(run(mut, "lcd_init"))) != INIT


@pytest.mark.parametrize("old, new, what", [
    ("(1u << 15));\n\tREG_WR(SPI_CR1, SPI_CR1_SSI);", "0);\n\tREG_WR(SPI_CR1, SPI_CR1_SSI);", "IOSWP"),
    ("(SPI_MBR << 28) | 7u", "(SPI_MBR << 28) | 15u", "frame size"),
    ("#define SPI_MBR        1u", "#define SPI_MBR        0u", "clock rate"),
    ("(5u << 24) | (5u << 28)", "(2u << 24) | (5u << 28)", "alternate function"),
    ("\tspi_wait(SPI_SR_EOT);\n\tREG_WR(SPI_IFCR", "\tREG_WR(SPI_IFCR", "end-of-transfer wait"),
    ("\tREG_WR(SPI_CR1, SPI_CR1_SSI);\n}\n\nstatic void spi_byte", "\tREG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE);\n}\n\nstatic void spi_byte", "SPE left on"),
])
def test_a_fault_in_the_spi5_setup_is_caught(tmp_path, old, new, what):
    """Break each guarded part of the peripheral set-up on purpose; the fake peripheral or the byte comparison must object."""
    src = open(os.path.join(FW, "h7_ui.c"), encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_ui_mut.c"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    mut = build(str(tmp_path), str(bad), hw=1)
    out = subprocess.run([mut, "fill"], capture_output=True, text=True, timeout=pacing.NORMAL).stdout.splitlines()
    clean = (not any(l.startswith("BAD") for l in out) and "forbidden 0" in out and "spi_errors 0" in out
             and commands(spi(out)) == [(0x2A, [0, 2, 0, 5]), (0x2B, [0, 3, 0, 4]), (0x2C, [0xF8, 0x1F] * 8)])
    assert not clean, what


def test_a_stuck_spi5_costs_one_short_wait_not_one_per_pixel(tmp_path):
    """A peripheral that never reports a free FIFO slot: the first wait gives up, the error is counted once and the
    rest of a full-screen fill touches SPI5 no more. Without the latch a fill would wait out 153,600 times."""
    out = run(build(str(tmp_path), hw=1), "spi_stuck")
    reads = int([l for l in out if l.startswith("sr_reads")][0].split()[1])
    assert "spi_errors 1" in out
    assert reads <= 2 * 4000 + 16, reads                  # one wait, plus the status snapshot
