"""measure.parse_crash: the `c` line, parsed without a table."""
import measure

LINE = ("# crash: reset=software fault=1 count=2 streak=1 pc=0x20000000 "
        "lr=0x000853ab xpsr=0x80000000 cfsr=0x00020000 hfsr=0x40000000 "
        "mmfar=0xe000ed34 bfar=0xe000ed38 sp=0x2007ff68")


def test_a_full_line_is_read():
    r = measure.parse_crash("noise\n" + LINE + "\n#\n")
    assert r["reset"] == "software" and r["fault"] == 1
    assert r["count"] == 2 and r["streak"] == 1
    assert r["pc"] == 0x20000000 and r["cfsr"] == 0x00020000


def test_a_clean_boot_has_no_fault_fields():
    r = measure.parse_crash("# crash: reset=power-on fault=0 count=0 streak=0\n")
    assert r == {"reset": "power-on", "fault": 0, "count": 0, "streak": 0}


def test_the_last_line_wins():
    old = "# crash: reset=software fault=1 count=1 streak=1 pc=0x1\n"
    new = "# crash: reset=software fault=0 count=1 streak=0\n"
    assert measure.parse_crash(old + new)["fault"] == 0


def test_nothing_to_read_is_none():
    assert measure.parse_crash("# id: track=B fw=0.2.0\n") is None


def test_an_unknown_field_is_kept_not_dropped():
    r = measure.parse_crash("# crash: reset=software fault=1 count=1 wat=zz\n")
    assert r["wat"] == "zz" and r["fault"] == 1
