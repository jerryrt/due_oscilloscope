"""Automatic measurements, and what they refuse to say.

The numbers themselves are computed in `gui.stream.measure`, which is
Qt-free so a headless test can check them against a tone built by
construction. This is only the display.

The panel exists in the shape it does because of a rule rather than a
layout preference. `gui.stream.measure` returns a value or None with a
reason, never a plausible-looking figure, and this shows the reason in
place of the number when there is one - "discontinuity in window" where
the volts would be. A field that quietly reverts to its last good value,
or shows a dash, invites reading a stale number as a live one. That is
the failure `docs/status.md` records more than once: a clean-looking
display over data that was wrong.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from . import stream


#: key in the measure() result, label, formatter
FIELDS = [
    ("vpp_v", "Vpp", lambda v: f"{v:.4f} V"),
    ("mean_v", "Mean", lambda v: f"{v:.4f} V"),
    ("rms_v", "RMS", lambda v: f"{v:.4f} V"),
    ("freq_hz", "Frequency", lambda v: f"{v:,.1f} Hz"),
    ("period_s", "Period", lambda v: f"{v * 1e6:,.2f} us"),
    ("duty", "Duty", lambda v: f"{v * 100:.1f} %"),
]


class MeasurePanel(QtWidgets.QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Measure", parent)
        self._labels = {}
        form = QtWidgets.QFormLayout(self)
        for key, text, _fmt in FIELDS:
            lab = QtWidgets.QLabel("-")
            # Selectable for the same reason the health panel's are: the
            # first thing anyone does with a number is paste it
            # somewhere.
            lab.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self._labels[key] = lab
            form.addRow(text, lab)

        # The cursors' own reading, kept separate from the automatic
        # measurements above it. They answer different questions - the
        # automatic ones describe the whole sweep, the cursors describe
        # two points somebody chose - and merging them into one list
        # would make it unclear which is which.
        self.cursor = QtWidgets.QLabel("-")
        self.cursor.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.cursor.setWordWrap(True)
        form.addRow("Cursors", self.cursor)

        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #c0392b;")
        form.addRow("", self.note)

        # Which reference the volts above are in. Not decoration: the
        # DAC->ADC loop is ratiometric, so the board cannot measure its
        # own reference and every volt here is scaled by a number that
        # came from somewhere else. A reading that cannot be attributed
        # is not a measurement - see docs/measurement-suite.md.
        self.reference = QtWidgets.QLabel(
            f"ADVREF {stream.ADVREF_MV} mV, {stream.ADVREF_SOURCE}")
        self.reference.setStyleSheet("color: #7f8c8d;")
        form.addRow("", self.reference)

    def set_cursor(self, text):
        """Show the cursors' reading, or a dash when they are off."""
        self.cursor.setText(text or "-")

    def update_from(self, result):
        """Show a measure() result, refusals and all."""
        note = result.get("note")
        for key, _text, fmt in FIELDS:
            value = result.get(key)
            lab = self._labels[key]
            if value is None:
                # The reason, not a dash, and not the previous value.
                lab.setText(note or "-")
                lab.setStyleSheet("color: #7f8c8d; font-style: italic;")
            else:
                lab.setText(fmt(value))
                lab.setStyleSheet("")
        self.note.setText("")
