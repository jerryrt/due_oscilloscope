"""The host's waveform generators. No board, no scope.

Every one of these is a property the *instrument* rests on rather than a
restatement of the code. A ramp whose period is not a whole number of
samples makes `ramp_discontinuities` report a discontinuity once a
cycle; a sine whose buffer is not a whole number of cycles makes the
Feeder's wrap a phase step; a square whose halves differ by one sample
puts a duty error on the screen that reads as the converter's.
"""

import struct

import pytest

import measure


def codes(wave):
    """DAC codes and channel tags, as the DACC will see them."""
    return [(struct.unpack("<H", wave[i:i + 2])[0] & 0xFFF,
             (struct.unpack("<H", wave[i:i + 2])[0] >> 12) & 0x3)
            for i in range(0, len(wave), 2)]


BUILDERS = [
    ("sine", lambda: measure.build_waveform(6250.0, 200000)),
    ("square", lambda: measure.build_square(6250.0, 200000)),
    ("ramp", lambda: measure.build_ramp()),
    ("dc", lambda: measure.build_dc(2048)),
]


@pytest.mark.parametrize("name,build", BUILDERS, ids=[b[0] for b in BUILDERS])
def test_every_sample_is_tagged_for_dac0(name, build):
    """DAC1 was tried and the analog result behaved as though both
    channels reached channel 0 - see build_waveform. Until that is
    understood, a tag other than 0 is a generator bug."""
    wave, _ = build()
    assert wave, f"{name} produced nothing"
    assert len(wave) % 2 == 0, "half-words, so an odd byte count is a bug"
    assert all(tag == 0 for _, tag in codes(wave))


@pytest.mark.parametrize("name,build", BUILDERS, ids=[b[0] for b in BUILDERS])
def test_no_sample_exceeds_the_dacs_twelve_bits(name, build):
    wave, _ = build()
    assert all(0 <= c <= 4095 for c, _ in codes(wave))


def test_the_sine_buffer_holds_whole_cycles():
    """The Feeder wraps this buffer with `pos = (pos + n) % len(wave)`,
    so a partial cycle at the end is a phase step every wrap - which on
    a triggered scope is the trace jumping sideways."""
    wave, tone = measure.build_waveform(6250.0, 200000)
    per_cycle = round(200000 / tone)
    assert len(wave) // 2 % per_cycle == 0


def test_the_square_buffer_holds_whole_cycles():
    wave, tone = measure.build_square(6250.0, 200000)
    per_cycle = round(200000 / tone)
    assert len(wave) // 2 % per_cycle == 0


def test_the_square_has_two_levels_and_they_are_the_rails():
    wave, _ = measure.build_square(6250.0, 200000)
    assert sorted({c for c, _ in codes(wave)}) == [0, 4095]


# The whole AWG ladder, so an odd samples-per-cycle cannot hide at one
# rate. 39 MHz / RC, and the sweep's fixed 32 samples per cycle.
LADDER = [(39_000_000 // rc, (39_000_000 // rc) / 32.0)
          for rc in (195, 98, 65, 44, 39, 32, 28)]


@pytest.mark.parametrize("sps,tone", LADDER, ids=[str(s) for s, _ in LADDER])
def test_the_square_is_fifty_percent_duty(sps, tone):
    """An odd samples-per-cycle would put one extra sample on one half.
    A generator-authored 51% is indistinguishable on a screen from a
    converter-authored one."""
    wave, actual = measure.build_square(tone, sps)
    seq = [c for c, _ in codes(wave)]
    per_cycle = round(sps / actual)
    assert per_cycle % 2 == 0, f"{per_cycle} samples per cycle is odd"
    assert seq.count(4095) == seq.count(0)


def test_the_square_transitions_exactly_twice_per_cycle():
    wave, tone = measure.build_square(6250.0, 200000)
    seq = [c for c, _ in codes(wave)]
    edges = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    cycles = (len(seq) // round(200000 / tone))
    # One edge per half cycle, less the final falling edge that the
    # buffer's end takes with it - the wrap supplies it at playback.
    assert edges == 2 * cycles - 1


def test_the_ramp_period_is_a_whole_number_of_samples():
    wave, _ = measure.build_ramp()
    seq = [c for c, _ in codes(wave)]
    assert len(seq) == 4096 // measure.RAMP_STEP
    steps = {(seq[i] - seq[i - 1]) % 4096 for i in range(1, len(seq))}
    assert steps == {measure.RAMP_STEP}


def test_dc_is_one_level():
    wave, tone = measure.build_dc(2048)
    assert {c for c, _ in codes(wave)} == {2048}
    assert tone == 0.0


@pytest.mark.parametrize("kwargs,expect", [
    ({}, "build_waveform"),
    ({"square": 6250.0}, "build_square"),
    ({"ramp": 8}, "build_ramp"),
    ({"dc": 2048}, "build_dc"),
])
def test_the_selector_reaches_every_builder(kwargs, expect):
    """run_loop and run_play share this chain; they used to each carry a
    copy and the copies drifted."""
    wave, _ = measure.build_selected(200000, **kwargs)
    direct = {
        "build_waveform": lambda: measure.build_waveform(1000.0, 200000),
        "build_square": lambda: measure.build_square(6250.0, 200000),
        "build_ramp": lambda: measure.build_ramp(step=8),
        "build_dc": lambda: measure.build_dc(2048),
    }[expect]()[0]
    assert wave == direct


# ---------------------------------------------------------------------
# The firmware's own generator. Board-free: what is checked here is that
# the host predicts the device's arithmetic, not that the device does
# it - the device's answer is checked on the bench, with an instrument.
# ---------------------------------------------------------------------

def test_the_shape_codes_match_the_firmware_headers():
    """drivers/gen.h and sketches/bringup/gen.h both define these, and a
    host that disagrees with either sends the wrong shape silently."""
    assert measure.GEN_SHAPES == {"sine": 0, "square": 1, "ramp": 2,
                                  "triangle": 3, "dc": 4}
    assert measure.GEN_SHAPE_NAMES[2] == "ramp"


@pytest.mark.parametrize("asked,adopted", [
    (300, 256), (256, 256), (255, 128), (100, 64), (64, 64),
    (65, 64), (3, 2), (2, 2), (1, 2), (0, 2),
])
def test_the_host_rounds_resolution_the_way_the_device_does(asked, adopted):
    """The device rounds down to the nearest legal power of two rather
    than refusing. A host that does not round the same way predicts the
    wrong frequency for every request that is not already a power of
    two - and 300 -> 256 and 100 -> 64 are measured on the board."""
    assert measure.gen_points_for(asked) == adopted


def test_resolution_is_a_frequency_knob():
    """f = trigger / (2 * points): halving the resolution doubles the
    output. Verified on the bench from 256 points down to 2."""
    for pts, hz in ((256, 390.625), (128, 781.25), (64, 1562.5),
                    (16, 6250.0), (4, 25000.0), (2, 50000.0)):
        assert measure.gen_output_hz(200_000, pts) == hz


def test_every_legal_resolution_divides_the_table():
    """A resolution that does not divide the table leaves a partial
    cycle at the PDC wrap, which is a phase step in the analog output
    once per reload."""
    for asked in range(1, 400):
        p = measure.gen_points_for(asked)
        assert measure.GEN_TABLE_POINTS % p == 0
        assert measure.GEN_POINTS_MIN <= p <= measure.GEN_TABLE_POINTS


def test_the_fold_period_follows_the_resolution():
    """The issue-#5 instruments fold at GEN_TABLE_LEN because 256 points
    has been the only resolution. It stops being the right period the
    moment the resolution moves, and that is the trap gen.h names."""
    assert measure.gen_fold_len(256) == measure.GEN_TABLE_LEN
    assert measure.gen_fold_len(128) == 256
    assert measure.gen_fold_len(8) == 16


def test_the_sync_modes_match_the_shared_header():
    """GEN_SYNC_* is in lib/due_shared/src/ctl_wire.h and both tracks
    compile it. The host holds the same numbers, and a host that
    disagreed would set a mode nobody asked for."""
    assert measure.GEN_SYNCS == {"off": 0, "cycle": 1, "wrap": 2}


def test_dac1_is_not_a_measurement_channel():
    """DAC1 carries the bench trigger, not a signal to look at. Every
    DSO tool measures DAC0, and this pins the default so a channel
    argument cannot quietly drift onto the trigger pin."""
    import importlib.util
    import pathlib
    tool = (pathlib.Path(__file__).resolve().parent.parent
            / "tools" / "dso_sweep.py")
    spec = importlib.util.spec_from_file_location("dso_sweep", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.build_parser().get_default("channel") == 1
