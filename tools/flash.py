#!/usr/bin/env python3
"""Flash a bare-metal .bin to the Due, on any host.

This is the single implementation; tools/flash.sh is a shim onto it and
the CMake `flash` target invokes it. Where the tools live is CMake's
business (cmake/hosttools.cmake, toolchains.json) - it passes --bossac.
Run standalone and this resolves the same registry itself.

The Due enters SAM-BA when the programming port is opened at 1200 baud:
the 16U2 sees the baud change followed by DTR dropping, and asserts ERASE
then RESET. That baud rate is a control signal here, not a data rate.
pyserial performs that identically on every platform, which is why there
is no OS branch in this file.

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


def touch_1200(port):
    print(f"==> 1200-baud touch on {port} (erase + reset)")
    s = open_port(port, 1200)
    s.dtr = False                     # the erase+reset trigger
    time.sleep(0.1)
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
        touch_1200(console)
        target, native_usb = console, "false"
        # The touch erases; the chip then boots ROM SAM-BA on the native
        # port. Take only a node that was NOT there beforehand - that is
        # what makes it ours rather than whichever blank board happened
        # to be plugged in.
        # Poll gently and for longer. 5 s of 0.25 s polling was not
        # enough on macOS - measured failing about one run in three - and
        # re-enumerating every serial device four times a second while
        # the board is itself re-enumerating is not free. Missing the
        # node is no longer fatal, because the programming port is tried
        # too, so this can afford to be patient rather than eager.
        deadline = time.time() + SAMBA_WAIT_S
        while time.time() < deadline:
            fresh = set(samba_nodes()) - before
            if len(fresh) == 1:
                target, native_usb = fresh.pop(), "true"
                print(f"==> SAM-BA came up on {target} (native USB)")
                break
            if len(fresh) > 1:
                sys.exit(f"the touch brought up {len(fresh)} bootloader "
                         f"nodes: {sorted(fresh)}. Refusing to guess.")
            time.sleep(0.5)
        else:
            print(f"==> no native SAM-BA node in {SAMBA_WAIT_S:.0f} s; "
                  f"the programming port serves the ROM monitor too")

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
        print(f"==> bossac: writing {os.path.basename(binary)} via {node} "
              f"({label})")
        rc = subprocess.call([bossac, "-i", "-d",
                              f"--port={os.path.basename(node)}",
                              "-U", usb, "-e", "-w", "-v", "-b", binary, "-R"])
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
        def git(*a):
            try:
                return subprocess.run(("git",) + a, cwd=REPO, text=True,
                                      capture_output=True,
                                      timeout=5).stdout.strip() or None
            except Exception:
                return None
        rec = {
            "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "binary": os.path.relpath(binary, REPO),
            "sha256": h,
            "repo_rev": git("rev-parse", "--short", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        }
        os.makedirs(os.path.dirname(FLASH_LOG), exist_ok=True)
        with open(FLASH_LOG, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
        print(f"==> logged: {rec['repo_rev']}"
              f"{' (dirty)' if rec['dirty'] else ''} sha {h[:12]}")
    except Exception as e:                                    # noqa: BLE001
        print(f"==> could not log the flash: {e}", file=sys.stderr)


def newest_source(binary):
    """(path, mtime) of the newest firmware source for `binary`'s track.

    Which paths those are comes from `provenance.fw_source_paths()`, so
    this and the provenance report cannot disagree about what a firmware
    image is built from - and the track comes from the binary's own
    path, the same rule `provenance.track_of_binary()` applies to the
    flash log.
    """
    track = provenance.track_of_binary(binary)
    newest, newest_at = None, 0.0
    for rel in provenance.fw_source_paths(track):
        base = os.path.join(REPO, rel)
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
