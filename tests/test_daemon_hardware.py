"""The daemon against the real board.

`test_daemon_api.py` covers the API without hardware, deliberately.
What cannot be covered that way is the one thing this file checks: that
`BoardDevice` drives a real Due, that whole frames come out of a real
serial stream, and that the daemon's teardown leaves the port in a
state the next run can open. Everything else about signals and timing
belongs to the suite around it.

Kept to one streaming case on purpose. This is the slowest kind of test
in the project and its value is the wiring, not the measurement.
"""

import time

import pytest

import measure
from daemon import client as clientmod
from daemon import device as devmod
from daemon import server as servermod


@pytest.mark.slow
@pytest.mark.scope
def test_the_daemon_streams_real_frames_and_lets_go_of_the_port(board, track):
    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=15.0)
    try:
        c.connect()
        assert c.hello("control")["device"]["kind"] == "board"
        c.subscribe()
        c.call("start", mode="capture", preset="1")

        frames = c.wait_frames(20, timeout=20.0)
        assert all(len(f) == devmod.FRAME_BYTES for f in frames)

        ps = measure._finish(measure.parse_frames(b"".join(frames)))
        assert ps.frames >= 20
        assert ps.crc_bad == 0, "frames reached the client corrupt"
        assert ps.seq_gaps == 0, (
            f"{ps.seq_gaps} sequence gaps: the daemon lost frames the "
            f"device sent")
        assert ps.declared_rate_hz > 0

        st = c.call("status")["status"]
        assert st["running"] is True
        assert st["frames_read"] >= 20
        assert st["discarded_bytes"] < devmod.FRAME_BYTES, (
            "more than one frame's worth of bytes was discarded before "
            "framing locked on")

        c.call("stop")
    finally:
        c.close()
        srv.stop()

    # The port must be usable immediately afterwards. A daemon that
    # leaves the device streaming, or the native node held, turns into
    # the next run's mystery.
    time.sleep(0.5)
    fd = board.open_native()
    try:
        measure.drain_until_quiet(fd, quiet=0.3, cap=3.0)
    finally:
        board.close_native(fd)
