# Toolchain

Two independent toolchains, with different jobs. They do **not** share
source, and no attempt should be made to unify them.

| Track | Build | Purpose |
|---|---|---|
| A | `arduino-cli` | Reference oracle. Known-good behaviour to compare against |
| B | `arm-none-eabi-gcc` + CMake | The actual project. Bare metal and RTOS |

## Why two

With no debug probe, a working reference implementation is worth a great
deal. When bare-metal ADC code returns garbage, flashing the equivalent
Arduino sketch answers "is this the hardware or my code?" in one step.

Track A also bootstraps Track B (see below), so it is not pure overhead.

---

## Installed on this host *(verified)*

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

## Track A — arduino-cli

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
| Build | `arduino-cli compile` | `cmake --build build` |
| Flash | `arduino-cli upload` | `tools/flash.sh` |

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
