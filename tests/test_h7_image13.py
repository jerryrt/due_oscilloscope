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
IMAGE = os.path.join(ROOT, "targets", "h7tool", "fw", "image13", "main.c")


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


def _source():
    with open(IMAGE, encoding="utf-8") as fh:
        return fh.read()


def test_image13_has_no_self_timed_return_by_default():
    src = _source()
    m = re.search(r"#ifndef RUN_MS\s*\n#define RUN_MS\s+(\w+)", src)
    assert m and m.group(1) in ("0", "0u"), "RUN_MS must default to 0 (no timer); the host asks for the boot loader"
    assert re.search(r"#if RUN_MS == 0\s*\n#define RUN_WINDOW_OPEN\(\)\s+1\b", src), "with RUN_MS 0 the run loop must be unconditional"
    loops = re.findall(r"^\s*while \((.*RUN.*)\) \{$", src, re.M)
    assert loops == ["RUN_WINDOW_OPEN()"], f"the run loop must test only RUN_WINDOW_OPEN(), found {loops}"
    assert "ms_now < RUN_MS" not in re.sub(r"#define RUN_WINDOW_OPEN\(\)\s+\(ms_now < RUN_MS\)", "", src), "a bare window compare is back"


def test_image13_still_has_both_ways_back_to_the_boot_loader():
    src = _source()
    assert "int h7_request_bootloader(void)" in src and "boot_pending" in src      # the control opcode's hook
    assert re.search(r"req == 0x7F[^\n]*\n(?:[^\n]*\n){0,6}[^\n]*return_to_boot_loader\(\)", src), "the vendor request 0x7F must still restart"
