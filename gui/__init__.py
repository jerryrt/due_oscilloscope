"""The front end: a Qt window over the daemon's socket.

Nothing here talks to hardware. It talks to `host/daemon`, which owns
the ports and the real-time threads, for the reasons in
`docs/frontend.md`. Run it against `python3 -m daemon --fake` and no
board is involved at all.
"""
