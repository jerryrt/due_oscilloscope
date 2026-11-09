"""play_stop() and play_start() order their writes for a second task.

On Track C the console runs in a task of its own, so `play_service()`
can run between any two statements of `play_start()`/`play_stop()`.
Stopping the OUT DMA while `active` still read true made the service
pass count a channel stopped under it as a span that ended off a slot
edge (`play_partial`): 4 Track C runs in 10 failed on it, and neither A
nor B can, because their console runs inside the loop.

Board-free, on the source, because the window is a few microseconds and
no run can be made to land in it on purpose. The proof it is the cause
is a board one: a 3 ms delay in the old window gave partial=1 in 39 of
40 start/stop cycles, the same delay in the new order 0 of 40.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "drivers", "play.c"), encoding="utf-8").read()


def _body(name):
    m = re.search(r"^(?:bool|void) %s\(.*?\)\n\{\n(.*?)^\}\n" % name,
                  SRC, re.S | re.M)
    assert m, f"{name}() not found in drivers/play.c"
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)


def test_stop_clears_active_before_it_stops_the_dma():
    body = _body("play_stop")
    a = body.index("active = false;")
    d = body.index("usb_dma_mode_out(false)")
    assert a < d, "play_stop stops the OUT DMA while `active` is still true"


def test_start_raises_active_last():
    body = _body("play_start")
    last = body.rindex("active = true;")
    assert body.index("primed = false;") < last
    assert "usb_dma_mode_out(true)" in body[:last]
    assert not re.search(r"\b(fill_off|dma_inflight|play_produced)\s*=",
                         body[last:]), "state set after the service is let in"
