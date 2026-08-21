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
                    -p /dev/cu.usbmodem141301 sketches/blink
```

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

Download the **ARM GNU Toolchain** (14.x) for `darwin-x86_64` from ARM's
developer site and unpack it under `tools/`. It is gitignored.

macOS 12.6 will quarantine the downloaded binaries; clear it or every
invocation is blocked by Gatekeeper:

```sh
xattr -dr com.apple.quarantine tools/arm-gnu-toolchain-*/
```

Verify:

```sh
tools/arm-gnu-toolchain-*/bin/arm-none-eabi-gcc --version
```

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

`tools/flash.sh` wraps this. Exact `bossac` flag set is to be confirmed
at first bring-up rather than guessed; the shape is:

```sh
# 1200-baud touch to trigger erase + reset
# then something along the lines of:
bossac --port=cu.usbmodem141301 -U false -e -w -v -b build/firmware.bin -R
```

Note `bossac` wants the port name **without** the `/dev/` prefix, and
`-U false` selects the programming port rather than the native one.

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
