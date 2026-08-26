# Contributing

## Commit conventions

This repository follows **Linux kernel** commit style.

### Format

```
subsystem: imperative summary, no trailing period

Body wrapped hard at 72 columns. Explain what the change does and,
more importantly, why it is needed. Describe the problem the change
solves and the reasoning behind the approach taken.

Written in the imperative mood, as an instruction to the codebase:
"add", "fix", "move", "remove" - never "added", "fixes", "moving".

Separate paragraphs with blank lines. Prose, not bullet lists, unless
enumerating genuinely discrete items.

Signed-off-by: Name <email>
```

### Subject line

- Prefix with the subsystem, then `: `, then the summary.
- **Imperative mood**: `adc: add PDC ping-pong` not `adc: added ...`.
- Lower case after the prefix; no trailing period.
- Aim for 50 characters, hard limit 72.
- It must describe the change, not the file touched.

### Body

- Wrapped at **72 columns**. Not 80, not unwrapped.
- Explains **why**, not how. The diff already shows how.
- If the change is not obvious in six months, the body has failed.
- Reference measured figures rather than assumptions. If a number is
  unverified, say so.

### Subsystem prefixes

| Prefix | Area |
|---|---|
| `doc` | Documentation under `docs/`, `README.md` |
| `build` | CMake, toolchain files, `.gitignore` |
| `bsp` | Clock, startup, linker script, UART, LED, fault handling |
| `adc` | ADC and its PDC path |
| `dac` | DACC and its PDC path |
| `tc` | Timer Counter, triggering |
| `usb` | UOTGHS, endpoints, DMA descriptors, framing |
| `rtos` | FreeRTOS integration, port configuration |
| `host` | Host-side Python tooling |
| `sketch` | Track A reference sketches |
| `tools` | Flash scripts, helper utilities |

Use a compound prefix when a change genuinely spans two, e.g.
`adc, dac:`. Prefer splitting the commit instead.

### Trailers

`Signed-off-by:` is required, asserting the Developer Certificate of
Origin — that you wrote the change or have the right to submit it.

Other kernel trailers apply where relevant:

```
Fixes: <12-char sha> ("subject of the broken commit")
Reported-by: Name <email>
Tested-by: Name <email>
Reviewed-by: Name <email>
Co-Authored-By: Name <email>
```

### Examples

Good:

```
adc: enable channel tagging in LCDR

Set ADC_EMR.TAG so the channel index appears in ADC_LCDR[15:12]. The
PDC already transfers sixteen bits per conversion, so the tag costs
no additional bandwidth.

Tagging makes the sample stream self-describing. The host can then
demultiplex on the tag rather than trusting position, and can
resynchronise mid-stream after a glitch instead of discarding the
remainder of the capture.

Signed-off-by: Jerry Tian <jerryrt@gmail.com>
```

Bad, with reasons:

```
Updated adc.c                  no prefix, past tense, names a file
fix bug                        says nothing
adc: fixes the overrun issue.  wrong mood, trailing period, vague
```

### Granularity

One logical change per commit. A commit that adds a driver and fixes an
unrelated typo is two commits.

Every commit should build. Bisect is worth protecting.

## Branches

**`main` is the branch.** It is what is built, what is tested, what is
released and what every session starts from. Nothing else is a place
where work lives.

**Every other branch is short-lived: used and discarded.** Personal
branches, feature branches, bug-fix branches - all of them exist to
carry one change from its first commit to `main` and are deleted the
moment they land. A branch is a way of moving a change, not a place to
keep one.

**Concretely:**

- Branch from current `main`, not from another branch.
- Keep it to one change, the same way a commit is one logical change.
- Merge or rebase onto `main` and **delete the branch**, locally and on
  the remote, in the same breath. A merged branch left behind is
  noise that the next person has to evaluate.
- If a branch cannot land within a few days, that is a signal the change
  is too big, not a reason to keep the branch. Split it and land the
  parts that are ready.
- Leave the working tree on `main` when you stop. A checkout parked on a
  feature branch is how unrelated commits end up on the wrong one.

**Why this is a rule here and not a preference.** A long-lived branch on
this project rots in a way that is specific and expensive: the binary
selects which state issue #5 draws, so a branch that has drifted from
`main` is running different firmware *and* a different draw of an open
defect, and any measurement taken on it compares two things at once.
Instruments drift too - `wip/track-a-control-channel` sat long enough
that its recorded "160 passed / 88 failed" was taken with a
`measure.py` that no longer exists, so the number meant nothing by the
time anyone read it. Neither problem is visible from inside the branch.

**The one long-lived exception, and it is being retired.**
`wip/track-a-control-channel` predates this rule. It is not to be
treated as precedent: it either lands or is deleted, and until it does,
it is merged *from* `main` rather than left to drift. Anything learned
on it that is not the change itself - a diagnosis, a measurement, a
landmine in the vendor core - belongs on `main` in `docs/`, where it
survives the branch being thrown away.


## Code conventions

To be established with the first firmware commit. Provisionally:

- C11, `-Wall -Wextra`, warnings treated as errors in CI
- Kernel-style naming: `lower_snake_case` for functions and variables,
  `UPPER_SNAKE` for macros
- Register access through CMSIS definitions, never magic numbers
- Every ISR documents its priority and its constraints, particularly
  whether it may call RTOS primitives

## Documentation

Documentation changes accompany the code they describe, in the same
commit where practical.

Mark unverified figures explicitly. A number that was guessed and later
read as fact is worse than no number, and this project has several
figures that remain unmeasured — see the open questions in
`docs/scope.md`.
