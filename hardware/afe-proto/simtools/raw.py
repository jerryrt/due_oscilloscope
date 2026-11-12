"""Read ngspice binary raw files into numpy, one Plot per analysis.

    plots = read_raw("deck.raw")
    tran = plots["Transient Analysis"]
    tran["time"], tran["v(out)"]

Real plots give float64 arrays, complex plots (AC, noise-free) complex128.
Only the binary format ngspice writes with `-r` in batch mode is read;
an ASCII file is refused rather than guessed at.
"""
import re
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Plot:
    title: str
    name: str
    flags: str
    npoints: int
    names: list
    types: list
    data: np.ndarray = field(repr=False)     # shape (npoints, nvars)

    def __getitem__(self, var):
        return self.data[:, self.names.index(var.lower())]

    def __contains__(self, var):
        return var.lower() in self.names


def read_raw(path):
    buf = open(path, "rb").read()
    plots, pos = {}, 0
    while pos < len(buf):
        end = buf.find(b"Binary:\n", pos)
        if end < 0:
            if b"Values:" in buf[pos:]:
                raise ValueError(f"{path}: ASCII raw file; rerun ngspice with binary output")
            break
        head = buf[pos:end].decode("latin-1")
        title = re.search(r"^Title: (.*)$", head, re.M)
        plotname = re.search(r"^Plotname: (.*)$", head, re.M).group(1).strip()
        flags = re.search(r"^Flags: (.*)$", head, re.M).group(1).strip()
        nvars = int(re.search(r"^No\. Variables: (\d+)", head, re.M).group(1))
        npts = int(re.search(r"^No\. Points: (\d+)", head, re.M).group(1))
        vblock = head.split("Variables:\n", 1)[1]
        rows = [l.split() for l in vblock.splitlines() if l.strip()]
        if len(rows) != nvars:
            raise ValueError(f"{path}: header lists {len(rows)} variables, says {nvars}")
        names = [r[1].lower() for r in rows]
        types = [r[2] for r in rows]
        cplx = "complex" in flags
        dt = np.dtype("<c16") if cplx else np.dtype("<f8")
        nbytes = npts * nvars * dt.itemsize
        start = end + len(b"Binary:\n")
        if start + nbytes > len(buf):
            raise ValueError(f"{path}: truncated, plot {plotname!r} wants {nbytes} bytes, {len(buf) - start} left")
        data = np.frombuffer(buf, dtype=dt, count=npts * nvars, offset=start).reshape(npts, nvars).copy()
        if cplx and names[0] == "frequency":
            # ngspice leaves the imaginary half of the frequency column uninitialised: it holds
            # process-dependent pointer bits (measured: two identical runs differ in those 80 bytes
            # and nowhere else). The frequency is real, so keep only its real part.
            data[:, 0] = data[:, 0].real
        key = plotname
        while key in plots:
            key += "'"            # a repeated analysis keeps all its plots
        plots[key] = Plot(title.group(1) if title else "", plotname, flags, npts, names, types, data)
        pos = start + nbytes
    if not plots:
        raise ValueError(f"{path}: no plots found")
    return plots
