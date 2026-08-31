#!/usr/bin/env python3
"""Flash a bare-metal .bin to the Due, on any host.

This is the single implementation; tools/flash.sh is a shim onto it and
the CMake `flash` target invokes it. Where the tools live is CMake's
business (cmake/hosttools.cmake, toolchains.json) - it passes --bossac.
Run standalone and this resolves the same registry itself.

The Due enters SAM-BA when the programming port is opened at 1200 baud:
the 16U2 sees the baud change followed by DTR dropping, and asserts ERASE
then RESET. That baud rate is a control signal here, not a data rate.

**That last sentence used to end "pyserial performs that identically on
every platform, which is why there is no OS branch in this file", and it
is measured wrong** - issue #35. What reaches the 16U2 is not the same on
every host: Linux and Windows deliver the explicit mid-session DTR drop,
so the erase fires there and the speed must be restored on the fd that is
already open or the *next* open erases the board that was just flashed
(3 of 3 on linux-x1). macOS delivers no such transition - four arms, and
only the two that close while still at 1200 erase anything - so there the
speed must NOT be restored before the close.

The two requirements are contradictory, so there is a branch now. It is
taken on **evidence rather than on sys.platform**: the default arm is the
one measured working on Linux and Windows, and the other is reached only
when the bus shows that the touch did nothing at all.

    python3 tools/flash.py                        # discover everything
    python3 tools/flash.py --port COM7
    python3 tools/flash.py --bin build/x.bin --port /dev/cu.usbmodem14201
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain                                        # noqa: E402
sys.path.insert(0, os.path.join(toolchain.REPO, "host"))
import provenance                                       # noqa: E402

REPO = toolchain.REPO
VID, PID_CONSOLE = 0x2341, 0x003D          # programming port (the 16U2)
SAMBA = (0x03EB, 0x6124)                   # SAM3X ROM bootloader

# How long to wait for the native bootloader node after the touch. It is
# an optimisation - the programming port is tried regardless - so this is
# patience, not a deadline anything depends on.
SAMBA_WAIT_S = 15.0

# How long bossac gets before it is killed. It is not a performance
# budget - a whole erase-write-verify-reset is seconds - it is a bound on
# a hang: bossac given a port that does not exist spins forever at 100%
# CPU with no output, and unbounded means the flash never returns.
BOSSAC_TIMEOUT_S = 120.0

# How long to wait, after bossac has reset the board, for the ROM
# bootloader node to go away - which is the only evidence available here
# that the program actually took over.
BOOT_WAIT_S = 8.0


def find_console(explicit=None):
    """The programming port, by USB VID/PID - identical on every OS."""
    if explicit:
        return explicit
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("needs pyserial to discover the port (pip install pyserial), "
                 "or pass --port")
    hits = [p.device for p in list_ports.comports()
            if p.vid == VID and p.pid == PID_CONSOLE]
    if not hits:
        # Refuse rather than guessing: the 1200-baud touch ERASES whatever
        # port it lands on, and aiming it at the wrong one wipes the flash
        # without writing anything. That has happened once already.
        sys.exit("no programming port found (VID 2341 PID 003D); pass --port")
    if len(hits) > 1:
        sys.exit(f"more than one programming port: {hits}; pass --port")
    return hits[0]


def samba_nodes():
    """Every ROM-bootloader node on the system.

    With blank flash the SAM3X boots ROM SAM-BA, which enumerates on the
    NATIVE port as 03EB:6124 - not through the 16U2. So after an erase
    the programming port is the wrong place to look, and bossac reports
    "No device found" on a board that is sitting in the bootloader
    waiting.

    Returns a list, never one node, because attributing a bootloader to
    a board is the whole problem: SAM-BA has a different VID/PID and no
    serial number in common with the running firmware, so with two
    boards attached there is nothing in the enumeration that says which
    is which. The caller has to earn the attribution - see main().
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()
            if (p.vid, p.pid) == SAMBA]


def open_port(port, baud, tries=6, delay=0.75):
    """Open a serial port, waiting out a handle another process still holds.

    A test run that is killed rather than finished leaves its Python
    holding the programming port, and Windows reports the next open as
    PermissionError(13) - "Access is denied" - which reads like a
    permissions problem and is not one. The handle goes when the process
    does, which can be a moment later than the kill.

    Retrying is the whole fix, but the message matters as much: three
    flashes failed this way in one session and each one looked like a
    different problem. Say what is actually happening.
    """
    import serial
    last = None
    for attempt in range(tries):
        s = serial.Serial()
        s.port, s.baudrate = port, baud
        try:
            s.open()
            return s
        except serial.SerialException as e:
            last = e
            if "PermissionError" not in repr(e) and "Access is denied" not in repr(e):
                raise
            if attempt == 0:
                print(f"==> {port} is held by another process; waiting for it "
                      f"to release (a killed test run does this)")
            time.sleep(delay)
    raise SystemExit(
        f"{port} was still held after {tries} attempts over "
        f"{tries * delay:.0f}s: {last}. Something still has it open; "
        f"on Windows: Get-Process python* | Stop-Process -Force")


def usb_nodes():
    """Every USB-backed serial node on the system.

    The discriminator for "did the touch actually take". A real erase and
    reset changes this set - the firmware's native port goes away and the
    ROM monitor's 03EB:6124 arrives - while a touch the 16U2 ignored
    leaves it byte-identical. Built-in UARTs (`/dev/ttyS*`, vid None) are
    excluded because they are always there and would only add noise.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return set()
    return {p.device for p in list_ports.comports() if p.vid}


def samba_nodes():
    """Every ROM-bootloader node currently on the bus."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return sorted(p.device for p in list_ports.comports()
                  if (p.vid, p.pid) == SAMBA)


def port_present(node):
    """Is `node` still on the bus? Cross-platform.

    `os.path.exists()` answers this only where a serial node is a
    filesystem path. On Windows a port is named `COM10` and is not a
    path, so `os.path.exists("COM10")` is False for every port that
    exists - including one pyserial is enumerating at that moment.

    Measured on windows-desk 2026-08-30, immediately after 38e2cd4: the
    native SAM-BA route was skipped as "gone from the bus" while COM10
    was listed by `list_ports.comports()`, then the programming-port
    route was skipped for the same reason, and all three retries failed
    with the board left erased in the bootloader. That is the whole
    flash path on this platform, and it is also the recovery path, so a
    board could not be flashed back out of it.

    `usb_nodes()` is the set the discriminator above already builds, and
    it is pyserial's view rather than the filesystem's. The
    `os.path.exists` arm is kept for a POSIX node pyserial does not
    enumerate - a udev symlink, say - so this is strictly more
    permissive than the check it replaces and cannot newly skip a route
    on Linux or macOS. A node that has genuinely gone fails both arms
    and is still skipped, which is what BOSSAC_TIMEOUT_S is about.
    """
    return node in usb_nodes() or os.path.exists(node)


def touch_1200(port, restore=True):
    """Fire the 16U2's erase-and-reset by dropping DTR at 1200 baud.

    `restore` picks *when* the speed goes back to 115200, and the two
    platforms measured so far want opposite answers - see the block
    below and issue #35. It is never selected from `sys.platform`;
    `_flash_attempt` tries the default and falls back on the evidence.
    """
    print(f"==> 1200-baud touch on {port} (erase + reset)"
          f"{'' if restore else ', closing at 1200'}")
    s = open_port(port, 1200)
    s.dtr = False                     # the erase+reset trigger
    time.sleep(0.1)
    if not restore:
        # macOS shape. The explicit DTR drop above does not reach the
        # wire there - measured by mac-bench across four arms on #35:
        # dropping DTR and then setting 115200 before the close does not
        # erase (nor does waiting 1.5 s first), and closing while still
        # at 1200 does. So on that host the 16U2 only ever sees the
        # transition the close performs, and it reads the line coding
        # that is current at that moment.
        #
        # This leaves the port stored at 1200, which is the hazard the
        # restore path exists to avoid - so the caller clears it while
        # the board is already erased and has nothing left to lose.
        s.close()
        time.sleep(1.5)
        return
    # Leave 115200 behind on the way out, not on a later open.
    #
    # restore_115200() below exists to stop the next open of this port
    # re-triggering the 16U2, and on Linux it cannot: os.open() applies
    # the tty's stored termios - still 1200 at that point - and the
    # kernel drives the modem lines before pyserial can set the speed,
    # so the function fires the hazard it was written to disarm. It runs
    # after wait_for_boot(), so flash.py then reports a successful flash
    # and exits leaving an erased board with the GPNVM boot bit clear.
    #
    # Measured on linux-x1: 3 of 3 boards running after bossac went to
    # SAM-BA on that one open, against 2 of 2 still running with the same
    # wait and no open. Setting the speed back here, on the fd that is
    # already open, means the stored termios is 115200 and the next open
    # is ordinary.
    try:
        s.baudrate = 115200
    except Exception:                                    # noqa: BLE001
        pass
    s.close()
    # The programming port's CDC belongs to the 16U2, which is not itself
    # reset, so the node normally persists. Give it a moment regardless.
    time.sleep(1.5)


def restore_115200(port):
    """Leave sane line coding behind.

    A port left at 1200 re-triggers the 16U2 erase-and-reset on the NEXT
    open, which presents as the board mysteriously restarting whenever a
    tool attaches.
    """
    try:
        open_port(port, 115200).close()
    except Exception as e:                               # noqa: BLE001
        # Do NOT swallow this silently. The docstring above says why: a
        # port left at 1200 re-triggers the 16U2's erase-and-reset on the
        # next open, so a silent failure here re-arms exactly the hazard
        # this function exists to disarm, and the next person sees a
        # board that wipes itself whenever a tool attaches.
        print(f"WARNING: could not restore {port} to 115200: {e}",
              file=sys.stderr)
        print("         The next open of this port may erase the board. "
              "Re-open it at", file=sys.stderr)
        print("         115200 before using it.", file=sys.stderr)


def wait_for_boot(watched, timeout=BOOT_WAIT_S):
    """Did the program actually start after bossac reset the board?

    bossac reports "Verify successful" for a write that lands perfectly
    and still leaves the board sitting in ROM SAM-BA - measured here at
    roughly two attempts in three on macOS, with no diagnostic anywhere.
    The board then has no native port, answers nothing, and the only
    symptom is silence, so it reads as a firmware fault rather than a
    flash that did not finish. It cost three false conclusions in one
    session, including "this branch does not boot" about a branch that
    boots fine - the interleaved control was what disproved it.

    The evidence is negative and that is the best available without
    knowing what the program enumerates: SAM-BA is 03EB:6124 and the
    running firmware is not, so a bootloader node that is still there
    after the reset window means the reset went back into the ROM
    monitor. Track A and Track B enumerate different things and a
    program need not enumerate at all, so do not test for a native port.

    The limitation, stated rather than hidden: with a second board in
    SAM-BA this cannot tell whose node it is looking at, which is the
    same attribution problem samba_nodes() documents. main() already
    refuses to guess in that case.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = set(samba_nodes())
        if not (now & watched) and not (watched and now):
            return True
        time.sleep(0.5)
    return False


def wait_for_quiet_bus(settle=1.5, timeout=10.0):
    """Block until the USB serial nodes stop changing.

    A touch that resets the board more than once - which the
    close-at-1200 arm does on a host that also re-fires on the reopen -
    churns the bus for several seconds, and every node seen during that
    window is provisional. Waiting for quiet is cheaper and more honest
    than guessing how many resets are in flight.
    """
    deadline = time.time() + timeout
    last, since = None, time.time()
    while time.time() < deadline:
        now = usb_nodes()
        if now != last:
            last, since = now, time.time()
        elif time.time() - since >= settle:
            return
        time.sleep(0.25)


def _await_samba(before, timeout=SAMBA_WAIT_S):
    """Wait for a ROM-bootloader node that was not there before.

    The touch erases; the chip then boots ROM SAM-BA on the native port.
    Take only a node that was NOT there beforehand - that is what makes
    it ours rather than whichever blank board happened to be plugged in.

    Poll gently and for longer. 5 s of 0.25 s polling was not enough on
    macOS - measured failing about one run in three - and re-enumerating
    every serial device four times a second while the board is itself
    re-enumerating is not free. Missing the node is no longer fatal,
    because the programming port is tried too, so this can afford to be
    patient rather than eager.

    Returns the node, or None - which means "not seen", never "the touch
    failed". Those are different claims and only usb_nodes() separates
    them.

    **The node has to still be there when this returns, and that is not
    automatic.** Any sequence that resets the board twice - the
    close-at-1200 arm on a host that also re-fires on the reopen - brings
    a bootloader node up, tears it down and brings a *differently named*
    one up. Taking the first sighting hands bossac a `/dev/ttyACM1` that
    no longer exists, and bossac does not fail on that: measured here, it
    spins at 100% CPU indefinitely on a named port that is absent. So a
    sighting is confirmed on a second poll before it is believed.
    """
    deadline = time.time() + timeout
    seen = None
    while time.time() < deadline:
        fresh = set(samba_nodes()) - before
        if len(fresh) > 1:
            sys.exit(f"the touch brought up {len(fresh)} bootloader "
                     f"nodes: {sorted(fresh)}. Refusing to guess.")
        node = fresh.pop() if len(fresh) == 1 else None
        if node is not None and node == seen:
            return node                  # same node twice: it has settled
        seen = node
        time.sleep(0.5)
    return None


def _flash_attempt(bossac, binary, args):
    """One erase-write-verify-reset cycle. Returns (rc, booted)."""
    # A bootloader node is only used if it can be attributed to the board
    # we were asked to flash. Attribution comes from one of two things: it
    # appeared as a result of *our* touch, or it is the only one on the
    # system and no port was named. Anything else and we would be aiming
    # an erase at somebody else's board - the same accident find_console
    # refuses, and the one the comment above it records.
    before = set(samba_nodes())
    console = None
    target = native_usb = None

    if args.samba:
        target, native_usb = args.samba, "true"
        print(f"==> SAM-BA        : {target} (named)")
    elif before and not args.port:
        if len(before) > 1:
            sys.exit(f"more than one board is in SAM-BA: {sorted(before)}. "
                     f"Pass --samba to say which, or --port to touch a "
                     f"specific programming port.")
        target, native_usb = next(iter(before)), "true"
        print(f"==> SAM-BA already up on {target} (native USB)")

    if target is None:
        console = find_console(args.port)
        print(f"==> port   : {console}")
        target, native_usb = console, "false"
        # Snapshot the bus before the touch, so that "the touch did
        # nothing at all" is a measurement rather than an inference. See
        # the fallback below.
        usb_before = usb_nodes()
        if args.close_at_1200:
            touch_1200(console, restore=False)
            restore_115200(console)
            wait_for_quiet_bus()
        else:
            touch_1200(console)
        fresh = _await_samba(before)

        if (fresh is None and usb_nodes() == usb_before
                and not before and not args.close_at_1200):
            # Nothing on the bus moved: no bootloader node arrived and
            # the firmware's own nodes are all still there. The board
            # never reset, so the 16U2 did not see the trigger.
            #
            # `not before` is load-bearing and was missing. A board that
            # is ALREADY in the bootloader has no firmware nodes to lose
            # and its SAM-BA node is not fresh, so the bus looks
            # unchanged however well the touch worked - the
            # discriminator has nothing to measure and says "nothing
            # happened" about a board that reset perfectly. Measured on
            # linux-x1: `--port` given against a board sitting in ROM
            # SAM-BA took the macOS arm on Linux, harmlessly but for the
            # wrong reason. When a bootloader node was there beforehand
            # the board is already where the flash needs it and there is
            # nothing to diagnose.
            #
            # This is macOS, and it is issue #35. The two shapes of the
            # touch are host-specific and they conflict - Linux needs the
            # speed restored on the open fd or the *next* open erases the
            # board it just flashed (measured 3 of 3 on linux-x1), while
            # macOS needs the close to happen at 1200 or nothing erases
            # at all (mac-bench's four arms). There is no one sequence
            # that is right on both.
            #
            # So it is chosen on evidence rather than on sys.platform.
            # The default arm is the one measured working on Linux and
            # Windows and it is not perturbed; this branch is reached
            # only where today's code already fails outright, which is
            # what makes it safe to add without a macOS bench to test on.
            print("==> nothing on the bus moved: the 16U2 did not take "
                  "the trigger.")
            print("    Retrying with the close-at-1200 shape (issue #35).")
            touch_1200(console, restore=False)
            # Clear the stored 1200 immediately. It is the hazard the
            # restore path exists to avoid, and here it is cheap: the
            # board is erased and in the ROM monitor, so even a host that
            # re-fires the trigger on this open costs one more reset of a
            # board with nothing left on it.
            restore_115200(console)
            # That open re-fires the trigger on some hosts, so the board
            # may be on its second reset. Let the bus stop moving before
            # asking what is on it.
            wait_for_quiet_bus()
            fresh = _await_samba(before)

        if fresh is not None:
            target, native_usb = fresh, "true"
            print(f"==> SAM-BA came up on {target} (native USB)")
        else:
            # A board that is ALREADY in the bootloader never produces a
            # node that "was not there before", so the rule above can
            # never fire for it - and that is exactly the board that
            # needs flashing most. Measured on windows-desk 2026-08-30:
            # a failed flash left the board erased in ROM SAM-BA on
            # COM10, and every subsequent attempt reported "no native
            # SAM-BA node" while COM10 sat in `list_ports.comports()`.
            # The recovery path could not recognise the state it exists
            # to recover from, and only --samba got the board back.
            #
            # Adopt it, but keep the reason the freshness rule exists:
            # it is there so a *different* blank board plugged into the
            # same host is not flashed by accident. So adopt only when
            # there is exactly one bootloader node to adopt, and say
            # that it is being adopted rather than seen to arrive -
            # those are different claims and the operator should get the
            # weaker one.
            stuck = samba_nodes()
            if len(stuck) == 1:
                target, native_usb = stuck[0], "true"
                print(f"==> no NEW SAM-BA node, but {target} is already "
                      f"one and is the only one: adopting it (a board "
                      f"already in the bootloader cannot produce a fresh "
                      f"node)")
            else:
                why = ("none on the bus" if not stuck
                       else f"{len(stuck)} on the bus, so which is ours "
                            f"is not decidable: " + ", ".join(stuck))
                print(f"==> no native SAM-BA node in {SAMBA_WAIT_S:.0f} s "
                      f"({why}); the programming port serves the ROM "
                      f"monitor too")

    # Try every route before giving up, because by this point the touch
    # has already erased the board: a failure here is not "nothing
    # happened", it is a board with no program in it.
    #
    # The native SAM-BA node is an OPTIMISATION, never a requirement. The
    # SAM3X ROM monitor listens on the UART behind the 16U2 as well, so
    # the programming port always works - that is why the old shell
    # script had no race at all. Treating the native node as the only
    # path is what made this fail one run in three on macOS and leave the
    # board unbootable.
    routes = []
    if native_usb == "true":
        routes.append((target, "true", "native SAM-BA"))
        if console:
            routes.append((console, "false", "programming port"))
    else:
        routes.append((target, "false", "programming port"))

    rc = 1
    for node, usb, label in routes:
        if not port_present(node):
            # The node was there when the route list was built and is not
            # now. Say so and move on rather than handing bossac a name
            # it will hang on - see BOSSAC_TIMEOUT_S.
            print(f"==> {label} {node} has gone from the bus; skipping it")
            continue
        print(f"==> bossac: writing {os.path.basename(binary)} via {node} "
              f"({label})")
        try:
            rc = subprocess.call(
                [bossac, "-i", "-d", f"--port={os.path.basename(node)}",
                 "-U", usb, "-e", "-w", "-v", "-b", binary, "-R"],
                timeout=BOSSAC_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            # Measured on linux-x1: given --port=ttyACM1 for a node that
            # had gone away, bossac burned 100% of a core for four
            # minutes and would not have stopped. There is no diagnostic
            # and no exit - the flash simply never returns, which reads
            # as a wedged board rather than a wrong argument. A bound is
            # the only thing that turns it back into a failure.
            print(f"    {label} did not return in {BOSSAC_TIMEOUT_S:.0f}s "
                  f"and was killed; the port was probably gone")
            rc = 1
        if rc == 0:
            break
        print(f"    {label} failed ({rc})")
        if (node, usb, label) is not routes[-1]:
            time.sleep(1.5)


    # Verified is not booted. See wait_for_boot().
    booted = True
    if rc == 0 and not args.no_boot_check:
        watched = {target} if native_usb == "true" else set()
        booted = wait_for_boot(watched)
        if not booted:
            print("==> flashed and verified, but the board came back "
                  "in the ROM bootloader")

    if console:
        restore_115200(console)
    if rc != 0:
        print("", file=sys.stderr)
        print(f"FLASH FAILED ({rc}) - and the board is now ERASED.",
              file=sys.stderr)
        print("The 1200-baud touch erases before anything is written, so "
              "there is no", file=sys.stderr)
        print("program on the board and it will not enumerate its native "
              "port. This is", file=sys.stderr)
        print("recoverable: just run the flash again. The board is sitting "
              "in ROM SAM-BA", file=sys.stderr)
        print("and the next run takes the 'already up' path.",
              file=sys.stderr)
        print("If it still fails, press ERASE then RESET on the board and "
              "retry.", file=sys.stderr)
    return rc, booted

#: Where the flash log lives. One JSON line per successful flash.
FLASH_LOG = os.path.join(REPO, "records", "flash-log.jsonl")


def _log_flash(binary) -> None:
    """Record which commit produced the image that was just flashed.

    The firmware deliberately does **not** carry a git SHA -
    `lib/due_shared/src/fw_version.h` gives the reason, and it is a good
    one: two toolchains would need build plumbing that can silently
    disagree, and `__DATE__ " " __TIME__` already answers "is this the
    image I just flashed".

    It does not answer "which commit is this", and those are different
    questions. On 2026-08-27 a bench published a noise floor a whole bit
    wrong because its board carried a build five minutes older than a DAC
    fix; both benches reported `fw 0.2.0` four hours and three commits
    apart, and nothing on the device could have said so.

    So the mapping is recorded here instead of baked in there: the tool
    that does the flashing is the one place that knows the binary and the
    tree at the same moment, and it cannot disagree with itself. Never
    raises - a measurement tool that fails at the bookkeeping step has
    still flashed the board.
    """
    try:
        import hashlib
        import json
        h = hashlib.sha256(open(binary, "rb").read()).hexdigest()
        root = image_work_tree(binary)
        def git(*a):
            if root is None:
                return None
            try:
                return subprocess.run(("git",) + a, cwd=root, text=True,
                                      capture_output=True,
                                      timeout=5).stdout.strip() or None
            except Exception:
                return None
        # What "dirty" actually was, not merely that it was.
        #
        # mac-bench's gap, raised on #35: sha256 of the binary changes on
        # every rebuild because the identity line carries __DATE__ and
        # __TIME__, so it cannot say two images were built from the same
        # source. That leaves repo_rev carrying the whole weight, and
        # repo_rev is identical for every dirty state of one commit. Their
        # log has a deliberately-reverted control image and a main image
        # on adjacent lines, both `(dirty)`, and nothing distinguishes
        # them.
        #
        # A hash of the working-tree delta does. Two images from the same
        # commit and the same edits share it; a revert changes it. It
        # answers "same dirty or different dirty", which is the question
        # that was unanswerable.
        #
        # `git diff HEAD` is tracked content; `git status --porcelain`
        # adds the names of untracked files, which the diff omits. An
        # untracked file's *content* is still invisible - CMakeLists lists
        # its sources explicitly so an untracked .c is not built, but that
        # is an argument about this repository rather than a guarantee.
        porcelain = git("status", "--porcelain")
        delta = (git("diff", "HEAD") or "") + "\n" + (porcelain or "")
        rec = {
            "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "binary": os.path.relpath(binary, REPO),
            "sha256": h,
            "repo_rev": git("rev-parse", "--short", "HEAD"),
            "source_root": (os.path.relpath(root, REPO)
                            if root and os.path.abspath(root)
                            != os.path.abspath(REPO) else None),
            "dirty": bool(porcelain),
            "dirty_sha": (hashlib.sha256(delta.encode()).hexdigest()
                          if porcelain else None),
        }
        os.makedirs(os.path.dirname(FLASH_LOG), exist_ok=True)
        with open(FLASH_LOG, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
        dirt = (f" (dirty {rec['dirty_sha'][:8]})" if rec["dirty"]
                else "")
        rev = rec["repo_rev"] or "no-commit (image outside any work tree)"
        where = f" from {rec['source_root']}" if rec["source_root"] else ""
        print(f"==> logged: {rev}{dirt}{where} sha {h[:12]}")
    except Exception as e:                                    # noqa: BLE001
        print(f"==> could not log the flash: {e}", file=sys.stderr)


def image_work_tree(binary):
    """The git work tree that *contains* `binary`, or None.

    Everything below used to ask `REPO` - the checkout flash.py itself
    lives in - what commit an image was built from. That is right only
    while the image was built here, and this bench is the one that
    flashes images that were not: it is the only bench that can reflash
    freely, so it is where a bisect happens, and a bisect builds in a
    second work tree on purpose.

    Measured on windows-desk 2026-08-30, reflashing three images to
    settle issue #5: the log recorded `repo_rev` b76f3c1, the current
    HEAD, against an image built from 8e300d2 in another work tree. The
    docstring on check_not_stale already names this exact failure - "a
    log that says a board runs a commit it does not run is worse than no
    log" - for a different cause. The cause is the same assumption, and
    it also made the staleness guard compare a historical image against
    today's sources, which refuses every correct bisect flash.

    `--show-toplevel` resolves a linked work tree to its own root, which
    is what a `git worktree add` bisect needs. An image outside every
    work tree - a copy in a scratch directory, which is also how a
    bisect gets done - has no commit, and saying so is the point: the
    caller writes null rather than the wrong answer.
    """
    try:
        top = subprocess.run(("git", "rev-parse", "--show-toplevel"),
                             cwd=os.path.dirname(os.path.abspath(binary)),
                             text=True, capture_output=True,
                             timeout=5).stdout.strip()
    except Exception:                                        # noqa: BLE001
        return None
    return top or None


def newest_source(binary):
    """(path, mtime) of the newest firmware source for `binary`'s track.

    Which paths those are comes from `provenance.fw_source_paths()`, so
    this and the provenance report cannot disagree about what a firmware
    image is built from - and the track comes from the binary's own
    path, the same rule `provenance.track_of_binary()` applies to the
    flash log.
    """
    track = provenance.track_of_binary(binary)
    root = image_work_tree(binary) or REPO
    newest, newest_at = None, 0.0
    for rel in provenance.fw_source_paths(track):
        base = os.path.join(root, rel)
        if os.path.isfile(base):
            cands = [base]
        elif os.path.isdir(base):
            cands = [os.path.join(r, f)
                     for r, _d, fs in os.walk(base) for f in fs
                     if not f.startswith(".")]
        else:
            continue
        for path in cands:
            try:
                at = os.path.getmtime(path)
            except OSError:
                continue
            if at > newest_at:
                newest, newest_at = path, at
    return newest, newest_at


def check_not_stale(binary, allow):
    """Refuse an image older than the source it is supposed to contain.

    Issue #35, and it is the flash log's integrity rather than a
    convenience. `enforce_clean_build` runs `--target clean` as a
    dependency of the link, and Ninja plans the whole graph before
    running any of it, so the clean deletes the objects the same plan is
    about to link. Two shapes, both measured:

      windows-desk, Ninja       the link fails loudly, and `flash.py`
                                then flashed the previous image and
                                logged the current commit against it
      linux-x1, Ninja 1.13.2    worse - the build **exits 0**, cleans 26
                                objects, never relinks, and leaves the
                                previous .bin and .elf in place. There
                                is no failure to ignore

    Make re-evaluates as it goes and relinks correctly on both benches,
    which is why this went unseen.

    Neither shape is flash.py's fault and both end here, because this is
    the last thing that touches the image before `_log_flash` writes a
    commit next to a sha. A log that says a board runs a commit it does
    not run is worse than no log, and `host/provenance.py` is built on
    believing it.

    mtimes, not git: a dirty tree is the normal state on a bench, and
    "the file changed after the image was built" is the question. A
    checkout can move an mtime backwards and produce a false alarm,
    which is the safe direction and is what --stale-ok is for.
    """
    try:
        built = os.path.getmtime(binary)
    except OSError:
        return
    newest, at = newest_source(binary)
    if newest is None or at <= built:
        return
    rel = os.path.relpath(newest, REPO)
    shown = binary if os.path.relpath(binary, REPO).startswith("..") \
        else os.path.relpath(binary, REPO)
    age = at - built
    msg = (f"the image is older than the firmware source it should "
           f"contain:\n"
           f"    {shown}  built {time.ctime(built)}\n"
           f"    {rel}  changed {time.ctime(at)}  ({age:.0f}s later)\n"
           f"Rebuild before flashing, and check the build actually "
           f"relinked rather than only reporting success - issue #35, "
           f"where a failed link left the previous .bin in place and "
           f"this script flashed it under the current commit.")
    if not allow:
        sys.exit("refusing to flash: " + msg +
                 "\n(--stale-ok flashes anyway and logs it as stale)")
    print("==> WARNING, flashing a stale image on request: " + msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.path.join(REPO, "build",
                                                  "baremetal_bringup.bin"))
    ap.add_argument("--port", help="programming port; discovered if omitted")
    ap.add_argument("--bossac", help="bossac executable; from the registry "
                                     "if omitted (CMake passes it)")
    ap.add_argument("--samba", help="bootloader port to flash directly, for "
                                    "when more than one board is blank")
    ap.add_argument("--retries", type=int, default=3,
                    help="re-flash this many times if the board comes back "
                         "in the bootloader instead of running the program "
                         "(default 3; 0 to report and stop)")
    ap.add_argument("--close-at-1200", action="store_true",
                    help="take the macOS-shaped touch straight away "
                         "instead of falling back to it (issue #35). "
                         "Use to test that arm on its own; the automatic "
                         "path needs no flag")
    ap.add_argument("--no-boot-check", action="store_true",
                    help="skip the post-flash boot check; for a program "
                         "that is expected not to run, or a second board "
                         "in SAM-BA that would confuse the attribution")
    ap.add_argument("--stale-ok", action="store_true",
                    help="flash an image older than its own sources. For "
                         "deliberately re-flashing a known-old build; it "
                         "is refused by default because the flash log "
                         "would otherwise record the current commit "
                         "against it (issue #35)")
    args = ap.parse_args()

    binary = os.path.abspath(args.bin)
    if not os.path.isfile(binary):
        sys.exit(f"no such binary: {binary}\nbuild it first: cmake --build build")
    check_not_stale(binary, args.stale_ok)

    bossac = args.bossac
    if not bossac:
        _, bossac = toolchain.resolve("bossac")
    if not bossac or not os.path.isfile(bossac):
        sys.exit("bossac not found. Add a pattern to toolchains.json, or "
                 "pass --bossac. Run: python3 tools/toolchain.py")

    print(f"==> bossac : {bossac}")
    print(f"==> binary : {binary}")

    for attempt in range(1, max(0, args.retries) + 2):
        if attempt > 1:
            # Re-flashing repeats the 1200-baud touch, which erases
            # first - that is the sequence that recovers a board stuck
            # in the ROM monitor, and doing it by hand is how this was
            # got through before the check existed.
            print(f"==> retrying ({attempt - 1} of {args.retries})")
        rc, booted = _flash_attempt(bossac, binary, args)
        if rc == 0 and booted:
            _log_flash(binary)
            return 0

    if rc == 0 and not booted:
        print("", file=sys.stderr)
        print(f"FLASHED BUT NOT RUNNING after {attempt} attempt(s).",
              file=sys.stderr)
        print("The write verified every time; the board is sitting in "
              "ROM SAM-BA and", file=sys.stderr)
        print("is not running the program. Run the flash again, or "
              "press ERASE then", file=sys.stderr)
        print("RESET on the board. Do not read this as a firmware "
              "fault: a board that", file=sys.stderr)
        print("never started looks exactly like one that hangs on "
              "boot.", file=sys.stderr)
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
