"""How far through a recording the replay is, and how to start it again.

A replay is the one source with an end, and until this bar there was no
way to see one coming: the trace simply stopped and the mode went to
`idle`, which looks exactly like a board that was told to stop. "How far
through am I" is the first question anyone asks of a recording, and the
daemon has always been able to answer it - `counters` on a `FileDevice`
carries `frames`, `frames_total`, `loops` and `at_end`, and the window
already polls that four times a second for the underrun count.

Shown only while the source is a recording. A board has no position and
a progress bar against one would be inventing a number.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class ReplayBar(QtWidgets.QWidget):
    """Position, pass count, and a Restart."""

    #: Play the file again from the beginning.
    restart = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.restart_btn = QtWidgets.QToolButton()
        self.restart_btn.setText("Restart")
        self.restart_btn.setToolTip("Play the recording again from the start")
        self.restart_btn.clicked.connect(self.restart)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(1)
        self.bar.setValue(0)
        # Frames rather than a percentage: the frame count is the unit
        # everything else about a recording is quoted in - the sidecar's
        # `frames`, the daemon's `frames_read`, the health panel - and a
        # percentage would be the one number here that does not join up
        # with the rest.
        self.bar.setFormat("%v / %m frames")
        self.bar.setMinimumWidth(160)

        self.state = QtWidgets.QLabel("")
        self.state.setMinimumWidth(96)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("Replay"))
        row.addWidget(self.restart_btn)
        row.addWidget(self.bar)
        row.addWidget(self.state)

    def set_position(self, counters):
        """Update from a `counters` reply. Ignores one that is not a file's.

        The position is `frames - loops * frames_total` because the
        replayed count runs on across a loop while the file starts
        again: the daemon counts what it sent, and where in the file
        that is has to be worked out from how many times it wrapped.
        """
        total = counters.get("frames_total")
        if not total:
            return
        loops = counters.get("loops") or 0
        played = counters.get("frames") or 0
        pos = max(0, min(total, played - loops * total))
        self.bar.setMaximum(total)
        self.bar.setValue(pos)

        if counters.get("at_end"):
            self.state.setText("at the end")
        elif loops:
            self.state.setText(f"pass {loops + 1}")
        else:
            self.state.setText("")

    def reset(self):
        self.bar.setMaximum(1)
        self.bar.setValue(0)
        self.state.setText("")
