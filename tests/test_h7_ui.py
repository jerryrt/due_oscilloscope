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
    if scenario not in ("spi_stuck", "dma_after_fallback", "dma_begin_stuck"):
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
    ("\tREG_WR(SPI_CR1, SPI_CR1_SSI);\n\tREG_WR(SPI_IFCR, SPI_IFCR_ALL);", "\tREG_WR(SPI_CR1, 0);\n\tREG_WR(SPI_IFCR, SPI_IFCR_ALL);", "SSI before the configuration"),
    ("#define SPI_MBR        0u", "#define SPI_MBR        1u", "clock rate"),
    ("(5u << 24) | (5u << 28)", "(2u << 24) | (5u << 28)", "alternate function"),
    ("\tif (!spi_wait(SPI_SR_EOT)) return 0;\n\tREG_WR(SPI_IFCR", "\tREG_WR(SPI_IFCR", "end-of-transfer wait"),
    ("\tREG_WR(SPI_CR1, SPI_CR1_SSI);\n\treturn 1;\n}", "\tREG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE);\n\treturn 1;\n}", "SPE left on"),
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


def test_a_stuck_spi5_costs_one_short_wait_and_the_picture_still_arrives(tmp_path):
    """A peripheral that never reports a free FIFO slot: the first wait gives up, the error is counted once, the pins
    take over, and the whole full-screen fill still reaches the panel byte for byte. Without the hand-over a fill
    would wait out 153,600 times and, with a dead path, draw nothing."""
    out = run(build(str(tmp_path), hw=1), "spi_stuck")
    reads = int([l for l in out if l.startswith("sr_reads")][0].split()[1])
    assert "spi_errors 1" in out
    assert reads <= 4000 + 8, reads                       # one wait, plus the status snapshot
    assert commands(spi(out)) == [
        (0x2A, [0x00, 0x00, 0x00, 0xEF]), (0x2B, [0x00, 0x00, 0x01, 0x3F]), (0x2C, [0xFF] * (240 * 320 * 2)),
    ]


def kv(out):
    return {l.split()[0]: l.split()[1] for l in out if len(l.split()) == 2 and not l.startswith(("S ", "I ", "R "))}


def test_pll2_is_started_for_spi5_and_nothing_else_is_touched(tmp_path):
    """From the state the images leave RCC in, PLL2 comes up at 160 MHz (M 5, N 128, Q 4), SPI4/5 is moved onto it only after
    it is ready, PLL1's registers are untouched, and the only CR change is PLL2ON."""
    v = kv(run(build(str(tmp_path), hw=1), "pll2"))
    assert v["fast"] == "1"
    assert v["pll2divr"] == "0103027f" and v["pllcksel"] == "00005052" and v["pllcfgr"] == "00170088"
    assert int(v["cr"], 16) & 0x0F03FFFF == 0x0F03C025 and v["d2ccip1r"] == "00010000"      # PLL2ON and PLL2RDY added, the rest as it was
    assert v["pll1divr"] == "0103029f" and v["pll1fracr"] == "00000000"


def test_the_hand_clocked_build_leaves_rcc_alone(tmp_path):
    v = kv(run(build(str(tmp_path), hw=0), "pll2"))
    assert v["fast"] == "0" and v["cr"] == "0303c025" and v["d2ccip1r"] == "00000000" and v["pll2divr"] == "00000000"


@pytest.mark.parametrize("scenario, check", [
    ("pll2_busy",  lambda v: v["pll2divr"] == "11111111" and v["d2ccip1r"] == "00000000" and int(v["cr"], 16) & (1 << 26)),    # in use by someone else
    ("pll2_dead",  lambda v: v["cr"] == "0303c025" and v["d2ccip1r"] == "00000000"),                                    # never locks: switched off again
    ("pll2_other", lambda v: v["pllcksel"] == "00000040" and v["pll2divr"] == "00000000" and v["cr"] == "0303c025"),    # not the clock tree it knows
])
def test_pll2_is_not_taken_when_it_is_busy_dead_or_unexpected(tmp_path, scenario, check):
    out = run(build(str(tmp_path), hw=1), scenario)
    v = kv(out)
    assert v["fast"] == "0" and check(v), v


@pytest.mark.parametrize("old, new, what", [
    ("(127u) | (1u << 9)", "(126u) | (1u << 9)", "PLL2 multiplier"),
    ("(3u << 16) | (1u << 24)", "(2u << 16) | (1u << 24)", "PLL2 Q divider"),
    ("(5u << 12)", "(4u << 12)", "PLL2 input divider"),
    ("(REG_RD(RCC_CR) & (1u << 26)) ||", "0 ||", "PLL2 already on"),
    ("REG_WR(RCC_CR, REG_RD(RCC_CR) & ~(1u << 26));                                         /* never locked", "(void)0;                                         /* never locked", "switch off after no lock"),
])
def test_a_fault_in_the_pll2_start_is_caught(tmp_path, old, new, what):
    src = open(os.path.join(FW, "h7_ui.c"), encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_ui_mut.c"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    mut = build(str(tmp_path), str(bad), hw=1)
    good = {"pll2": lambda v: v["pll2divr"] == "0103027f" and v["pllcksel"] == "00005052" and v["fast"] == "1",
            "pll2_busy": lambda v: v["fast"] == "0" and v["pll2divr"] == "11111111",
            "pll2_dead": lambda v: v["fast"] == "0" and v["cr"] == "0303c025"}
    results = []
    for sc, ok in good.items():
        out = subprocess.run([mut, sc], capture_output=True, text=True, timeout=pacing.NORMAL).stdout.splitlines()
        results.append(not any(l.startswith("BAD") for l in out) and ok(kv(out)))
    assert not all(results), what


EXPECT_SHADOW = {}
for _y in (3, 4):
    for _x in range(2, 6): EXPECT_SHADOW[(_x, _y)] = "f81f"
for _y in range(310, 320):
    for _x in range(230, 240): EXPECT_SHADOW[(_x, _y)] = "1234"            # the clipped part of the 20 x 20 fill
for _i in range(6): EXPECT_SHADOW[(10 + _i % 3, 20 + _i // 3)] = "%02x%02x" % (_i + 1, _i + 1)
EXPECT_SHADOW.update({(5, 5): "1111"})   # the second pixel of a one-pixel window is dropped


def test_the_shadow_copy_holds_exactly_what_was_drawn(exe):
    """Every pixel sent is also in the shadow, in its place, nothing outside the window or the glass is written, and the
    guard bytes either side of the buffer survive."""
    out = run(exe, "shadow")
    v = kv(out)
    got = {(int(l.split()[1]), int(l.split()[2])): l.split()[3] for l in out if l.startswith("px ")}
    assert got == EXPECT_SHADOW
    assert v["guard"] == "0" and v["draws"] == "4"


@pytest.mark.parametrize("old, new, what", [
    ("d[0] = hi; d[1] = lo;", "d[0] = lo; d[1] = hi;", "byte order"),
    ("(((win_y + sh_cy) * H7LCD_W) + win_x + sh_cx) * 2u", "(((win_y + sh_cy) * H7LCD_W) + win_x) * 2u", "column advance"),
    ("if (++sh_cx == win_w) { sh_cx = 0; sh_cy++; }", "if (++sh_cx == win_w + 1) { sh_cx = 0; sh_cy++; }", "row wrap"),
    ("\tshadow_put(hi, lo);\n", "", "pixels not mirrored"),
    ("\tCS_H();\n\tdraw_count++;", "\tCS_H();", "draw counter"),
])
def test_a_fault_in_the_shadow_copy_is_caught(tmp_path, old, new, what):
    src = open(os.path.join(FW, "h7_ui.c"), encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_ui_mut.c"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    mut = build(str(tmp_path), str(bad), hw=1)
    out = subprocess.run([mut, "shadow"], capture_output=True, text=True, timeout=pacing.NORMAL).stdout.splitlines()
    got = {(int(l.split()[1]), int(l.split()[2])): l.split()[3] for l in out if l.startswith("px ")}
    assert got != EXPECT_SHADOW or "draws 4" not in out or "guard 0" not in out, what


def rets(out): return [l for l in out if l.startswith(("ret ", "chunks "))]


def test_the_panel_model_and_the_shadow_agree_after_cpu_drawing(exe):
    """The harness builds the panel's memory from the bytes that were actually sent, by whichever route; the shadow must equal it."""
    assert "panel_diff 0" in run(exe, "shadow")


def test_dma_fills_reach_the_panel_and_the_shadow_in_three_chunks(tmp_path):
    out = run(build(str(tmp_path), hw=1), "dma_fill")
    assert rets(out) == ["ret 1", "chunks 65534 65534 22532 n 3", "ret 1", "ret 1", "ret 0", "ret 0"]
    assert "panel_diff 0" in out and "guard 0" in out and "dma_errors 0" in out and "dma_left 0" in out
    assert "dma_bytes %d" % (153600 + 16 + 200) in out                                # the clipped 10 x 10 corner is 200 bytes


def test_dma_blits_chunk_the_buffer_and_refuse_what_does_not_fit(tmp_path):
    out = run(build(str(tmp_path), hw=1), "dma_blit")
    assert rets(out) == ["ret 1", "ret 0", "ret 0", "ret 0", "ret 0", "ret 1", "chunks 12 65534 65534 n 4"]
    assert "panel_diff 0" in out and "guard 0" in out and "dma_left 0" in out and "dma_bytes %d" % (12 + 153600) in out


def test_a_dma_transfer_that_never_ends_is_given_up_cleanly(tmp_path):
    out = run(build(str(tmp_path), hw=1), "dma_stuck")
    assert rets(out) == ["ret 0"] and "dma_errors 1" in out and "dma_stream_left 0" in out and "dma_left 0" in out
    assert "panel_diff 0" in out                                                      # nothing half-recorded in the shadow


def test_dma_is_not_attempted_without_a_scratch_pixel_or_after_the_pins_took_over(tmp_path):
    exe_ = build(str(tmp_path), hw=1)
    out = run(exe_, "dma_noscratch")
    assert rets(out) == ["ret 0"] and "dma_bytes 0" in out and "panel_diff 0" in out and "dma_errors 0" in out
    out = run(exe_, "dma_after_fallback")
    assert rets(out) == ["ret 0"] and "spi_errors 1" in out and "dma_errors 0" in out and "panel_diff 0" in out
    assert "dma_bytes 8" in out                                                       # only the 2 x 2 fill the pins drew


def test_a_window_that_falls_back_to_the_pins_does_not_start_dma(tmp_path):
    out = run(build(str(tmp_path), hw=1), "dma_begin_stuck")
    assert rets(out) == ["ret 0"] and "chunks_n 0" in out and "spi_errors 1" in out and "dma_errors 0" in out
    assert "panel_diff 0" in out and "dma_left 0" in out


def test_the_hand_clocked_build_refuses_dma_and_still_matches(tmp_path):
    out = run(build(str(tmp_path), hw=0), "dma_fill")
    assert rets(out)[0] == "ret 0" and "panel_diff 0" in out


@pytest.mark.parametrize("old, new, what", [
    ("\tshadow_rect(w, h, dma_scratch[0], dma_scratch[1]);", "\tshadow_rect(w, h, 0, 0);", "DMA fill not mirrored"),
    ("\tfor (uint32_t i = 0; i < bytes; i += 2) shadow_put(src[i], src[i + 1]);", "", "blit not mirrored"),
    ("(1u << 10) | (1u << 6)", "(1u << 10)", "DMA direction"),
    ("REG_WR(DMAMUX1_C11, DMAREQ_SPI5_TX);", "REG_WR(DMAMUX1_C11, DMAREQ_SPI5_TX + 1u);", "DMAMUX request"),
    ("circ ? circ : bytes", "bytes", "circular count"),
    ("REG_WR(SPI_CFG1, REG_RD(SPI_CFG1) | (1u << 15));", "", "TXDMAEN"),
    ("REG_WR(SPI_CFG1, REG_RD(SPI_CFG1) & ~(1u << 15));", "", "TXDMAEN left on"),
    ("#define SPI_CHUNK_MAX  65534u", "#define SPI_CHUNK_MAX  65535u", "odd chunk size"),
    ("|| bytes / 2u > pix_left", "", "blit bound"),
    ("REG_WR(DMA2_S3, 0);\n\tdma_wait(DMA2_S3, 1u, 0, 1000u);", "dma_wait(DMA2_S3, 1u, 0, 1000u);", "stream left on"),
])
def test_a_fault_in_the_dma_path_is_caught(tmp_path, old, new, what):
    src = open(os.path.join(FW, "h7_ui.c"), encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_ui_mut.c"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    mut = build(str(tmp_path), str(bad), hw=1)
    fine = True
    for sc, want in (("dma_fill", ["ret 1", "chunks 65534 65534 22532 n 3", "ret 1", "ret 1", "ret 0", "ret 0"]),
                     ("dma_blit", ["ret 1", "ret 0", "ret 0", "ret 0", "ret 0", "ret 1", "chunks 12 65534 65534 n 4"]),
                     ("dma_stuck", ["ret 0"]), ("dma_begin_stuck", ["ret 0"])):
        out = subprocess.run([mut, sc], capture_output=True, text=True, timeout=pacing.NORMAL).stdout.splitlines()
        fine &= (not any(l.startswith("BAD") for l in out) and "forbidden 0" in out and rets(out) == want
                 and "panel_diff 0" in out and "guard 0" in out and "dma_left 0" in out)
    assert not fine, what
