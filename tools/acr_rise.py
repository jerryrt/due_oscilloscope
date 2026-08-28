"""Does DACC_ACR's bias setting move the settling edge?

IBCTL is a slew-rate control, so rise is the figure it should touch -
the other bench measured saturated update rate instead and found 0.11%.
ABBA interleaved so drift cancels; the arm order flips every round.
"""
import argparse, io, json, os, re, statistics, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = r"C:\Jerry.Projects\due_oscilloscope"
sys.path.insert(0, os.path.join(REPO, "host"))
sys.path.insert(0, os.path.join(REPO, "tools"))
import measure, settletime, eqtime            # noqa: E402

ARMS = {"0x000": (0, 0), "0x10A": (2, 1)}


def read_acr(board):
    board.poll_console()
    board.cmd("?")
    txt = board.drain_console(0.6) or ""
    m = re.search(r"acr=([0-9a-fA-F]+)", txt)
    return m.group(1) if m else "?"


def one(board, arm, args):
    ch, core = ARMS[arm]
    board.poll_console()
    board.cmd(f"={ch},{core}I")
    board.drain_console(0.4)
    r = settletime.cmd_rise(board, args)
    return {"arm": arm, "rise_ns": r["rise_s"] * 1e9,
            "ticks": round(r["rise_s"] * eqtime.TC_CLOCK_HZ),
            "margin": r["margin"], "step_codes": r["step_codes"],
            "acr": read_acr(board)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    ra = argparse.Namespace(points=8, seconds=a.seconds, pre=80,
                            dac_hz=200000)
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop(); board.drain_console(0.5)
        for i in range(a.rounds):
            order = ["0x000", "0x10A"] if i % 2 == 0 else ["0x10A", "0x000"]
            for arm in order:
                rows.append(one(board, arm, ra))
                print(f"round {i} {arm}: {rows[-1]['ticks']} ticks "
                      f"({rows[-1]['rise_ns']:.1f} ns) acr={rows[-1]['acr']} "
                      f"margin {rows[-1]['margin']:.1f}x", flush=True)
    finally:
        try:
            board.stop(); measure.set_sync(board, "cycle")
        finally:
            board.close()
    print("\n== summary ==")
    for arm in ARMS:
        t = [r["ticks"] for r in rows if r["arm"] == arm]
        ns = [r["rise_ns"] for r in rows if r["arm"] == arm]
        acrs = sorted({r["acr"] for r in rows if r["arm"] == arm})
        print(f"{arm}: n={len(t)} ticks median {statistics.median(t)} "
              f"range {min(t)}-{max(t)} | ns median {statistics.median(ns):.1f} "
              f"| acr seen {acrs}")
    io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "acr_rise.json"), "w").write(json.dumps(rows, indent=1))


main()
