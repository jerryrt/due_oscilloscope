"""networkx is in the image (a pinned, hash-locked wheel) and its planarity test works.

kvm_02's planarity pre-check uses nx.check_planarity; a hand-written planarity test is code this project should
not own. This is not only an import: K5 and K3,3 are the two non-planar graphs, a cycle and a grid are planar,
and the version is the one the lock file names.
"""
import re
from pathlib import Path

import pytest

try:
    import networkx as nx
except ImportError:      # the networkx marker skips every test here with a reason, or fails it under --require-tool=networkx (conftest)
    nx = None

pytestmark = pytest.mark.networkx


def test_planarity_decides_the_textbook_graphs():
    assert nx.check_planarity(nx.complete_graph(5))[0] is False
    assert nx.check_planarity(nx.complete_bipartite_graph(3, 3))[0] is False
    assert nx.check_planarity(nx.cycle_graph(8))[0] is True
    assert nx.check_planarity(nx.grid_2d_graph(4, 4))[0] is True


def test_the_installed_version_is_the_locked_one():
    lock = (Path(__file__).resolve().parents[3] / "docker" / "pcb" / "requirements-lock.txt").read_text()
    want = re.search(r"^networkx==(\S+)", lock, re.M).group(1)
    reqs = (Path(__file__).resolve().parents[3] / "requirements-pcb.txt").read_text()
    assert f"networkx=={want}" in reqs
    assert nx.__version__ == want
