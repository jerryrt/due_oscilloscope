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


def _since(n):
    return [p for p in IMAGES if int(os.path.basename(os.path.dirname(p))[5:]) >= n]


def _body(src, name):
    return re.search(r"^static void %s\([^)]*\)\n\{\n(.*?)^\}" % name, src, re.M | re.S).group(1)


@pytest.mark.parametrize("image", _since(14), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_stream_endpoint_is_quiesced_at_both_ends_of_a_run_and_an_aborted_transfer_is_sent_again(image):
    src = _source(image)
    assert re.search(r"ep2_quiesce\([01]?\);", _body(src, "acq_start")) and re.search(r"ep2_quiesce\([01]?\);", _body(src, "acq_stop"))
    assert re.search(r"else if \(ep_busy && \(DIEPINT\(2\) & 2u\)\)", _body(src, "stream_poll")), "a disabled-not-completed transfer must be sent again"


@pytest.mark.parametrize("image", _since(17), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_in_endpoint_is_disabled_by_the_cores_procedure_and_epdis_is_never_written_to_an_idle_endpoint(image):
    """Image 14 wrote EPDIS after checking EPENA once, earlier: a transfer that completed on its own in between left EPENA clear, EPDIS latched,
    and the next transfer was armed with both set - the unit then streamed nothing (1 start in 50-100). The core's procedure is Global IN NAK,
    wait for it to take effect, look at EPENA AGAIN (nothing can complete now), EPDIS only if it is still set, wait for EPDISD, release the NAK."""
    q = _body(_source(image), "ep2_quiesce")
    order = [q.find(x) for x in ("DCTL |= 1u << 7", "GINTSTS & (1u << 6)", "if (DIEPCTL(2) & EPENA) {\n\t\t\tDIEPCTL(2) |= (1u << 30)", "DIEPINT(2) & 2u", "DCTL |= 1u << 8")]
    assert -1 not in order, f"a step of the procedure is missing: {order}"
    assert order == sorted(order), "the steps are out of order: SGINAK, GINAKEFF, EPENA again then EPDIS, EPDISD, CGINAK"
    assert len(re.findall(r"\(1u << 30\)", q)) == 1, "EPDIS must be written in exactly one place, behind the second EPENA check"
    waits = re.findall(r"^\s*while \((.*)\) tick\(\);", q, re.M)
    assert len(waits) == 2 and all(re.search(r"ms_now - t < \d+u", w) for w in waits), "both waits (GINAKEFF, EPDISD) must be against the clock"
    assert "for (uint32_t n" not in q, "no iteration-count wait"
    assert q.count("ep_q_timeouts++") == 2, "each of the two waits must count its own expiry: an expired wait is never silent"


@pytest.mark.parametrize("image", _since(17), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_bulk_out_is_drained_when_no_playback_owns_it(image):
    """The Due's rule: a CDC device keeps draining bulk OUT when nothing uses it. Without it the bytes the host wrote for a stopped playback sit in its write
    queue and closing the stream port waits for them for ever: a start that never returned, found when the host began closing the port at every run."""
    src = _source(image)
    idle = _body(src, "out_idle_poll")
    assert re.search(r"if \(play_on \|\| config_value != 1\) return;", idle), "idle draining must yield to playback and wait for a configuration"
    assert "DOEPDMA(2) = PLAY_RING;" in idle and "DOEPCTL(2) |= EPENA | CNAK;" in idle, "the endpoint is re-armed on the (unused) play ring"
    assert not re.search(r"\bwhile\b|\bfor\b", idle), "constant work per pass (invariant 7): no loop in the drain"
    loop = src[src.index("	while (RUN_WINDOW_OPEN()) {"):]
    assert "out_idle_poll();" in loop, "the drain must run in the main loop, every pass"
    assert "out_quiesce();" in _body(src, "play_start"), "playback must take the endpoint from the drain cleanly"
    assert "out_quiesce();" in _body(src, "play_stop")


@pytest.mark.parametrize("image", _since(17), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_the_out_endpoint_is_disabled_by_the_cores_procedure_too(image):
    """The same latent flaw as the IN side: EPDIS written after one early EPENA check latches on an endpoint whose transfer finished meanwhile. With the idle
    drain keeping a transfer armed, it would be reached far more often."""
    q = _body(_source(image), "out_quiesce")
    order = [q.find(x) for x in ("DCTL |= 1u << 9", "GINTSTS & (1u << 7)", "if (DOEPCTL(2) & EPENA) {\n\t\t\tDOEPCTL(2) |= (1u << 30)", "DOEPINT(2) & 2u", "DCTL |= 1u << 10")]
    assert -1 not in order and order == sorted(order), f"SGONAK, GONAKEFF, EPENA again then EPDIS, EPDISD, CGONAK, in that order: {order}"
    assert len(re.findall(r"\(1u << 30\)", q)) == 1
    waits = re.findall(r"^\s*while \((.*)\) tick\(\);", q, re.M)
    assert len(waits) == 2 and all(re.search(r"ms_now - t < \d+u", w) for w in waits) and "for (uint32_t n" not in q
    assert q.count("out_q_timeouts++") == 2, "each wait counts its own expiry"
