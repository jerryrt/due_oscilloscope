# Toolchain

Three tracks, one compiler, one build system. `arm-none-eabi-gcc` and
CMake build all of them, and `arduino-cli` is invoked by nothing.

| Track | Target | Purpose |
|---|---|---|
| A | `firmware_track_a` in `build-a` | Reference oracle. Known-good behaviour to compare against |
| B | `firmware` in `build` | The actual project. Bare metal |
| C | `firmware_rtos` in `build-c` | The RTOS variant |

Track A compiles the Arduino core *sources* with this project's own
toolchain; the two build properties that used to be a wrapper's job —
`build.f_cpu` and `build.ldscript` — are lines in `cmake/track_a.cmake`,
so neither can be silently forgotten.

**What the tracks share is the wire contract, and only that.** The
frame and playback-status layouts, the CRC, the control protocol and
its parser, the console surface and the stream framer live in
`lib/due_shared/src` and every build compiles them. Register
programming stays independent per track, which is what makes a
behavioural divergence point at one of them. `main()` is shared by
nothing. Invariant 3 in `CLAUDE.md` is the rule; `docs/shared-source.md`
is the reasoning.

## Why two

With no debug probe, a working reference implementation is worth a great
deal. When bare-metal ADC code returns garbage, flashing the equivalent
Arduino sketch answers "is this the hardware or my code?" in one step.

Track A also bootstraps Track B (see below), so it is not pure overhead.

---

## Where the tools live

Tool locations are a property of the machine, not of the project, so they
are not hardcoded anywhere. `toolchains.json` at the repository root is a
**committed, shared registry** of search patterns per platform, and it is
the single source of truth: `cmake/hosttools.cmake` reads it for the
build, `tools/toolchain.py` reads it for the scripts. Adding a host means
adding a pattern there, not editing CMake.

It follows the same rule as `requirements-dev.txt` - the declaration
travels between team members, the installed bytes do not.

```sh
python3 tools/toolchain.py          # what resolved on this machine
cmake --build build --target tools  # the same, through the build
```

Resolution order for the ARM toolchain, first hit wins:

| | Source | For |
|---|---|---|
| 1 | `-DARM_TOOLCHAIN_DIR=...` | one-off, and what CI passes |
| 2 | `ARM_TOOLCHAIN_DIR` in the environment | per shell |
| 3 | `toolchains.local.json` | per machine, gitignored |
| 4 | `toolchains.json` | the shared registry |

A local entry *prepends* its patterns rather than replacing them, so an
override for one machine cannot quietly break the fallbacks every other
machine relies on. Prefer adding a pattern to the shared file when the
layout is one a teammate could plausibly have; keep the local file for
genuinely odd paths.

Two rules the registry enforces that are easy to lose:

- **A directory that exists is not a toolchain.** The named executable
  must be inside it. A stale install directory outlives its contents and
  would otherwise shadow a working toolchain further down the list.
- **`arduino:sam`'s bundled `arm-none-eabi-gcc` is refused by pattern.**
  It is gcc 4.8.3 from 2014 and it is on disk on any machine with the
  Arduino IDE installed, which is most of them. Track B is not built with
  it, and that is enforced rather than left to search order.

### Platform differences belong to CMake

`cmake/hosttools.cmake` resolves the platform, the home directory and the
executable suffix; the scripts receive absolute paths and never branch on
the OS. `tools/flash.py` has no OS branch at all - pyserial performs the
1200-baud touch identically everywhere - and CMake passes it the `bossac`
it resolved.

---

## Installed on the macOS dev host *(verified)*

| Component | Version | Architecture | Runs on macOS 12.7.6 x86_64 |
|---|---|---|---|
| `arduino-cli` | 1.5.1 | Mach-O x86_64 | yes, at `~/.local/bin/arduino-cli` |
| `arduino:sam` core | 1.6.12 | - | yes |
| `arm-none-eabi-gcc` | 4.8.3-2014q1 | Mach-O x86_64 | yes |
| `bossac` | 1.6.1-arduino | universal i386 + x86_64 | yes, x86_64 slice |
| `arm-none-eabi-gcc` (xPack) | 15.2.1 | Mach-O x86_64 | yes, Track B compiler |
| `cmake` | 4.4.2 | universal | yes, at `~/.local/bin/cmake` |
| `arm-gnu-toolchain` (ARM official) | 14.2.rel1 | Mach-O x86_64 | **no** - `cc1` needs Homebrew zstd |

The age of these binaries is the risk on this host, but inverted from the
usual direction: macOS 12 removed 32-bit support entirely, so an i386-only
tool would not launch. Both checked. `gcc` is x86_64-only and runs;
`bossac` is a universal binary and macOS selects its x86_64 slice.

`~/.local/bin` must be on `PATH`.

End-to-end flash verified: `sketches/blink` compiles (10692 bytes) and
uploads over the programming port. `bossac` reports Atmel SMART device
`0x285e0a60`, writes 47 pages, sets the boot flash flag and resets.

## arduino-cli — the core sources, not a build path

**`arduino-cli` does not build Track A and is invoked by nothing in
this repository.** What it is still installed for is what it *puts on
disk*: the `arduino:sam` core sources that `cmake/track_a.cmake`
compiles, and `bossac`. `toolchains.json` resolves both as
`arduino_sam_core` and `bossac`.

The `compile`/`upload` commands below remain useful for a bring-up
sketch such as `sketches/blink`. They are not how Track A firmware is
built — that is `firmware_track_a` in `build-a`, above.

### Install

`arduino-cli` ships as a standalone binary; no Homebrew needed (none is
installed on this host).

```sh
# official install script, drops a binary into ./bin
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

arduino-cli config init
arduino-cli core update-index
arduino-cli core install arduino:sam
```

### FQBNs

| FQBN | Port |
|---|---|
| `arduino:sam:arduino_due_x_dbg` | **Programming port** — use this |
| `arduino:sam:arduino_due_x` | Native port |

The `_dbg` variant targets the programming port, where the 1200-baud
touch reset works. That is the one to use.

### Build and flash

```sh
arduino-cli compile --fqbn arduino:sam:arduino_due_x_dbg sketches/blink
arduino-cli upload  --fqbn arduino:sam:arduino_due_x_dbg \
                    -p "$(python3 host/ports.py | awk '/control/{print $3}')" \
                    sketches/blink
```

The port path is enumeration-dependent; discover it, never hardcode it.
A stale hardcoded path once aimed the 1200-baud erase at the wrong port
and wiped the flash without writing anything.

### What it installs that Track B reuses

Under `~/Library/Arduino15/packages/arduino/`:

- **SAM3X8E CMSIS pack** — `sam3x8e.h` register definitions,
  `system_sam3xa.c`, startup sources
- **Reference linker script** (`flash.ld`) to adapt
- **`bossac`** — the flash tool, used by both tracks

Copy the CMSIS pack into `vendor/` and **pin it**. Do not reference it in
place; a core update would silently change the register definitions the
firmware is built against.

### Compiler version caveat

The `arduino:sam` core ships **`arm-none-eabi-gcc` 4.8.3**, a 2014-era
release. It is fine for Track A and unsuitable for Track B: no modern
C++, weak optimisation, dated diagnostics.

Track B uses a separately installed modern toolchain. Two compilers
coexisting is normal and intentional.

---

## Track B — arm-none-eabi-gcc + CMake

### Install the ARM toolchain

Use the **xPack** distribution, not ARM's own build. Unpack under
`tools/`; it is gitignored.

```sh
# xpack-arm-none-eabi-gcc-15.2.1-1.1-darwin-x64.tar.gz
tar xzf xpack-arm-none-eabi-gcc-*-darwin-x64.tar.gz -C tools/
xattr -cr tools/xpack-*/
tools/xpack-*/bin/arm-none-eabi-gcc --version
```

#### Why not ARM's official build *(found the hard way)*

ARM's `arm-gnu-toolchain-14.2.rel1-darwin-x86_64` **does not run on a Mac
without Homebrew.** `cc1` is linked against Homebrew's zstd at an
absolute path:

```
dyld[34442]: Library not loaded: '/usr/local/opt/zstd/lib/libzstd.1.dylib'
  Referenced from: .../libexec/gcc/arm-none-eabi/14.2.1/cc1
arm-none-eabi-gcc: internal compiler error: Abort trap: 6
```

The failure is deceptive: `arm-none-eabi-gcc --version` succeeds, because
the *driver* has no such dependency. Only `cc1` dies, and only once you
actually compile something. CMake reports it as "compiler is broken".

The xPack build bundles its dependencies through `@rpath`, including its
own `libzstd.1.dylib`, and is genuinely self-contained. Verify with
`otool -L` on `cc1` if in doubt.

### Install CMake

Not present on this host either. MacPorts is installed and could
supply it, but the toolchain here is kept as self-contained binaries
under `~/.local` so a port upgrade cannot move it. Use Kitware's
universal binary:

```sh
tar xzf cmake-4.4.2-macos-universal.tar.gz
cp -R cmake-*/CMake.app ~/.local/opt/
ln -sf ~/.local/opt/CMake.app/Contents/bin/cmake ~/.local/bin/cmake
```

`make` is already available from the Command Line Tools at
`/usr/bin/make`, so the default Unix Makefiles generator works.

### CMake toolchain file

`cmake/arm-none-eabi-toolchain.cmake`, in outline:

```cmake
set(CMAKE_SYSTEM_NAME       Generic)
set(CMAKE_SYSTEM_PROCESSOR  arm)

# Without this, CMake tries to link a test executable, fails for want of
# _exit, and refuses to configure. Everyone hits this exactly once.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)

add_compile_options(
    -mcpu=cortex-m3 -mthumb
    -ffunction-sections -fdata-sections
    -Wall -Wextra
)
add_link_options(
    -mcpu=cortex-m3 -mthumb
    -Wl,--gc-sections
    -specs=nano.specs
    -Wl,-Map=output.map
)
```

Add `-u _printf_float` only if `%f` is genuinely needed; it pulls in a
large amount of code.

### Configure and build

```sh
cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake
cmake --build build -j
```

### What bare metal requires

Track A supplies none of this; it must exist before any application code:

```
cmake/arm-none-eabi-toolchain.cmake   toolchain definition
vendor/CMSIS/                         pinned from arduino:sam
linker/sam3x8e_flash.ld               512K flash, 96K SRAM in two banks
bsp/startup.c                         vector table, .data/.bss init
bsp/system_init.c                     PLL to 84 MHz MCK, flash wait states
bsp/uart_printf.c                     newlib retarget
bsp/hardfault.c                       fault reporting
bsp/led.c                             heartbeat and blink codes
```

newlib retargeting means implementing `_write()` plus stubs for `_sbrk`,
`_close`, `_fstat`, `_isatty`, `_lseek`, `_read`; the linker complains
otherwise.

---

## Flashing (both tracks)

The Due programming port is erased and reset by opening it at **1200
baud**, which drives the 16U2 to pull ERASE and RESET. `bossac` then
talks to the SAM-BA bootloader.

`tools/flash.sh` wraps this, and **discovers the port itself rather
than accepting a guess** - a stale hardcoded path once aimed the
1200-baud erase at the wrong port and wiped the flash without writing
anything. Use it:

```sh
tools/flash.sh build/baremetal_bringup.bin
```

Under the hood: 1200-baud touch to trigger erase + reset, then
`bossac -U false -e -w -v -b <bin> -R`. `bossac` wants the port name
**without** the `/dev/` prefix, and `-U false` selects the programming
port rather than the native one.

## Track parity

The tracks are kept **feature-equivalent on purpose**. Every capability
that exists in one exists in the other, with the same commands and the
same output format, so that a difference in behaviour is a real finding
rather than an artefact of two different harnesses.

| Feature | Track A | Track B |
|---|---|---|
| Entry point | `sketches/bringup/bringup.ino` | `apps/baremetal_bringup/main.c` |
| UART printf | `Serial` (interrupt + ring buffer) | `bsp/uart.c` (polled) + newlib retarget |
| LED heartbeat | `PIO_SODR`/`PIO_CODR` | `bsp/led.c` |
| HardFault report | `sketches/bringup/fault.cpp` | `bsp/fault.c` |
| Commands | `h` `p` `g` `f` | `h` `p` `g` `f` |
| Build | `cmake --build build-a --target firmware_track_a` | `cmake --build build` |
| Flash | `python3 tools/flash.py --bin build-a/track_a_bringup.bin` | `cmake --build build --target flash` |
| Underneath | `cmake/track_a.cmake` (no arduino-cli) | `tools/flash.sh` |
| Link map | `linker/arduino_due_x_sram1.ld` | `linker/sam3x8e_flash.ld` |

Track A goes through a wrapper rather than `arduino-cli` directly
because it needs two build properties and each one fails silently:
`build.f_cpu=78000000L`, without which `micros()` is wrong by 7.7%, and
`build.ldscript`, without which the capture ring is not in SRAM bank 1.
The second has to be a path relative to the *installed variant
directory*, so the wrapper computes it.

The CMake targets **drive that wrapper** rather than repeating it. One
entry point for both tracks, and still exactly one place that knows
Track A's build properties - duplicating them in `CMakeLists.txt` is how
a Track A that links, runs, and silently costs 35-44 ADC overruns per
4 s gets built.

Track A was implemented and verified on hardware **first**, then Track B
was written against it. With no debug probe, having a known-good
reference for each mechanism is what makes the bare-metal version
debuggable at all.

Note the deliberate asymmetry in the UART: Track A's `Serial` is
interrupt-driven and buffered, while Track B's is polled. Polled output
is slower but works with interrupts disabled and from fault context,
which is precisely when diagnostics matter. Both report identical
measurements because the path is wire-bound either way.

## Repository layout

```
due_oscilloscope/
├── cmake/arm-none-eabi-toolchain.cmake
├── vendor/CMSIS/              pinned from arduino:sam
├── linker/sam3x8e_flash.ld
├── bsp/                       clock, uart printf, hardfault, led, systick
├── drivers/                   adc_pdc, dacc, tc_trigger, usb
├── rtos/FreeRTOS/             submodule
├── apps/
│   ├── baremetal_loopback/    same drivers,
│   └── rtos_loopback/         different main()
├── host/                      Python: deframe, FFT, plot
├── sketches/                  Track A reference sketches
└── tools/flash.sh
```

`drivers/` stays RTOS-agnostic so both applications link the same code.
That is what makes the bare-metal versus RTOS comparison meaningful
rather than two unrelated projects.

## Host tooling

Python with `pyserial`, `numpy`, `scipy`, and **`pyqtgraph`** for live
plotting. Matplotlib cannot sustain interactive redraw rates and should
not be used for the live view.

If the vendor-class USB path is taken later, add `pyusb` (libusb).

---

## Installed on the Windows host *(verified 2026-08-25)*

Everything Track B needs was already present; nothing was downloaded.

| Component | Version | Location |
|---|---|---|
| `arm-none-eabi-gcc` | **14.3.Rel1** (ARM, mingw-w64) | `C:/arm-gnu-toolchain-14.3.rel1-mingw-w64-i686-arm-none-eabi/bin` |
| `cmake` | 3.31.6 | bundled in Visual Studio 2022 Community |
| `ninja` | bundled | same tree |
| `bossac` | 1.6.1-arduino | `%LOCALAPPDATA%/Arduino15/...` |
| `arduino-cli` | bundled in Arduino IDE 2.x | `%LOCALAPPDATA%/Programs/Arduino IDE/resources/...` |
| `arduino:sam` core | 1.6.12 | `%LOCALAPPDATA%/Arduino15` |

All five resolve from `toolchains.json` with no `toolchains.local.json`.

Track B builds clean: GCC 14.3.1, 19/19 objects, no warnings under
`-Wall -Wextra`, 27,868 B text / 116 B data / 73,020 B bss.

**Note on ARM's own build.** The macOS objection to it is a macOS
packaging defect - `cc1` linked against Homebrew's zstd at an absolute
path - and does not apply here. ARM's mingw-w64 build is self-contained
and is what this host uses. The xPack advice stands for macOS only.

```sh
cmake -S . -B build -G Ninja \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release
cmake --build build
cmake --build build --target tools     # what resolved
cmake --build build --target flash     # Track B over the programming port
```

---

## A second code generator on one bench

The project has **two** code generators, not three. ARM GNU 14.3.1 and
Debian 14.2.1 generate the same instructions for this source; xPack
15.2.1 does not. Three installs, two draws.

That matters because the shared-source oracle is a codegen comparison.
Track A against Track B has no oracle power on `lib/due_shared/src` —
it is one source compiled once — so the only thing left that can
disagree about shared source is a second code generator. For a while
that rested on a single bench happening to be on xPack, which is a
single point of failure nobody chose.

**A bench can host both.** The second toolchain is installed
**deliberately outside every `toolchains.json` search pattern** and
selected per build:

```sh
# linux-x1: the default stays Debian 14.2.1 from /usr/bin
cmake -B build-xpack \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release \
      -DARM_TOOLCHAIN_DIR=$HOME/toolchains-optin/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin
```

`windows-desk` uses the same arrangement at `C:/toolchains-optin/`.

**Outside the globs is the whole design.** The Linux patterns include
`{repo}/tools/xpack-arm-none-eabi-gcc-*/bin` and
`/opt/xpack-arm-none-eabi-gcc-*/bin`, both searched ahead of
`/usr/bin`. Unpacking xPack into either would silently make it the
default and **replace** the bench's generator rather than add one — the
opposite of what a second toolchain is for, and it would do it without
a diagnostic. A `toolchains.local.json` entry has the same effect,
since a local entry prepends. Opt-in per build is the only form that
adds a draw without removing one.

### What it buys, measured

Track B at `766c951` on `linux-x1`, one board, one source tree, the
compiler the only variable:

| | mnemonics | instructions |
|---|---|---|
| Debian 14.2.1 (default) | `759d3fc4fd2129b4` | 10,510 |
| xPack 15.2.1 (opt-in) | `ccfad36a8a72516b` | 10,345 |

Shared source only — the oracle question:

```
65 functions shared      46 identical      19 differing
```

The 19: `bench_push_in`, `con_ch`, `con_hex32`, `con_pad`, `con_u32`,
`con_u32w`, `console_cmd_loop`, `console_cmd_rate_sweep`,
`console_cmd_stream`, `console_gen_report`, `ctl_bleed_describe`,
`ctl_error`, `ctl_have`, `dma_seed_payloads`, `frame_crc32_update`,
`gen_updates_per_cycle`, `stream_bench_stop`, `stream_core_service`,
`stream_core_start`.

**So one bench now reproduces what previously took two.** The
cross-bench comparison that established the oracle was 18 of 63 on
shared source; this is 19 of 65 from two toolchains on one machine.

**Control, because a fingerprint claim here was wrong once for exactly
this reason.** The same xPack configuration built in a directory with a
much longer path gives `ccfad36a8a72516b` / 10,345 — identical. Track B
embeds no absolute path, so it is not exposed to what Track C is;
running the control costs one build and is the difference between a
hash and a hash that means something.

**A whole-image hash cannot answer this question** and is not the
number to quote. Invariant 3 requires the per-track code to differ, so
two images differ for reasons that have nothing to do with the code
generator. `tools/image_mnemonics.py --shared-source` is the form that
restricts to `lib/due_shared`.
