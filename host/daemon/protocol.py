"""Framing between the daemon and its clients.

Four message types share one connection. Two carry JSON - commands
going up and events coming down - and two carry bytes that are never
parsed here: a device frame on its way to a client, and waveform data
on its way to the DAC.

The device frame crosses this boundary **verbatim**, header and all.
That is deliberate: sequence numbers, device timestamps and the overrun
flag stay in the bytes, so a client can prove continuity rather than
trust the daemon's word for it, and `measure.parse_frames` reads a
socket and a serial port identically. One parser, one definition of the
format.

Nothing here does I/O. That is what makes it testable without a board,
a socket, or a thread.
"""

from __future__ import annotations

import json
import struct

PROTOCOL_VERSION = 1

MAGIC = b"DU"

# magic, type, flags, body length
HDR = struct.Struct("<2sBBI")
HDR_LEN = HDR.size
assert HDR_LEN == 8

T_CMD = 1      # client -> daemon, JSON
T_EVT = 2      # daemon -> client, JSON
T_FRAME = 3    # daemon -> client, one device frame, untouched
T_AWG = 4      # client -> daemon, waveform bytes for playback

TYPE_NAMES = {T_CMD: "cmd", T_EVT: "evt", T_FRAME: "frame", T_AWG: "awg"}

# A ceiling on a single message, so a corrupt or hostile length cannot
# make the daemon allocate without bound. Waveform uploads are the
# largest legitimate message; the playback ring is 32 KB, and a client
# with more than 4 MB to send should send it in pieces.
MAX_BODY = 4 << 20


class ProtocolError(Exception):
    """The stream is not this protocol, or has lost its framing."""


def encode(mtype, body=b"", flags=0):
    """One message. `body` is bytes and is not inspected."""
    if mtype not in TYPE_NAMES:
        raise ProtocolError(f"unknown message type {mtype}")
    if len(body) > MAX_BODY:
        raise ProtocolError(
            f"body of {len(body)} bytes exceeds the {MAX_BODY} limit")
    return HDR.pack(MAGIC, mtype, flags, len(body)) + body


def encode_json(mtype, obj, flags=0):
    return encode(mtype, json.dumps(obj, separators=(",", ":")).encode(),
                  flags)


def decode_json(body):
    """Parse a JSON body into a dict.

    Anything that is not a JSON object is refused rather than passed on:
    every command and event in this protocol is keyed, and a bare list
    or string arriving where one is expected is a bug worth surfacing at
    the edge instead of three frames later.
    """
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError(f"body is not JSON: {e}") from None
    if not isinstance(obj, dict):
        raise ProtocolError(f"body is JSON {type(obj).__name__}, not an object")
    return obj


class Decoder:
    """Bytes in, whole messages out.

    A socket hands over arbitrary slices - half a header, three
    messages, one byte - so the decoder holds what it cannot yet use and
    returns only what is complete.

    It does **not** resynchronise on a bad magic. A stream that has lost
    its framing has already produced an unknown amount of garbage, and
    hunting for the next plausible magic in it invents structure that
    may not be there. Failing loudly at the first bad header is the
    honest answer, and the caller closes the connection.
    """

    def __init__(self, max_body=MAX_BODY):
        self._buf = bytearray()
        self._max = max_body

    def feed(self, data):
        """Return a list of (type, body) for everything now complete."""
        self._buf += data
        out = []
        while True:
            if len(self._buf) < HDR_LEN:
                return out
            magic, mtype, _flags, length = HDR.unpack_from(self._buf, 0)
            if magic != MAGIC:
                raise ProtocolError(
                    f"bad magic {bytes(magic)!r}: the stream is not framed")
            if mtype not in TYPE_NAMES:
                raise ProtocolError(f"unknown message type {mtype}")
            if length > self._max:
                raise ProtocolError(
                    f"declared body of {length} bytes exceeds the "
                    f"{self._max} limit")
            if len(self._buf) < HDR_LEN + length:
                return out
            body = bytes(self._buf[HDR_LEN:HDR_LEN + length])
            del self._buf[:HDR_LEN + length]
            out.append((mtype, body))

    @property
    def pending(self):
        """Bytes held back because the message is incomplete."""
        return len(self._buf)
