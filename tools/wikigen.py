#!/usr/bin/env python3
"""Build the wiki's gallery pages from the capture's own index.

**The caption and the image come from one record, and that is the whole
point of this file.** The first published gallery was written by hand
alongside the screenshots, and every one of its interesting captions was
wrong in a different way: four shapes that were all one sine, a "clipped"
waveform that the front end had actually refused, a "smeared" spectrum on
a frequency that cannot smear, an XY view captioned as drawing the loop
while A1 sat undriven, and three rate presets that produced one identical
rate. A figure whose words are maintained separately from the measurement
drifts, and it drifts silently, because nobody re-reads a caption.

So `tools/gallery.py` writes `index.json` as it captures - title, why,
bench, the status bar it verified, the Health alarms standing at the
moment of the grab - and this reads it. Editing the prose means editing
the script that took the picture and taking it again.

    .venv-gui/Scripts/python.exe tools/gallery.py --out <shots>
    python3 tools/wikigen.py --shots <shots> --wiki <wiki checkout>
"""
import argparse
import json
import os
import shutil


REPO_URL = "https://github.com/jerryrt/due_oscilloscope"

#: Which shots go on which page, in order. A prefix match on the file
#: name, so the numbering in `gallery.py` is what decides the grouping
#: and there is no second list to keep in step.
PAGES = [
    ("Gallery-Generator", "The generator", ["01-", "02-", "03-", "04-", "05-"],
     "Everything here is DAC0 to A0 over a jumper, which is the only "
     "signal path this front end offers. `docs/frontend.md`'s safety "
     "section is why: nothing on this board is 5 V tolerant and there "
     "is no protection of any kind, so the panel has no external output "
     "and no control that reads as *connect your signal here*."),
    ("Gallery-Analysis", "Analysis views", ["06-", "07-", "08-", "09-"],
     "The same capture, read four ways. Two of these are here to show "
     "an analysis being wrong in a way that looks right, which is the "
     "failure mode a spectrum is most prone to."),
    ("Gallery-Scope", "The scope", ["10-", "11-", "12-"],
     "Rate, timebase and trigger. The rate is the one worth reading "
     "carefully: every rate this hardware has is 39 MHz divided by an "
     "integer, so the number that comes back is rarely the number that "
     "was asked for, and the panel shows the one the frame headers "
     "carry."),
    ("Gallery-Integrity", "Integrity and measurement",
     ["13-", "14-", "15-", "16-"],
     "The panels that exist to tell you whether to believe the trace, "
     "shown healthy and then shown doing their job on a board that has "
     "been stalled on purpose."),
]


def load(shots):
    with open(os.path.join(shots, "index.json"), encoding="utf-8") as f:
        return json.load(f)


def page_body(title, blurb, entries):
    out = [f"# {title}", "", blurb, ""]
    for e in entries:
        out.append(f"## {e['title']}")
        out.append("")
        out.append(f"![{e['title']}](img/{e['file']})")
        out.append("")
        out.append(e["why"])
        out.append("")
        bits = [f"*Captured on `{e['bench']}`, {e['at']}.*"]
        if e.get("status_bar"):
            bits.append(f"Status bar read `{e['status_bar']}`.")
        alarms = e.get("alarms") or {}
        if alarms:
            named = ", ".join(f"{k} {v}" for k, v in sorted(alarms.items()))
            bits.append(f"**Health alarms standing: {named}** - on purpose; "
                        f"see above.")
        else:
            bits.append("Health alarm counters all zero, checked "
                        "immediately before the grab.")
        out.append(" ".join(bits))
        out.append("")
    return "\n".join(out)


def overview(shots, index):
    rows = []
    for slug, title, _prefixes, _blurb in PAGES:
        rows.append(f"| **[{title}]({slug})** | "
                    f"{sum(1 for e in index if _page_of(e) == slug)} images |")
    alarmed = [e for e in index if e.get("alarms")]
    body = f"""# Gallery

{len(index)} screenshots of the front end driving a real Arduino Due,
captured by [`tools/gallery.py`]({REPO_URL}/blob/main/tools/gallery.py)
against a live board and written up by
[`tools/wikigen.py`]({REPO_URL}/blob/main/tools/wikigen.py) from the
index that capture produced.

**There is no fake-device option, deliberately.** The test suite has
board-free tests, because framing, ownership and backpressure are not
properties of the Due. But a gallery is a claim about an *instrument*,
and a picture of a synthetic device making a synthetic sine would be the
most misleading thing this repository could publish. No board, no
gallery.

| | |
|---|---|
{chr(10).join(rows)}

## Every caption here is checked against its own picture

This gallery is regenerated rather than maintained, and that is a
reaction to how badly the first one went. It was written by hand
alongside the screenshots, and every interesting caption was wrong in a
different way: four waveform shapes that were all the same sine, a
"clipped" waveform the front end had actually *refused*, a "smeared"
spectrum taken at a frequency that cannot smear, an XY view described as
drawing the loop while the second channel sat undriven, and three
capture-rate presets that all produced one identical rate.

None of those were careless sentences. Each was a reasonable prediction
of what the instrument would do, written next to a picture of it doing
something else, and none survived being looked at.

So the capture script now verifies before it saves:

- **the status bar names the waveform the device is playing**, not the
  one the panel is displaying - which is what the four-identical-sines
  bug was;
- **the measurement window is measurable**, so a shot is never taken
  across a discontinuity by accident;
- **every Health alarm counter is zero**, rechecked immediately before
  the grab, with the run restarted and retried if not.

A shot that cannot satisfy those fails the build instead of being
published. Three images below are exempt, because they are *supposed* to
be alarming, and each says so in its own caption.

## The pictures that look wrong on purpose

{len(alarmed)} of these show the instrument at or past a limit, and they
are the reason to trust the rest:

- **A generator request that is refused, not clipped.** 3.0 Vpp against
  a DAC that spans 2.193 V. The panel names the limit in red and leaves
  the previous trace alone. A silently clipped sine would have looked
  like a signal.
- **A square at the front end's own ceiling.** The frequency box stops
  at 20 kHz, so the interesting ceilings in
  [`docs/awg.md`]({REPO_URL}/blob/main/docs/awg.md) are not reachable
  from this panel at all. That is a gap in the front end rather than in
  the board, and it is better shown than described.
- **A spectrum with the wrong window**, on a tone that does not fit a
  whole number of cycles into the analysis window.
- **A capture rate whose counters will not come clean**, because above
  200 kHz the stream loses exactly three frames at start - every time,
  and then runs clean for as long as anyone has watched.
- **A board stalled on purpose**, with the counters going red - and,
  next to it, the one picture here of the front end getting something
  *wrong*. With the DAC no longer driven, the measurement panel will
  sometimes report a frequency, a period and a duty cycle computed
  entirely from the bench's own noise, because the guard meant to stop
  it is set below the noise it has to reject. That is issue #43, and it
  is published rather than captured around.

That last one deserves saying plainly. **Overruns are counted and
flagged, never silently spliced**; that is invariant 5, and it is the
reason the Health panel exists. A trace with no way to tell whether it
is continuous is a trace that will eventually be believed when it should
not be. Most instruments simply do not show you this.
"""
    return body


def home(index):
    """The front page, with its one quoted measurement taken from the
    capture rather than typed from memory."""
    hero = next((e for e in index if e["file"].startswith("01-")), None)
    m = (hero or {}).get("measure") or {}
    if m.get("vpp_v") and m.get("freq_hz"):
        shown = (f"*Asked for 1.500 Vpp at 1 kHz. Measured "
                 f"{m['vpp_v']} at {m['freq_hz']}, on `{hero['bench']}`.*")
    else:
        shown = f"*Captured on `{(hero or {}).get('bench', 'a bench')}`.*"
    return f"""# due_oscilloscope

A 12-bit oscilloscope and signal generator on an Arduino Due
(SAM3X8E, Cortex-M3). **The board acquires and generates; the host does
all the DSP and drawing.** There is no on-target FFT, because a
Cortex-M3 has no FPU and pretending otherwise would cost the sample
path.

The instrument closes a loop you can see in one picture - a waveform
built on the host, played out of DAC0, read back on A0, and drawn in the
same window:

[![The closed loop](img/01-loop-sine.png)](img/01-loop-sine.png)

{shown}

## Start here

| | |
|---|---|
| **[Gallery](Gallery)** | {len(index)} screenshots from a live board - including the ones where it refuses, clamps, smears, or gets something wrong |
| **[Generator (AWG)](Gallery-Generator)** | Shapes, and the limits worth meeting deliberately |
| **[Scope](Gallery-Scope)** | Rates, timebases, trigger modes |
| **[Analysis views](Gallery-Analysis)** | Time, spectrum, XY - and one window used wrongly on purpose |
| **[Integrity](Gallery-Integrity)** | The panels that say whether the trace can be believed |

## The short version of the capabilities

- **~907 ksps aggregate**, 12-bit - and that is *one* ADC behind a 16:1
  multiplexer, so channel count **divides** the aggregate rather than
  multiplying it. Twelve channels is ~75 ksps each, not 12 Msps.
- **~1.81 MB/s** of sample data, regardless of channel count. More
  channels cost per-channel rate, not USB bandwidth.
- **Not simultaneous sampling.** Consecutive conversions are ~0.95 us
  apart; the skew is real and is corrected on the host.
- **The DAC is not rail-to-rail** - 578-2771 mV on this board, measured.
  Writing zero does not give ground.
- **Nothing is 5 V tolerant.** No clamps, no series resistors, no
  protection of any kind. Do not connect unknown signals.

## Where the real documentation is

This wiki is a front door, not a reference. Everything authoritative
lives in the repository, versioned with the code it describes:

- [`docs/scope.md`]({REPO_URL}/blob/main/docs/scope.md) - what the project is for
- [`docs/architecture.md`]({REPO_URL}/blob/main/docs/architecture.md) - how the pieces fit
- [`docs/awg.md`]({REPO_URL}/blob/main/docs/awg.md) - the generator, and its four different ceilings
- [`docs/status.md`]({REPO_URL}/blob/main/docs/status.md) - measured figures, each with its bench
- [`docs/daemon-api.md`]({REPO_URL}/blob/main/docs/daemon-api.md) - the wire protocol
- [`CLAUDE.md`]({REPO_URL}/blob/main/CLAUDE.md) - the invariants, and the facts that are easy to get wrong

**Deliberately not duplicated here.** A wiki page restating a reference
drifts from it, and this project has been bitten by exactly that:
`FW_VERSION_STR` once read `0.1.0` while `FW_VERSION_MAJOR/MINOR/PATCH`
read `0.2.0` - identically on both firmware tracks, so one board
answered "which firmware are you" two different ways.

## A note on every number here

A figure carries **its bench and its date**, or it is not quotable.
There is more than one bench, they differ in wiring, and a figure
without its provenance is not comparable with anything.

The gallery pages take that literally: they are generated by
[`tools/wikigen.py`]({REPO_URL}/blob/main/tools/wikigen.py) from the
index that [`tools/gallery.py`]({REPO_URL}/blob/main/tools/gallery.py)
writes while it drives the board, so every caption, bench, timestamp
and counter on them came from the run that took the picture. The
sentence under the image above is filled in the same way - it used to
be hand-typed, and it was wrong by the next capture.
"""


def sidebar(index):
    """Navigation, generated so it cannot drift from the pages.

    The hand-kept one listed the pages in a different order from the one
    they are built in. Harmless, until someone adds a page and updates
    only one of the two lists.
    """
    lines = ["### due_oscilloscope", "", "- [Home](Home)", "",
             "**Gallery**", "- [Overview](Gallery)"]
    for slug, title, prefixes, _blurb in PAGES:
        n = sum(1 for e in index
                if any(e["file"].startswith(p) for p in prefixes))
        if n:
            lines.append(f"- [{title}]({slug}) ({n})")
    lines += ["", "**Reference lives in the repo**"]
    for name in ("docs/scope.md", "docs/architecture.md", "docs/awg.md",
                 "docs/status.md", "docs/daemon-api.md", "CLAUDE.md"):
        lines.append(f"- [{name}]({REPO_URL}/blob/main/{name})")
    return "\n".join(lines) + "\n"


def _page_of(entry):
    for slug, _title, prefixes, _blurb in PAGES:
        if any(entry["file"].startswith(p) for p in prefixes):
            return slug
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--wiki", required=True)
    args = ap.parse_args()

    index = load(args.shots)
    imgdir = os.path.join(args.wiki, "img")
    os.makedirs(imgdir, exist_ok=True)
    for old in os.listdir(imgdir):
        os.remove(os.path.join(imgdir, old))
    for e in index:
        shutil.copy2(os.path.join(args.shots, e["file"]),
                     os.path.join(imgdir, e["file"]))

    written = []
    for slug, title, prefixes, blurb in PAGES:
        entries = [e for e in index
                   if any(e["file"].startswith(p) for p in prefixes)]
        if not entries:
            continue
        path = os.path.join(args.wiki, f"{slug}.md")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(page_body(title, blurb, entries))
        written.append((slug, len(entries)))

    with open(os.path.join(args.wiki, "Gallery.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(overview(args.shots, index))
    with open(os.path.join(args.wiki, "Home.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(home(index))
    with open(os.path.join(args.wiki, "_Sidebar.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(sidebar(index))

    orphans = [e["file"] for e in index if _page_of(e) is None]
    if orphans:
        raise SystemExit(f"no page claims these shots: {orphans}")

    for slug, n in written:
        print(f"  {slug}.md  {n} images")
    print(f"  Gallery.md  overview of {len(index)}")
    print("  Home.md")
    print("  _Sidebar.md")


if __name__ == "__main__":
    main()
