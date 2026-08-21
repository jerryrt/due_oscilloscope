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
