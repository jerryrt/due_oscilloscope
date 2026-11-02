import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
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
    # positive control: the shipping image must pass
    assert os.path.exists(STOCK)
    assert check(open(STOCK, "rb").read()) == []
