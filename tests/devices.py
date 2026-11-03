"""Which hardware a run can use, decided without opening a port, and what a run did not do for want of it.

The decisions are plain functions so a test can feed them faked states: the conftest fixtures only call them. A test that needs a device and
finds none SKIPS with a reason that names the device and the way to get it, and the end-of-run summary counts those skips per device - a skip
is not a pass (CLAUDE.md), and `--require-board` / `--require-h7` turn the skip into a failure for harnesses that score by pytest's summary.
"""

H7_REASONS = {
    "boot_loader": "the H7 is in the stock boot loader (0483:5720), not running an image: flash one with "
                   "targets/h7tool/tools/h7_flash_wait.sh <image>",
    "absent": "no H7 is attached (1209:0001 with interfaces 0 and 2, or 0483:5720 in the boot loader)",
}


def h7_decision(state, require):
    """('ok'|'skip'|'fail', reason) for a test that needs a running H7."""
    if state == "running":
        return "ok", ""
    reason = f"no H7: {H7_REASONS.get(state, 'state ' + repr(state))}"
    return ("fail" if require else "skip"), (f"--require-h7 given but {reason}" if require else reason)


def device_of_skip(reason):
    """'Due', 'H7' or None: which device a skip reason is about. Matches the two phrases the fixtures use, nothing broader."""
    r = str(reason)
    if r.startswith("Skipped: "):           # pytest stores a skip's reason with this prefix in the report's longrepr
        r = r[len("Skipped: "):]
    if r.startswith("no H7") or "--require-h7" in r:
        return "H7"
    if r.startswith("no board") or r.startswith("board runs track"):
        return "Due"
    return None


def header_lines(census):
    """The lines printed at the start of a run: what is attached, so a reader knows which tiers can execute."""
    due, h7 = census["due"], census["h7"]
    if due["programming"] or due["native"]:
        d = f"Due attached (programming {due['programming'] or '-'}, native {', '.join(due['native']) or '-'})"
    else:
        d = "Due absent"
    if h7 == "running":
        h = f"H7 running an image ({census['h7_paths'][0]}, {census['h7_paths'][1]})"
    elif h7 == "boot_loader":
        h = "H7 in the stock boot loader (0483:5720): tests that need a running image will skip"
    else:
        h = "H7 absent" if h7 == "absent" else f"H7 {h7}"
    return [f"devices: {d}; {h}"]


def summary_lines(skipped_reasons):
    """The end-of-run lines for tests that did not run for want of a device; empty when none were."""
    n = {"Due": 0, "H7": 0}
    for r in skipped_reasons:
        k = device_of_skip(r)
        if k:
            n[k] += 1
    if not any(n.values()):
        return []
    parts = [f"{k}: {v}" for k, v in n.items() if v]
    return ["tests NOT run for want of a device (a skip is not a pass) - " + ", ".join(parts)]
