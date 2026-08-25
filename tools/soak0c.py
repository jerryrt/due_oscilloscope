"""Soak port open/close cycles, which is the thing 0c actually hangs in.

Every previous attempt soaked *benches* and every close came back in
0.00 s. The wedge is in close(), so this soaks close() - with write URBs
deliberately still in flight, because a close with nothing outstanding
has never been seen to hang.
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'host'))
import measure
import control, ports

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 60
MODE = sys.argv[2] if len(sys.argv) > 2 else "play-nodrain"

b = measure.Board('/dev/cu.usbmodem141201')
b.banner()
time.sleep(2.0)

worst = 0.0
for i in range(CYCLES):
    fd = b.open_native(blocking_writes=True)
    measure.drain_until_quiet(fd, quiet=0.2, cap=3.0)

    if MODE.startswith("play"):
        b.cmd(f"={measure.hz_for(65)},{measure.hz_for(130)},2P")
        time.sleep(0.3)

    # Push bytes so close() has write URBs to wait on. 256 KB is well
    # inside the 55-450 KB the CDC driver buffers below the tty layer.
    payload = bytes(256 * 1024)
    try:
        os.write(fd, payload)
    except OSError as e:
        print(f"  cycle {i}: write failed {e!r}")

    if "stop" in MODE:
        b.cmd("0")
        time.sleep(0.2)

    t0 = time.time()
    try:
        b.close_native(fd)
    except Exception as e:                                  # noqa: BLE001
        print(f"  cycle {i}: close raised {e!r}")
    cost = time.time() - t0
    worst = max(worst, cost)
    if cost > 0.5 or b.wedged:
        print(f"  cycle {i}: close took {cost:.2f} s  wedged={b.wedged}")
    if b.wedged:
        print(f"WEDGED at cycle {i} after {i+1} cycles")
        # The control channel is a different interface and keeps
        # answering while the sample port is stuck. This is the reading
        # every previous 0c diagnosis had to assume.
        try:
            node = b.command_node()
            with control.Control(node, timeout=2.0) as c:
                a = c.counters(); time.sleep(1.5); z = c.counters()
                print(f"  WHILE WEDGED, over the control channel:")
                print(f"    loop passes  +{z['loop_passes']-a['loop_passes']}"
                      f" in {(z['dev_us']-a['dev_us'])/1e6:.2f} s")
                print(f"    drain polls  +{z['drain_polls']-a['drain_polls']}")
                print(f"    play active? abandoned={z['abandoned']}"
                      f"  underruns={z['underruns']}")
        except Exception as e:                              # noqa: BLE001
            print(f"  control channel unreadable: {e!r}")
        break
    if not MODE.startswith("play"):
        pass
    else:
        b.cmd("0")
        time.sleep(0.2)
    b.drain_console(0.2)
else:
    print(f"{CYCLES} cycles, no wedge. worst close {worst:.3f} s")
