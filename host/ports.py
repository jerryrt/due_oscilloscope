#!/usr/bin/env python3
"""
Locate the Due's two USB ports by probing, not by hardcoded path.

Device node names are derived from USB location, so they change whenever
a cable moves to a different socket or hub. Hardcoding one has already
caused two debugging detours in this project, and a wrong port looks
exactly like dead firmware.

The programming port is identified by the only reliable means available:
it answers. Sending 'h' provokes the firmware banner, and only the port
carrying the command UART will produce it.

The native port offers two CDC functions on one cable, samples and
commands, so there are two other nodes and picking either by position
is a coin flip that happens to land right. They are told apart by USB
interface number, which is a contract pinned in
docs/control-protocol.md - interfaces 0 and 1 carry samples, 2 and 3
carry commands - and IOKit is asked for it rather than the node name
being pattern-matched.
"""

import os
import re
import subprocess
import sys
import time

import transport
from transport import WINDOWS, open_raw          # noqa: F401  (re-exported)
import pacing

# macOS is the only platform that needs ioreg, and the only one where
# pyserial does not report a USB interface number. Tier 2: see CLAUDE.md.
DARWIN = sys.platform == "darwin"

BANNER_MARK = b"due_oscilloscope"

# The board's USB identity, which reads the same on every OS - unlike a
# device node name, which macOS derives from USB location and Windows
# assigns from an enumeration counter.
VID = 0x2341
PID_CONSOLE = 0x003D                  # programming port, via the 16U2
PID_NATIVE = 0x003E                   # native port, the SAM3X's own USB

# Why discovery cannot enumerate at all, or None. A missing pyserial and
# an empty bench used to be the same return value - three Nones - and
# the documented first move against a board that looks dead is to bounce
# the native port and reflash it. That is the GPNVM trap one layer up:
# the cheap fact that would have stopped it is one line, so say it.
_no_enumeration = None

PYSERIAL_HINT = (
    "pyserial is not installed for this interpreter, so no serial port "
    "can be enumerated and no board can be found however many are "
    "attached. Run host/ tools from the venv - .venv/bin/python - or "
    "install the dependency: pip install -r requirements-dev.txt"
)


def pyserial_missing():
    """The import error that stopped enumeration, or None.

    Callers keep their empty result - nothing here starts raising, and
    the daemon, the suite and docker/run-ci.sh all treat an empty bench
    as a legitimate state. This is how one of them tells "nothing is
    attached" from "nothing can be seen" when it wants to know.

    None until discovery has been attempted at least once, because the
    import is lazy and answering before it has been tried would be a
    guess.
    """
    return _no_enumeration


def answers_banner(dev, timeout=pacing.REPORT):
    """Does this node produce the firmware banner?

    Not used for discovery - that is VID/PID now, on every platform,
    because probing opens the programming port, and opening it resets
    the board on macOS (not on Linux or Windows). Kept because "is there
    working firmware behind this node" is a different and still useful
    question from "which node is this".
    """
    return _responds(dev, timeout)


def _responds(dev, timeout=pacing.REPORT):
    try:
        port = open_raw(dev, 115200)
    except OSError:
        return False
    try:
        port.write(b"h")
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            if transport.wait_any([port], pacing.POLL):
                try:
                    buf += port.read(4096)
                except OSError:
                    break
            if BANNER_MARK in buf:
                return True
        return False
    finally:
        port.close()


def usb_interfaces():
    """Map each serial node to the USB interface behind it.

    Returns {device_path: (serial_number, interface_number)}, or {} if
    the platform will not say - every caller treats that as "no
    information" and falls back rather than failing, because this is an
    aid to identification and not the identification itself.

    One function, because native_order() must not branch on platform:
    the ordering rule is a contract from docs/control-protocol.md
    (samples on interfaces 0/1, commands on 2/3) and it is the same
    everywhere. Only the way the number is obtained differs - pyserial
    on Windows and Linux, ioreg on macOS.
    """
    if not DARWIN:
        # The guard belongs here rather than inside _pyserial_nodes,
        # because this is the function that promises {} on failure.
        try:
            return {d: (ser or "", i)
                    for d, _v, _p, i, ser in _pyserial_nodes()
                    if i is not None}
        except Exception:                                    # noqa: BLE001
            return {}
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOUSBHostInterface", "-r", "-l", "-w", "0",
             "-d", "4"],
            capture_output=True, text=True, timeout=pacing.NORMAL).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    found = {}
    serial = iface = None
    for line in out.splitlines():
        # A new interface subtree resets the record. Child nodes
        # (AppleUSBACMData, IOSerialBSDClient) must not, because the
        # callout device hangs off them and belongs to this interface.
        if "+-o " in line and "class IOUSBHostInterface" in line:
            serial = iface = None
            continue
        m = re.search(r'"bInterfaceNumber" = (\d+)', line)
        if m:
            iface = int(m.group(1))
            continue
        m = re.search(r'"USB Serial Number" = "([^"]*)"', line)
        if m:
            serial = m.group(1)
            continue
        m = re.search(r'"IOCalloutDevice" = "([^"]*)"', line)
        if m and iface is not None:
            found[m.group(1)] = (serial, iface)
    return found


def _pyserial_nodes():
    """(node, vid, pid, interface) for every serial device, or [].

    pyserial's `location` ends in the USB interface number on Windows
    ("1-5:x.0", "1-5:x.2"), which is the same contract IOKit is asked
    for on macOS: interfaces 0/1 carry samples, 2/3 carry commands.
    Note that pyserial's `hwid` does NOT carry the MI_00 that the Win32
    DeviceID has, so matching on that substring finds nothing here.
    """
    global _no_enumeration
    try:
        from serial.tools import list_ports
    except ImportError as e:
        # NOT the same as an enumeration that answered with nothing.
        # This interpreter cannot look at all, and every caller above
        # would otherwise read that as an empty bench - which reads in
        # turn as dead firmware, and the response to dead firmware here
        # is to bounce the port and reflash. Said once per process, on
        # stderr so nothing parsing stdout changes shape.
        if _no_enumeration is None:
            _no_enumeration = str(e)
            print(f"host/ports.py: {PYSERIAL_HINT} ({e})", file=sys.stderr)
        return []
    try:
        out = []
        for p in list_ports.comports():
            iface = None
            m = re.search(r"[.:](\d+)$", (p.location or ""))
            if m:
                iface = int(m.group(1))
            out.append((p.device, p.vid, p.pid, iface, p.serial_number))
        return out
    except Exception:                                        # noqa: BLE001
        # Same contract as the ioreg path: an enumeration that will not
        # answer is no information, not an error. Callers fall back.
        return []


def native_order(nodes):
    """Sort native nodes so the sample function comes first.

    By interface number where IOKit will say, and by name otherwise.
    The fallback is not arbitrary: the sample function holds the lower
    interface numbers by contract, and macOS derives the node name from
    the interface, so the two orderings agree today. It is a fallback
    rather than the method because that agreement is a property of one
    operating system's naming and not something this project controls.
    """
    ifaces = usb_interfaces()

    def key(n):
        serial, iface = ifaces.get(n, (None, 1 << 16))
        # Serial first so two attached boards keep their own pair
        # together rather than interleaving by interface number.
        return (serial or "", iface, n)

    return sorted(nodes, key=key)


def native_nodes(exclude=None):
    """The native port's nodes, sample function first.

    One discovery path for every caller, rather than each caller
    globbing device paths itself. Ordering is by USB interface number -
    samples on 0/1, commands on 2/3 - which is a contract pinned in
    docs/control-protocol.md rather than a property of any one OS's
    device naming.

    Discovery here never opens a port. Opening the programming port
    resets the board on macOS (it asserts NRSTB; Linux and Windows
    were measured not to), so a running daemon cannot afford to probe.

    Filtered by USB VID/PID on every platform, not by a path glob: a
    bare /dev/cu.usbmodem* glob also matches the programming port and a
    second board's ROM SAM-BA node (03eb:6124 is a cu.usbmodem* too).
    """
    pinned = _pinned()
    if pinned:
        return [n for n in pinned[1:] if n and n != exclude]
    nodes = [d for d, v, p, _i, _s in _pyserial_nodes()
             if (v, p) == (VID, PID_NATIVE) and d != exclude]
    return native_order(nodes)


def find_ports(wait=pacing.NORMAL):
    """Return (control_port, native_port).

    native_port is the *sample* node, which is what every existing
    caller means by it. Use find_all_ports() for the command node too.
    """
    ctl, native, _cmd = find_all_ports(wait)
    return ctl, native


H7_VID, H7_PID = 0x1209, 0x0001      # the H7 target's own identity (targets/h7tool, docs/06); not an allocation


def find_h7():
    """(stream_path, control_path) of an attached H7 target, or None.

    One cable, two CDC functions told apart by USB interface number: 0 is the sample stream, 2 the control channel
    (the same split as the Due's native pair, but the H7 has no programming port and no console). The number comes from
    `usb_interfaces()`, the one place that knows how each host reports it (pyserial's "1-4:1.0" on Linux, "1-5:x.0" on
    Windows, ioreg on macOS, where pyserial's location ends in a hub port and not an interface).
    """
    ifaces = usb_interfaces()
    nodes = {}
    for dev, vid, pid, _i, _s in _pyserial_nodes():
        if (vid, pid) == (H7_VID, H7_PID) and dev in ifaces:
            nodes[ifaces[dev][1]] = dev
    return (nodes[0], nodes[2]) if 0 in nodes and 2 in nodes else None


H7_BL_VID, H7_BL_PID = 0x0483, 0x5720   # the stock boot loader's mass-storage identity, which an H7 image returns to


def _usb_present(vid, pid):
    """True or False when the host can list USB devices that are not serial ports, None when it cannot.

    A boot-loader unit is mass storage and has no tty, so pyserial never lists it. Linux publishes every device under sysfs; the
    other hosts have no equally cheap, dependency-free answer here and say so rather than guess.
    """
    root = "/sys/bus/usb/devices"
    if not os.path.isdir(root):
        return None
    want = ("%04x" % vid, "%04x" % pid)
    for d in os.listdir(root):
        try:
            with open(os.path.join(root, d, "idVendor"), encoding="ascii") as fv, \
                 open(os.path.join(root, d, "idProduct"), encoding="ascii") as fp:
                if (fv.read().strip(), fp.read().strip()) == want:
                    return True
        except OSError:
            continue
    return False


def h7_state():
    """'running' (an image is enumerated with both functions), 'boot_loader', or 'absent'. Opens nothing and does not wait.

    'absent' means neither was seen; on a host that cannot list non-serial USB devices (not Linux) a unit in the boot loader reads as 'absent'.
    """
    if find_h7():
        return "running"
    return "boot_loader" if _usb_present(H7_BL_VID, H7_BL_PID) else "absent"


def census():
    """What is attached right now, without opening a port or waiting: {'due': {'programming': path|None, 'native': [paths]}, 'h7': state, 'h7_paths': tuple|None}."""
    found = _pyserial_nodes()
    return {"due": {"programming": next((d for d, v, p, _i, _s in found if (v, p) == (VID, PID_CONSOLE)), None),
                    "native": native_order([d for d, v, p, _i, _s in found if (v, p) == (VID, PID_NATIVE)])},
            "h7": h7_state(), "h7_paths": find_h7()}


class AmbiguousBoards(Exception):
    """More than one Due is attached and nothing says which one to use.

    A mixed answer - one board's programming port with the other's
    native pair - is worse than none: every measurement would run on
    two boards at once and be recorded as one. Name the board with
    DUE_DUT (a name in bench.json's "duts") or pin the three nodes.
    """


def dut_registry():
    """bench.json's "duts": {name: {control_serial, native_location, board_uid, ...}}."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "bench.json")
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return {}
    duts = got.get("duts") if isinstance(got, dict) else None
    return duts if isinstance(duts, dict) else {}


def _locations():
    """{node: USB location, e.g. '1-3.3:1.2'} for every serial device."""
    try:
        from serial.tools import list_ports
        return {p.device: (p.location or "") for p in list_ports.comports()}
    except Exception:                                        # noqa: BLE001
        return {}


def _refuse_if_ambiguous(found):
    ctls = [d for d, v, p, _i, _s in found if (v, p) == (VID, PID_CONSOLE)]
    nats = [d for d, v, p, _i, _s in found if (v, p) == (VID, PID_NATIVE)]
    if len(ctls) > 1 or len(nats) > 2:
        names = ", ".join(sorted(dut_registry())) or "none declared in bench.json"
        raise AmbiguousBoards(
            f"{len(ctls)} programming ports and {len(nats)} native nodes are "
            f"attached and nothing says which board to use. Set DUE_DUT to "
            f"one of: {names} (or pin DUE_CONTROL_PORT, DUE_NATIVE_PORT, "
            f"DUE_COMMAND_PORT).")


def resolve_dut(name):
    """(control, native_samples, native_commands) for a declared DUT.

    The programming port is found by the 16U2's own serial, which is
    unique per board and survives re-enumeration, and the native pair by
    its USB location (the hub path before the ':'), because both pairs
    report the same serial. Node names such as ttyACM3 move with every
    re-enumeration and are never stored. A node the registry names but
    the host cannot see is None, as in discovery.
    """
    reg = dut_registry()
    if name not in reg:
        raise AmbiguousBoards(f"no DUT named {name!r} in bench.json's \"duts\" "
                              f"(declared: {', '.join(sorted(reg)) or 'none'})")
    d = reg[name]
    found = _pyserial_nodes()
    loc = _locations()
    ctl = next((n for n, v, p, _i, s in found
                if (v, p) == (VID, PID_CONSOLE) and s == d.get("control_serial")), None)
    base = d.get("native_location")
    nat = [n for n, v, p, _i, _s in found
           if (v, p) == (VID, PID_NATIVE) and base
           and loc.get(n, "").split(":")[0] == base]
    nat = sorted(nat, key=lambda n: loc.get(n, ""))
    return (ctl, nat[0] if nat else None, nat[1] if len(nat) > 1 else None)


def _pinned():
    """The three nodes the bench has named for this process, or None.

    Every discovery path has to ask, not only find_all_ports(): the
    reconnect and bounce paths in measure.py re-list the native nodes
    themselves, and one that fell back to the global list would pick up
    the other board's cable the moment this board's own detached.
    """
    pinned = (os.environ.get("DUE_CONTROL_PORT"),
              os.environ.get("DUE_NATIVE_PORT"),
              os.environ.get("DUE_COMMAND_PORT"))
    if any(pinned):
        return pinned
    name = os.environ.get("DUE_DUT")
    return resolve_dut(name) if name else None


def find_all_ports(wait=pacing.NORMAL):
    """Return (programming_port, native_samples, native_commands).

    Any of the three may be None. The third is None against firmware
    built before the control channel existed, which is a board with one
    native node rather than an error.
    """
    # With two boards on one host discovery cannot say which node pair
    # belongs to which board - the programming port and the native pair
    # are separate USB devices - so a bench that holds two names them.
    # Three ways, strongest first; unset, discovery is unchanged.
    pinned = _pinned()
    if pinned:
        return pinned
    end = time.time() + wait
    while True:
        # Identify by USB VID/PID on every platform, not by probing.
        #
        # The programming port is 2341:003D and the native pair 2341:003E,
        # and pyserial reports both correctly on macOS as well - measured
        # in review, not assumed. So the "port that answers h" probe is
        # gone: it opened the programming port to find out what it was,
        # and opening it asserts NRSTB and resets the board on macOS.
        # Discovery that costs a reset is not discovery a running daemon can do,
        # and that was as true on macOS as anywhere.
        #
        # Ordering is the one thing that stays platform-specific, and it
        # lives in native_order(): pyserial takes `location` from the
        # parent USB device on macOS, so both CDC functions report the
        # same string there and only IOKit can tell interface 1 from 3.
        found = _pyserial_nodes()
        ctl = next((d for d, v, p, _i, _s in found
                    if (v, p) == (VID, PID_CONSOLE)), None)
        rest = native_order([d for d, v, p, _i, _s in found
                             if (v, p) == (VID, PID_NATIVE)])
        _refuse_if_ambiguous(found)
        if ctl or rest:
            return (ctl,
                    rest[0] if rest else None,
                    rest[1] if len(rest) > 1 else None)
        if _no_enumeration is not None:
            # Nothing can be enumerated, so waiting for a board to
            # appear is eight seconds spent watching a blind eye. Same
            # return shape; pyserial_missing() carries the reason.
            return None, None, None
        if time.time() >= end:
            return None, None, None
        pacing.pause(pacing.SETTLE)


if __name__ == "__main__":
    c, n, cmd = find_all_ports()
    print(f"control = {c}")
    print(f"native  = {n}")
    print(f"command = {cmd}")
    # Three statuses, because there are three outcomes and the middle
    # one used to wear the last one's clothes. 0 found it, 1 looked and
    # the bench is empty - unchanged, and the common case - and 2 could
    # not look, which _pyserial_nodes() has already explained on stderr.
    # The stdout lines keep their shape either way: docs/toolchain.md
    # pipes them through awk.
    if pyserial_missing() is not None:
        sys.exit(2)
    sys.exit(0 if c else 1)
