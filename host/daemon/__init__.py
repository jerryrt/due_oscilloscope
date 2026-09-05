"""The streaming daemon: it owns the ports, the real-time feeder and
the device console, and serves clients over a socket.

See `docs/daemon-api.md` for the wire protocol and the command
catalogue, and `docs/frontend.md` for why this is a separate process
from the GUI at all.

Nothing compiled: the fake and file sources are stdlib alone, and a
board needs only pyserial, which is pure Python - so this runs on a
free-threaded interpreter without waiting for wheels.
"""

from . import protocol  # noqa: F401

PROTOCOL_VERSION = protocol.PROTOCOL_VERSION
