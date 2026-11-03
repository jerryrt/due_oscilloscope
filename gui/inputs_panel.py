"""Gain and coupling per input channel, for a device whose description offers them (the H7's: docs/20, G7). A Due has none, and the
panel stays hidden for it.

The panel only asks. What a code means after a start is whatever the device's description then says (the `started` reply carries
it), so the volts on screen follow the settings actually in force and not the ones typed.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class InputsPanel(QtWidgets.QGroupBox):
    #: The user changed a setting. The window restarts a running capture; a stopped device takes it at the next start.
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__("Inputs", parent)
        self.gain = {}                  # channel id -> combo
        self.coupling = {}
        self._form = QtWidgets.QFormLayout(self)
        self._ids = ()
        self._quiet = False
        self.hide()

    def set_device(self, desc):
        """Show the controls the description offers, set to what it says is in force; hide them for a device with none."""
        opts = (desc or {}).get("options") or {}
        chans = [c for c in (desc or {}).get("channels") or [] if "coupling" in c]
        if not opts.get("gain") or not chans:
            self._ids = ()
            self.hide()
            return
        ids = tuple(c["id"] for c in chans)
        self._quiet = True
        try:
            if ids != self._ids:
                while self._form.rowCount():
                    self._form.removeRow(0)
                self.gain.clear(); self.coupling.clear()
                for c in chans:
                    g = QtWidgets.QComboBox(); k = QtWidgets.QComboBox()
                    for code in opts["gain"]:
                        g.addItem(f"{code}", code)
                    for mode in opts.get("coupling", ["dc"]):
                        k.addItem(mode.upper(), mode)
                    g.currentIndexChanged.connect(lambda _i: self._emit())
                    k.currentIndexChanged.connect(lambda _i: self._emit())
                    self.gain[c["id"]], self.coupling[c["id"]] = g, k
                    row = QtWidgets.QHBoxLayout(); row.addWidget(g); row.addWidget(k)
                    self._form.addRow(c.get("label", f"CH{c['id']}"), row)
                self._ids = ids
            for c in chans:
                g, k = self.gain[c["id"]], self.coupling[c["id"]]
                g.setCurrentIndex(max(0, g.findData(c["calibration"]["gain_code"])))
                k.setCurrentIndex(max(0, k.findData(c["coupling"])))
                g.setToolTip(f"full scale about +-{c.get('range_v', '?')} V at the gain in force")
        finally:
            self._quiet = False
        self.show()

    def _emit(self):
        if not self._quiet:
            self.changed.emit()

    def options(self):
        """The `options` a start sends: gain and coupling, one per channel in id order. {} while there are no controls."""
        if not self._ids:
            return {}
        return {"gain": [self.gain[i].currentData() for i in self._ids], "coupling": [self.coupling[i].currentData() for i in self._ids]}
