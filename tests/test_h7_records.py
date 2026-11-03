import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "targets", "h7tool", "tools")      # the H7 target's tools; its tests live here with the Due's (docs/testing.md)
sys.path.insert(0, TOOLS)
import h7_records as r


def test_a_record_carries_its_provenance_and_the_reasons_for_rejection(tmp_path):
    p = tmp_path / "x" / "awg.jsonl"
    r.record("sine", {"f": 1e4}, {"amp": 0.5}, False, reasons=["halves differ"], tries=3, fw_build=12,
             observer={"channel": 1}, path=str(p))
    r.record("sine", {"f": 1e4}, {"amp": 0.5}, True, path=str(p))
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2                                           # appended, not overwritten
    for k in ("ts", "bench", "commit", "dirty", "kind", "params", "metrics", "valid", "reasons", "tries", "fw_build", "observer"):
        assert k in rows[0]
    assert rows[0]["valid"] is False and rows[0]["reasons"] == ["halves differ"] and rows[0]["tries"] == 3
    assert rows[1]["valid"] is True
