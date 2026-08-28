"""The health panel.

Built first, not last, on purpose. Every counter here exists because
something once looked right on screen while the data was wrong: a clean
`seq_gaps=0 crc_bad=0 under=0` has coexisted with a badly degraded
signal more than once in this project's history. A trace with no way to
see what it cost to draw is a trace that can lie to you quietly.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


FIELDS = [
    ("link", "Link"),
    ("source", "Source"),
    ("role", "Role"),
    ("mode", "Mode"),
    ("rate", "Rate (actual)"),
    ("frames", "Frames shown / read"),
    ("dropped", "Dropped to us"),
    ("gaps", "Sequence gaps"),
    ("breaks", "Discontinuities"),
    ("overruns", "Device overruns"),
    ("read_gap", "Read gap max"),
    ("feed", "Feed gap max"),
    ("fanout", "Fan-out max"),
    ("recording", "Recording"),
]

# Anything in here turns the value red when it is not zero-ish. These
# are the numbers that mean the picture is not the signal.
ALARMS = {"dropped", "gaps", "breaks", "overruns"}


class HealthPanel(QtWidgets.QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Health", parent)
        self._labels = {}
        form = QtWidgets.QFormLayout(self)
        for key, text in FIELDS:
            lab = QtWidgets.QLabel("-")
            # Selectable, because the first thing anyone does with a bad
            # number is paste it into a message.
            lab.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse)
            self._labels[key] = lab
            form.addRow(text, lab)

    def value(self, key):
        """What this field is showing, as text.

        Issue #8's C1. The tests read `_labels[key].text()`, which makes
        a private name part of the suite's contract - so nobody renames
        it, which is the opposite of what a private name is for.
        `NoticeBar` and `ReplayBar` were built with read properties from
        the start; this is the same thing for the panels that were not.

        Text rather than the value that was set, deliberately: what a
        test wants to know is what a person would see, and `set()`
        stringifies. A test asserting on a number the panel might be
        formatting differently is not testing the panel.
        """
        lab = self._labels.get(key)
        return None if lab is None else lab.text()

    def alarming(self, key):
        """Whether the field is showing its alarm styling."""
        lab = self._labels.get(key)
        return bool(lab is not None and lab.styleSheet())

    def keys(self):
        """Every field this panel has, so a test can assert on the set."""
        return tuple(k for k, _ in FIELDS)

    def set(self, key, value, alarm=None):
        lab = self._labels.get(key)
        if lab is None:
            return
        lab.setText(str(value))
        if alarm is None:
            alarm = key in ALARMS and _nonzero(value)
        lab.setStyleSheet("color: #c0392b; font-weight: bold;" if alarm
                          else "")


def _nonzero(value):
    try:
        return float(str(value).split()[0].replace(",", "")) > 0
    except (TypeError, ValueError):
        return False
