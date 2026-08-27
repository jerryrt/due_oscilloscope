"""One line that stays until something replaces it.

`statusBar().showMessage()` was the window's only error channel, and
every message overwrote the last - including the ones the 4 Hz status
poll writes, so the device's own refusal could be gone in 250 ms. That
is the one message `docs/frontend.md` rule 4 says to show.

The pattern is not new here. `gui/awg.py` already keeps a persistent,
wrapped, red label for the generator's local refusals, and reserves the
height a wrapped one needs because "a truncated explanation is worse
than a bare no - it reads as the whole answer". This is that label,
generalised, so the device's refusals get the same treatment as the
panel's own and there is one answer to "where does a message go" rather
than two.

It is deliberately not a dialog. A modal interrupts to say something
the user can neither act on nor keep, and this project's refusals name
a limit worth reading twice - the rate the hardware will actually make,
the offset that would fit.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


#: Same red as the generator panel's refusals, for the same reason: a
#: refusal should look like one wherever it comes from.
ERROR_STYLE = "color: #c0392b; font-weight: bold;"
INFO_STYLE = ""


class NoticeBar(QtWidgets.QFrame):
    """A dismissible line under the plot. Hidden when there is nothing.

    Hidden rather than kept empty at a reserved height: this sits above
    the control strip in a window whose vertical budget is the trace,
    and 40 px of permanently blank strip costs more than the resize
    costs. The trace is a rolling redraw; it does not mind changing
    width or height between frames.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

        self.label = QtWidgets.QLabel("")
        self.label.setWordWrap(True)
        # Selectable, because the first thing anyone does with a
        # refusal is paste it into a message.
        self.label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self.dismiss = QtWidgets.QToolButton()
        self.dismiss.setText("×")
        self.dismiss.setAutoRaise(True)
        self.dismiss.setToolTip("Dismiss")
        self.dismiss.clicked.connect(self.clear)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 4, 4, 4)
        row.addWidget(self.label, 1)
        row.addWidget(self.dismiss, 0, QtCore.Qt.AlignTop)
        self.hide()

    # -- what to say --------------------------------------------------
    def error(self, text):
        """A refusal or a failure. Stays until dismissed or replaced."""
        self._show(text, ERROR_STYLE)

    def info(self, text):
        """Something worth keeping on screen that is not a failure."""
        self._show(text, INFO_STYLE)

    def clear(self):
        self.label.setText("")
        self.hide()

    def _show(self, text, style):
        if not text:
            self.clear()
            return
        self.label.setStyleSheet(style)
        self.label.setText(text)
        self.show()

    # -- what it is saying, for a test or a caller --------------------
    @property
    def text(self):
        return self.label.text()

    @property
    def showing(self):
        """Whether this bar is saying something.

        `isHidden()` rather than `isVisible()`: a child of a window that
        has not been shown yet is not visible, and "the notice is up" is
        a question about this widget rather than about whether anyone is
        looking at the window it lives in.
        """
        return bool(self.label.text()) and not self.isHidden()
