"""Where the vendor and open op-amp models are, and the one derivation of the 3PEAK macro the studies need.

    from simtools import vendor
    vendor.tph2501_ngspice()     # Path of the ngspice-ready TPH2501 macro (derived, hash-checked, cached)
    vendor.tph2502_beh()         # Path of the project's behavioural TPH2502 (models-open, committed)

3PEAK's TPH2501.mdl is fetched by tools/fetch_models.py into models/tph2501/ (untracked, MC-6) and ngspice reads
it only with ` tc1=0.001` removed from its resistors. The derived copy is written under a cache directory that is
never the repository (DUE_MODEL_CACHE, else the system temp directory) and is verified against the sha256 below
before it is returned, so a macro that changed upstream, or a derivation that went wrong, stops the run.
A missing model raises ModelMissing naming the command that fetches it: a study never runs on a stand-in.
"""
import hashlib
import os
import tempfile
from pathlib import Path

AFE = Path(__file__).resolve().parents[1]
TPH2501_SRC = AFE / "models" / "tph2501" / "TPH2501.mdl"
TPH2501_DERIVED_SHA = "256eeb242fe2d960625eb2c8b8d94d71a3e982730a617f01eb8cfcf90322fae1"
TPH2502_BEH = AFE / "models-open" / "tph2502-beh" / "tph2502_beh.lib"
TC1 = " tc1=0.001"


class ModelMissing(RuntimeError):
    pass


def derive_tph2501(text):
    """The macro's text with every ` tc1=0.001` removed (what `sed 's/ tc1=0.001//'` does)."""
    return text.replace(TC1, "")


def tph2501_ngspice(cache=None):
    if not TPH2501_SRC.is_file():
        raise ModelMissing(f"{TPH2501_SRC} is missing: python3 -I hardware/afe-proto/tools/fetch_models.py")
    cache = Path(cache or os.environ.get("DUE_MODEL_CACHE") or Path(tempfile.gettempdir()) / "due-model-cache")
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / "TPH2501_ngspice.mdl"
    data = derive_tph2501(TPH2501_SRC.read_bytes().decode("latin-1")).encode("latin-1")
    got = hashlib.sha256(data).hexdigest()
    if got != TPH2501_DERIVED_SHA:
        raise ModelMissing(f"derived TPH2501 macro has sha256 {got}, expected {TPH2501_DERIVED_SHA}: the fetched file changed")
    if not out.exists() or out.read_bytes() != data:
        tmp = out.with_name(f"{out.name}.{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, out)              # atomic: another process may be deriving the same file
    return out


def tph2502_beh():
    if not TPH2502_BEH.is_file():
        raise ModelMissing(f"{TPH2502_BEH} is missing (models-open/tph2502-beh is committed)")
    return TPH2502_BEH


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
