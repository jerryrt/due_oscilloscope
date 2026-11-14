#!/usr/bin/env python3
"""Build the intern's input package for the status-LED task.

    python3 make_package.py OUT_DIR [--datasheets DIR] [--no-datasheets]

Writes OUT_DIR/coppia-led-task/ and OUT_DIR/coppia-led-task.zip. Every
file is copied from the repository as it stands, except the brief and the
scope netlist, which come from this folder. The part datasheets are vendor
PDFs kept out of git: they are read from --datasheets (default: the
untracked hardware/afe-proto/models/ of the checkout this script sits in,
or of the main checkout when run from a worktree).
"""
import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AFE = HERE.parents[2]                    # hardware/afe-proto
REPO = AFE.parents[1]
NAME = "coppia-led-task"

# (source, destination in the package); a source directory is copied whole
FILES = [
    (HERE / "brief.md", "BRIEF.md"),
    (AFE / "v2/kicad/afe-v2.kicad_pro", "afe-proto/v2/kicad/afe-v2.kicad_pro"),
    (AFE / "v2/kicad/afe-v2.kicad_sch", "afe-proto/v2/kicad/afe-v2.kicad_sch"),
    (AFE / "v2/kicad/fp-lib-table", "afe-proto/v2/kicad/fp-lib-table"),
    (AFE / "v2/kicad/sym-lib-table", "afe-proto/v2/kicad/sym-lib-table"),
    (AFE / "v2/kicad/lib", "afe-proto/v2/kicad/lib"),
    (AFE / "v2/layout/integrated/afe-v2-integrated.kicad_pcb", "afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb"),
    (AFE / "v2/layout/integrated/afe-v2-integrated.kicad_pro", "afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pro"),
    (AFE / "v2/layout/integrated/fp-lib-table", "afe-proto/v2/layout/integrated/fp-lib-table"),
    (AFE / "v2/layout/integrated/sym-lib-table", "afe-proto/v2/layout/integrated/sym-lib-table"),
    (AFE / "v2/layout/integrated/lib", "afe-proto/v2/layout/integrated/lib"),
    (AFE / "kicad/lib/afe.kicad_sym", "afe-proto/kicad/lib/afe.kicad_sym"),
    (AFE / "kicad/lib/afe.pretty", "afe-proto/kicad/lib/afe.pretty"),
    (AFE / "kicad/lib/afe.3dshapes", "afe-proto/kicad/lib/afe.3dshapes"),
    (REPO / "hardware/reference/arduino-due/models/assembly/Arduino-Due.step", "due/Arduino-Due.step"),
    (HERE / "package/sim/scope_v2.cir", "sim/scope_v2.cir"),
    (AFE / "docs/due-header-table.md", "docs/due-header-table.md"),
    (REPO / "docs/afe.md", "docs/afe.md"),
    (REPO / "docs/afe-v2.md", "docs/afe-v2.md"),
    (AFE / "v2/jlc-basic.csv", "jlc-basic.csv"),
    (REPO / "docs/datasheets/Atmel-SAM3X-SAM3A-Series-Datasheet.pdf", "datasheets/SAM3X8E.pdf"),
]
OPEN_MODELS = ["tph2502", "lm27762", "ref3030", "bav99", "ads1115"]
FILES += [(AFE / f"models-open/{p}-open", f"models/{p}-open") for p in OPEN_MODELS]

# part datasheets: (file under the datasheet folder, name in the package)
DATASHEETS = [
    ("tph2502/tph2502.pdf", "TPH2502.pdf"),
    ("lm27762/lm27762.pdf", "LM27762.pdf"),
    ("ref3030/ref30.pdf", "REF3030E.pdf"),
    ("bav99/bav99.pdf", "BAV99.pdf"),
    ("ads1115/ads1115.pdf", "ADS1115.pdf"),
]


def default_datasheets():
    """hardware/afe-proto/models of this checkout, else of the main checkout (a worktree has no untracked files)."""
    here = AFE / "models"
    if all((here / s).exists() for s, _ in DATASHEETS):
        return here
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).parent / "hardware/afe-proto/models"
    except (OSError, subprocess.CalledProcessError):
        return here


def build(out, datasheets):
    root = Path(out) / NAME
    if root.exists():
        shutil.rmtree(root)
    for src, dst in FILES:
        if not src.exists():
            sys.exit(f"missing: {src}")
        d = root / dst
        d.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, d)
    if datasheets is not None:
        for s, n in DATASHEETS:
            p = Path(datasheets) / s
            if not p.exists():
                sys.exit(f"missing datasheet: {p} (pass --datasheets DIR, or --no-datasheets)")
            (root / "datasheets").mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, root / "datasheets" / n)
    z = Path(out) / f"{NAME}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(root.parent).as_posix())
    return root, z


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--datasheets", help="folder holding <part>/<part>.pdf (default: the checkout's untracked models/)")
    ap.add_argument("--no-datasheets", action="store_true", help="leave the five part datasheets out")
    a = ap.parse_args()
    ds = None if a.no_datasheets else (a.datasheets or default_datasheets())
    root, z = build(a.out, ds)
    n = sum(1 for f in root.rglob("*") if f.is_file())
    print(f"{n} files in {root}\n{z} ({z.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
