"""docker/pcb/dsn_canon.py: the same board always gives the same Specctra design file, and so the same routing."""
import importlib.util
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dsn_canon", REPO / "docker" / "pcb" / "dsn_canon.py")
canon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canon)

DSN = '''(pcb /tmp/x/t.dsn
  (parser
    (string_quote ")
    (host_cad "KiCad's Pcbnew")
  )
  (resolution um 10)
  (structure
    (layer F.Cu
      (type signal)
    )
    (layer B.Cu
      (type signal)
    )
  )
  (placement
    (component R_0603
%s
    )
  )
  (library
    (image R_0603
      (pin P 1 -825 0)
    )
  )
  (network
%s
  )
)
'''
PLACES = [f"      (place R{i} {1000 * i} -{500 * i} front 0 (PN R_0603))" for i in range(1, 7)]
NETS = [f"    (net N{i}\n      (pins R{i}-1 R{i + 1}-2 R{i + 2}-1)\n    )" for i in range(6)]


def build(places, nets, path="/tmp/x/t.dsn"):
    return (DSN % ("\n".join(places), "\n".join(nets))).replace("/tmp/x/t.dsn", path)


def shuffled(seed):
    r = random.Random(seed)
    places, nets = PLACES[:], NETS[:]
    r.shuffle(places)
    r.shuffle(nets)
    nets = [re.sub(r"\(pins ([^)]*)\)", lambda m: "(pins " + " ".join(r.sample(m.group(1).split(), 3)) + ")", n) for n in nets]
    return build(places, nets, f"/tmp/{seed}/t.dsn")


def test_any_order_of_places_nets_and_pins_gives_one_text():
    outs = {canon.canonicalise(shuffled(s), "t.dsn") for s in range(12)}
    assert len(outs) == 1
    assert len({shuffled(s) for s in range(12)}) > 1                       # and the inputs really were different


def test_the_canonical_form_is_sorted_and_keeps_everything_else_byte_for_byte():
    out = canon.canonicalise(shuffled(3), "t.dsn")
    refs = re.findall(r"\(place (R\d+)", out)
    assert refs == sorted(refs)
    nets = re.findall(r"\(net (N\d+)", out)
    assert nets == sorted(nets)
    for pins in re.findall(r"\(pins ([^)]*)\)", out):
        assert pins.split() == sorted(pins.split())
    # the parts that are not reordered are identical to the input's
    for part in ("(string_quote \")", '(host_cad "KiCad\'s Pcbnew")', "(layer F.Cu\n      (type signal)\n    )\n    (layer B.Cu",
                 "(pin P 1 -825 0)"):
        assert part in out
    assert out.startswith("(pcb t.dsn\n")


def test_a_dsn_with_nothing_to_sort_is_refused_not_copied_through():
    with pytest.raises(ValueError, match="no network"):
        canon.canonicalise("(pcb a.dsn\n  (placement\n  )\n)\n")
    with pytest.raises(ValueError, match="no placement"):
        canon.canonicalise("(pcb a.dsn\n  (network\n  )\n)\n")


def test_the_cli_writes_the_canonical_file_and_exits_3_on_a_bad_one(tmp_path):
    src, dst = tmp_path / "in.dsn", tmp_path / "out.dsn"
    src.write_text(shuffled(5))
    assert subprocess.run([sys.executable, str(REPO / "docker/pcb/dsn_canon.py"), str(src), str(dst)]).returncode == 0
    assert dst.read_text() == canon.canonicalise(shuffled(5), "in.dsn")
    src.write_text("(pcb a)\n")
    assert subprocess.run([sys.executable, str(REPO / "docker/pcb/dsn_canon.py"), str(src), str(dst)],
                          capture_output=True).returncode == 3


def test_a_quote_inside_a_string_does_not_hide_the_next_net():
    odd = shuffled(1).replace("(net N2", '(net "N 2"').replace("(net N4", "(net N4")
    out = canon.canonicalise(odd, "t.dsn")
    assert out.count("(net ") == 6
