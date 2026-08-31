"""One reader on the stream during `start()`, not two. Issue #44.

`Server._read_loop` drains the device for the daemon's whole lifetime
and asks only `device.read()` whether there is anything to take. So
whatever `read()` gates on decides when that thread is allowed to touch
the descriptor.

`BoardDevice.start()` assigns `self.fd` and then spends seconds before
it is finished: `drain_until_quiet(cap=5.0)`, the `=<dac>,<adc>L`
command, a 0.2 s settle, and a console drain. While `read()` gated only
on `fd is None`, the reader thread was inside that window with it, and
**two threads split one stream**.

Both consequences are real and the second is #44's headline:

- the drain does not drain - bytes it was meant to discard reach
  subscribers instead;
- frames from the new run that arrive inside the window are consumed by
  `drain_until_quiet` and discarded. Tens to hundreds, at the start of a
  run, which is the phenomenon this issue is named for.

**`FakeDevice` has always gated on `running`.** That is why the whole
board-free tier could not see this: the fake implements the contract and
the real device did not, so every daemon test ran against the one that
was right. A test that only ever exercises the stand-in cannot find a
divergence between the stand-in and the thing.

So this asserts the gate on **both** implementations, from the outside,
by the behaviour rather than by reading the source: a device that is not
running hands the reader nothing, whatever its descriptor says.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "host"))


class _Fd:
    """A descriptor that would hand over data if anyone asked it.

    The point of the test is that nobody asks. If `read()` ever reaches
    this, the gate is open when it should be shut and `used` says so.
    """

    def __init__(self):
        self.used = False

    def fileno(self):
        self.used = True
        return 0

    def read(self, _n):
        self.used = True
        return b"x" * 4096


def _board_device_not_running():
    """A BoardDevice past `self.fd = ...` and short of `running = True`.

    Built without `__init__` on purpose. Constructing a real one opens
    ports; what is under test is a two-line gate, and the state that
    reaches it is exactly these three attributes.
    """
    from daemon import device as dev

    d = object.__new__(dev.BoardDevice)
    d.fd = _Fd()
    d.running = False          # start() has not finished
    d._rx = 0
    return d


def test_board_device_reads_nothing_before_start_finishes():
    d = _board_device_not_running()
    assert d.read(timeout=0.01) == b""
    assert not d.fd.used, (
        "BoardDevice.read() touched the descriptor while start() was "
        "still draining it - that is two threads on one stream, and the "
        "frames drain_until_quiet eats are issue #44's lost frames")
    assert d._rx == 0


def test_the_gate_is_running_and_not_only_the_descriptor():
    """A live descriptor is not sufficient; `running` is required.

    Written as its own case because the previous gate passed a test that
    only ever set `fd = None`. Every value here is the *permissive* one
    except `running`, so nothing but the flag can be what stops it.
    """
    d = _board_device_not_running()
    assert d.fd is not None
    assert d.read(timeout=0.01) == b""


def test_fake_device_gates_the_same_way():
    """The stand-in and the thing agree, which is what was missing.

    `FakeDevice` was already right. Asserting it here means a future
    change to either one has to keep them in step, rather than the fake
    silently continuing to model a contract the real device abandoned.
    """
    from daemon import device as dev

    f = dev.FakeDevice()
    assert not f.running
    assert f.read(timeout=0.01) == b""
