"""The control parser, fed arbitrary bytes, and the proof that it can fail.

`ctl.c` is the shared firmware that consumes whatever a peer sent: a
byte-at-a-time magic hunt, a fixed header, a length field the sender
chooses, and a dispatch that reads payload bytes per opcode. It reaches
nothing outside `ctl_port.h`, so it mocks whole on a host compiler -
the same property `stream_port.h` gives the framer, and the same shape
`tests/framer/harness.c` uses.

**What is under test is invariant 7**, not only memory safety: "every
main-loop pass has a bounded worst case that does not depend on what a
host chose to send". A parser a malformed frame can walk off the end
of, loop in, or answer twice from one pass is the defect this file
exists to find. `tests/ctl/fuzz_ctl.c` carries four oracles for that,
and each of the four is mutation-tested below rather than trusted - a
fuzz target that cannot fail is worse than none, because the campaign
that finds nothing then reads as a clean parser.

The mutations are mechanical edits to a copy of `ctl.c`, never to the
tree, exactly as `test_framer_close.py` builds its mutant. Each anchor
is asserted to appear once, so a rewording fails here loudly instead of
leaving a mutant silently identical to the original.

**The fast tier gets a second of this and no more.** The board-free
selection is under a five-minute ceiling, and a fuzzing *campaign* has
no natural end - so what runs here is the built-in seed corpus, which
reaches every dispatch arm deterministically, plus a fixed pseudo-random
grind from two fixed seeds. The campaign belongs to
`docker/run-fuzz.sh`, where libFuzzer's coverage feedback and a corpus
that persists between runs actually pay for themselves.
"""

import os
import re
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
TARGET = os.path.join(HERE, "ctl", "fuzz_ctl.c")
CTL_C = os.path.join(SHARED, "ctl.c")

#: How many inputs the grind takes, and from which seeds. Fixed values,
#: because a run whose input set moves cannot be compared with the run
#: before it - and because a failure has to be re-enterable by anyone
#: who reads the failure message.
GRIND_RUNS = 200_000
GRIND_SEEDS = (1, 7)

#: Each mutation: the text to remove or replace in a copy of ctl.c, and
#: what the harness must then say. The oracle each one exercises is
#: named, because a mutation that fires the wrong oracle is a mutation
#: that proved nothing about the one it was written for.
MUTATIONS = {
    "no-length-check": dict(
        oracle="ASan/UBSan over rx_payload",
        find="""	if (h->length > CTL_MAX_PAYLOAD) {
		ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
		          "payload too long");
		rx_skip = h->length;
		rx_state = ST_SKIP;
		return true;
	}
""",
        replace="",
        expect=["out of bounds", "AddressSanitizer"],
    ),
    "reply-crc-not-complemented": dict(
        oracle="the reply oracle",
        find="""	c = frame_crc32_update(c, out + CTL_HDR_BYTES, len);
	h->crc32 = ~c;
""",
        replace="""	c = frame_crc32_update(c, out + CTL_HDR_BYTES, len);
	h->crc32 = c;
""",
        expect=["a reply whose CRC does not check"],
    ),
    "many-frames-per-pass": dict(
        oracle="the bounded-work oracle",
        find="""		if (ctl_feed(rx_buf[rx_buf_at++]))
			return;
""",
        replace="""		(void)ctl_feed(rx_buf[rx_buf_at++]);
""",
        expect=["more than one reply out of one ctl_service() call"],
    ),
    "stops-draining-the-endpoint": dict(
        oracle="the liveness oracle",
        find="""	if (rx_buf_at >= rx_buf_len) {
		rx_buf_len = ctl_port_read(rx_buf, sizeof(rx_buf));
		rx_buf_at = 0;
		if (rx_buf_len == 0)
			return;
	}
""",
        replace="",
        expect=["ctl_service() stopped making progress"],
    ),
}


def _require():
    if hostcc.cc() is None:
        pytest.skip("no host C compiler")


@pytest.fixture(scope="module")
def ctl_src():
    with open(CTL_C) as fh:
        return fh.read()


def _idle_us(src):
    """ctl.c's idle threshold, read out of ctl.c.

    The harness steps its mock clock past this between inputs so the
    parser is abandoned back to idle by the protocol's own rule rather
    than by anything reaching into its statics. Copying the number would
    let the two drift, and a harness whose reset had quietly stopped
    working would carry state from one corpus entry into the next -
    which makes a crash file mean nothing on its own.
    """
    m = re.search(r"^#define\s+CTL_IDLE_US\s+(\d+)u?\s*$", src, re.M)
    assert m, ("CTL_IDLE_US is no longer a plain #define in ctl.c; the "
               "fuzz harness needs its value to return the parser to idle "
               "between inputs")
    return int(m.group(1))


def _build(tmp_path, ctl_c, name, src):
    exe = str(tmp_path / name)
    proc = subprocess.run(
        [hostcc.cc(), "-std=c11", "-Wall", "-Wextra",
         *hostcc.sanitize_flags(),
         f"-DCTL_IDLE_US_PROBE={_idle_us(src)}u",
         "-I", SHARED, "-o", exe,
         TARGET, ctl_c,
         os.path.join(SHARED, "crc32.c"),
         os.path.join(SHARED, "console_out.c")],
        capture_output=True, text=True, env=hostcc.cc_env(), timeout=600)
    assert proc.returncode == 0, f"fuzz target build failed:\n{proc.stderr}"
    return exe


@pytest.fixture(scope="module")
def target(tmp_path_factory, ctl_src):
    _require()
    return _build(tmp_path_factory.mktemp("fuzz"), CTL_C, "fuzz_ctl", ctl_src)


def _run(exe, args, timeout=600):
    return subprocess.run([exe, *args], capture_output=True, text=True,
                          env=hostcc.cc_env(), timeout=timeout)


def test_the_seed_corpus_finds_nothing(target):
    """Every dispatch arm, both capability worlds, and the refusals.

    The seeds are built in the harness from `ctl_wire.h` itself, so a
    new opcode is one line there rather than a binary nobody can read.
    They are the same bytes `--write-seeds` hands libFuzzer, so the fast
    tier and the campaign start from one corpus.
    """
    proc = _run(target, ["--builtin"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 violations" in proc.stdout, proc.stdout


@pytest.mark.parametrize("seed", GRIND_SEEDS)
def test_a_deterministic_grind_finds_nothing(target, seed):
    """Fixed seeds, fixed count - re-enterable from the failure message.

    No coverage feedback, so this is a weaker instrument than the
    campaign and is not offered as a substitute for it. What it is, is
    the arm that runs on every change, on a bench with no clang.
    """
    proc = _run(target, ["--random", str(GRIND_RUNS), str(seed)])
    assert proc.returncode == 0, (
        f"reproduce with: fuzz_ctl --random {GRIND_RUNS} {seed}\n"
        + proc.stdout + proc.stderr)
    assert "0 violations" in proc.stdout, proc.stdout


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_harness_catches_a_parser_broken_on_purpose(tmp_path, ctl_src,
                                                        name):
    """One mutation per oracle, and the seed corpus alone must catch it.

    Not a test of the parser - a test of the fuzz target. The four
    together say what this file's null result is worth: memory safety
    over the payload buffer, a reply that parses back, at most one reply
    out of one pass, and a pass that makes progress.

    The corpus is what runs here rather than the grind, because a
    mutation only the random arm catches would be one the fast tier
    finds by luck.
    """
    _require()
    m = MUTATIONS[name]
    assert ctl_src.count(m["find"]) == 1, (
        f"the {name} anchor is no longer in ctl.c verbatim. If the code "
        f"was reworded, update MUTATIONS; if it was removed, that is the "
        f"regression this file exists to catch.")
    mutant = tmp_path / "ctl_mutant.c"
    mutant.write_text(ctl_src.replace(m["find"], m["replace"], 1))

    exe = _build(tmp_path, str(mutant), "fuzz_mutant", ctl_src)
    proc = _run(exe, ["--builtin"])
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"the {name} mutant passed the seed corpus, so {m['oracle']} has "
        f"no power over it:\n{out}")
    assert any(e in out for e in m["expect"]), (
        f"the {name} mutant failed, but not through {m['oracle']}. "
        f"Expected one of {m['expect']}:\n{out}")
