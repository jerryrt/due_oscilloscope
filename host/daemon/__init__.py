"""The streaming daemon: it owns the ports, the real-time feeder and
the device console, and serves clients over a socket.

See `docs/daemon-api.md` for the wire protocol and the command
catalogue, and `docs/frontend.md` for why this is a separate process
from the GUI at all.

Stdlib only, like everything else under `host/`.
"""

from . import protocol  # noqa: F401

PROTOCOL_VERSION = protocol.PROTOCOL_VERSION
