"""Image 13's return to the boot loader (docs/19): the control opcode that asks for it, and the absence of the old self-timed return.
The opcode is exercised through the simulated unit (the real dispatcher compiled for the host); the timer is held by a check of the image
source, because the image itself only runs on the unit. Needs a host C compiler for the first test: without one it SKIPS, not passes."""
import ctypes
import os
import re
import struct

import pytest

import control as ctl
import daemon.device as devmod
import daemon.h7sim as h7sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, "targets", "h7tool", "fw")
#: every image from 13 on: the ones that carry no self-timed return and the boot-loader opcode
IMAGES = sorted(os.path.join(FW, d, "main.c") for d in os.listdir(FW) if re.fullmatch(r"image(\d+)", d) and int(d[5:]) >= 13)


def test_there_are_images_to_guard():
    assert len(IMAGES) >= 2, "the images 13 and 14 must be found, or the two guards below check nothing"


@pytest.mark.skipif(not h7sim.available(), reason="no host C compiler for the simulated H7: this skip is NOT a pass")
def test_the_bootloader_opcode_arms_only_on_the_exact_word():
    dev = h7sim.make_sim_device()
    armed = ctypes.c_int.in_dll(dev._ctl._lib, "stub_boot_requests")
    base = armed.value
    for body in (b"", b"BOO", b"BOOTS", b"boot"):
        with pytest.raises(devmod.DeviceError):
            dev._call(0x0044, body)
    assert armed.value == base                                   # a wrong body does nothing
    assert dev._call(0x0044, b"BOOT").payload == b"\x01" and armed.value == base + 1
    caps, = struct.unpack_from("<H", dev._call(ctl.OP_CAPABILITY).payload)
    assert 0x0044 in struct.unpack_from("<%dH" % caps, dev._call(ctl.OP_CAPABILITY).payload, 2)    # and the unit says it can


def _source(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("image", IMAGES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_image_has_no_self_timed_return_by_default(image):
    src = _source(image)
    m = re.search(r"#ifndef RUN_MS\s*\n#define RUN_MS\s+(\w+)", src)
    assert m and m.group(1) in ("0", "0u"), "RUN_MS must default to 0 (no timer); the host asks for the boot loader"
    assert re.search(r"#if RUN_MS == 0\s*\n#define RUN_WINDOW_OPEN\(\)\s+1\b", src), "with RUN_MS 0 the run loop must be unconditional"
    loops = re.findall(r"^\s*while \((.*RUN.*)\) \{$", src, re.M)
    assert loops == ["RUN_WINDOW_OPEN()"], f"the run loop must test only RUN_WINDOW_OPEN(), found {loops}"
    assert "ms_now < RUN_MS" not in re.sub(r"#define RUN_WINDOW_OPEN\(\)\s+\(ms_now < RUN_MS\)", "", src), "a bare window compare is back"


@pytest.mark.parametrize("image", IMAGES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_image_still_has_both_ways_back_to_the_boot_loader(image):
    src = _source(image)
    assert "int h7_request_bootloader(void)" in src and "boot_pending" in src      # the control opcode's hook
    assert re.search(r"req == 0x7F[^\n]*\n(?:[^\n]*\n){0,6}[^\n]*return_to_boot_loader\(\)", src), "the vendor request 0x7F must still restart"


@pytest.mark.parametrize("image", [p for p in IMAGES if int(os.path.basename(os.path.dirname(p))[5:]) >= 14],
                         ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_stream_endpoint_is_quiesced_at_both_ends_of_a_run_and_an_aborted_transfer_is_sent_again(image):
    """Image 13 left a run's endpoint disable possibly pending; it then killed the next run's first transfer and the unit streamed nothing
    (15 of 400 starts on the bench, against 1 of 400 with this). The source holds the three parts of the fix; the rate is only measurable on the unit."""
    src = _source(image)
    body = lambda name: re.search(r"^static void %s\(void\)\n\{\n(.*?)^\}" % name, src, re.M | re.S).group(1)
    assert "ep2_quiesce();" in body("acq_start") and "ep2_quiesce();" in body("acq_stop")
    q = body("ep2_quiesce")
    assert "(1u << 30)" in q, "the endpoint is disabled with EPDIS"
    assert re.search(r"while \(\(DIEPCTL\(2\) & EPENA\) && ms_now - t < \d+u\) tick\(\);", q), \
        "the wait for the disable to finish must be against the clock, not a loop count"
    assert re.search(r"else if \(ep_busy && \(DIEPINT\(2\) & 2u\)\)", body("stream_poll")), "a disabled-not-completed transfer must be sent again"
