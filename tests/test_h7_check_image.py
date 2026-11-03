import struct, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "targets", "h7tool", "tools")      # the H7 target's tools; its tests live here with the Due's (docs/testing.md)
sys.path.insert(0, TOOLS)
from check_image import check

def img(sp=0x20020000, v=(0x08020371, 0x08020373, 0x08020375, 0x08020377, 0x08020379), n=4096):
    return struct.pack("<6I", sp, *v) + bytes(n - 24)

STOCK = os.path.expanduser("~/MCU.Projects/h7tool_backup/stock_release_files/h7_tool_app(V2.33).bin")

def test_good():            assert check(img()) == []
def test_bad_sp():          assert check(img(sp=0x10000000))
def test_vector_in_ram():   assert check(img(v=(0x20000371,) + (0x08020373,) * 4))
def test_vector_in_boot():  assert check(img(v=(0x08000371,) + (0x08020373,) * 4))
def test_no_thumb():        assert check(img(v=(0x08020370,) + (0x08020373,) * 4))
def test_oversize():        assert check(img(n=1_310_721))
def test_short():           assert check(b"\0" * 8)
def test_axi_sp_ok():       assert check(img(sp=0x24080000)) == []
def test_stock_accepted():
    # positive control: the shipping image must pass. The vendor file is not in the repository: without it this SKIPS, which is not a pass.
    import pytest
    if not os.path.exists(STOCK):
        pytest.skip(f"the vendor image is not on this machine ({STOCK}): the positive control did not run")
    assert check(open(STOCK, "rb").read()) == []
