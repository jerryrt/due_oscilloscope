# Track A built the way Track B is: CMake and the xPack toolchain.
#
# Issue #55. Track A was built by `arduino-cli`, which bundles
# **GCC 4.8.3 (2014q1)**, while Track B is on **xPack GCC 15.2.1**.
# Read out of the two images before this file existed:
#
#     build/track_a/bringup.ino.elf   GCC: (GNU Tools for ARM ...) 4.8.3
#     build/baremetal_bringup.elf     GCC: (xPack GNU Arm ...) 15.2.1
#
# Eleven years apart, on a track CLAUDE.md requires to be "comparable in
# design, feature set and performance" and whose gaps are "debt with a
# date on it, never a property of the track".
#
# It also removes a class of silent error the invariant already warns
# about. Under arduino-cli, Track A must be given
# `--build-property build.f_cpu=78000000L` or `micros()` is silently
# wrong, and `--build-property build.ldscript=...` computed against the
# *installed variant directory* or the capture ring is not in SRAM bank
# 1. Both are silent when missing. Here they are two lines in a file
# under version control.
#
# WHAT THIS COSTS, recorded because it is a real loss and not free.
# On issue #54 the compiler gap was measured to be a form of
# independence in its own right: two code generators eleven years apart
# compiling the same lib/due_shared source are two implementations of
# its behaviour, and a shared-source bug that only manifests under one -
# UB that 4.8.3 leaves alone and 15.2.1 exploits - is caught by A-vs-B
# and cannot be caught by B-vs-C. **Aligning the toolchains destroys
# that axis.** It was an accident of arduino-cli rather than a designed
# property, and holding a track on a 2014 compiler to keep it is a bad
# trade against eleven years of diagnostics - but if codegen diversity
# is wanted it now has to be deliberate (a periodic second-compiler or
# second-`-O` build), not a side effect of one track being stale.
#
# NOTHING 4.8.3 PRODUCED SURVIVES. The stock Arduino build links a
# prebuilt `libsam_sam3x8e_gcc_rel.a` - `platform.txt`'s link recipe
# names it as `{build.variant_system_lib}` - and that archive carries
# `startup_sam3xa.o`, `system_sam3xa.o`, `pio.o`, `pmc.o` and the rest,
# all compiled in 2014. Linking it would have left most of the image on
# the old compiler while claiming to have retired it. So libsam is
# compiled from source here, all 27 files, plus `startup_sam3xa.c` for
# `Reset_Handler` and `system_sam3xa.c` for `SystemInit`, and the
# prebuilt archive is not linked at all.

# WHERE THE CORE LIVES IS A PROPERTY OF THE MACHINE, NOT OF THE PROJECT.
#
# This defaulted to `$ENV{HOME}/Library/Arduino15/...` - macOS's arduino-cli
# data directory and nobody else's - hardcoded on the one file whose purpose
# is to stop Track A's build depending on how a machine happens to be set up.
# Found independently on `linux-x1` and on `windows-desk` within the hour,
# both while answering #55's question "can your bench build this target".
#
# The failure mode is worse than a missing dependency because it reads as
# one: the message says to install the core, and installing it does not
# help. On windows-desk configure died having looked in
# `C:/Users/<user>/Library/Arduino15/...`, which Windows never creates,
# while the core sat installed under `AppData/Local` the whole time.
#
# RESOLVED TO THE REGISTRY rather than to a candidate list in CMake, which
# is what `hosttools.cmake` exists for and says in its own header: "where
# each host keeps its build tools... adding a host means adding a search
# pattern there, not editing CMake". `toolchains.json` already carried the
# per-platform Arduino15 root for `bossac`, so the fact was in the repo and
# this file was not asking for it - and `tools/toolchain.py` reads the same
# file, so the build and the tooling around it cannot disagree about where
# the core is. `python3 tools/toolchain.py` now lists it alongside the rest.
#
# THE VERSION STAYS PINNED at 1.6.12 - linux-x1's point, and it is right.
# The registry pattern names the version rather than globbing `sam/*`: a
# bench that silently built against a different core is the mixed-revision
# hazard the clean-build rule exists for, and cross-bench figures are only
# comparable if the vendored source is the same. A bench on another version
# adds a pattern to the registry, or a `toolchains.local.json`, which is the
# documented escape hatch and leaves a trace where a glob would not.
#
# Order, as for the ARM toolchain: -D wins, then the shared registry, then
# a failure that names what it looked for.
include("${CMAKE_CURRENT_LIST_DIR}/hosttools.cmake")

if(NOT ARDUINO_SAM_CORE)
    hosttools_find(arduino_sam_core ARDUINO_SAM_CORE)
endif()

set(ARDUINO_SAM_CORE "${ARDUINO_SAM_CORE}"
    CACHE PATH "Installed Arduino SAM core (arduino:sam), the vendored source Track A builds from")

if(NOT ARDUINO_SAM_CORE OR NOT EXISTS "${ARDUINO_SAM_CORE}/cores/arduino/Arduino.h")
    hosttools_platform(_plat)
    message(FATAL_ERROR
        "Arduino SAM core 1.6.12 not found for host '${_plat}' "
        "(tried '${ARDUINO_SAM_CORE}', then every arduino_sam_core pattern "
        "in toolchains.json).
"
        "Install it (arduino-cli core install arduino:sam), add a pattern "
        "there, create toolchains.local.json, or pass "
        "-DARDUINO_SAM_CORE=/path/to/hardware/sam/1.6.12.
"
        "Run  python3 tools/toolchain.py  to see what resolved. Only the "
        "*sources* are used - no arduino-cli invocation and no bundled "
        "compiler.")
endif()

message(STATUS "Arduino SAM core: ${ARDUINO_SAM_CORE}")

enable_language(CXX)

set(A_CORE   ${ARDUINO_SAM_CORE}/cores/arduino)
set(A_VARIANT ${ARDUINO_SAM_CORE}/variants/arduino_due_x)
set(A_LIBSAM ${ARDUINO_SAM_CORE}/system/libsam)
set(A_CMSIS  ${ARDUINO_SAM_CORE}/system/CMSIS)
set(A_DEVICE ${A_CMSIS}/Device/ATMEL/sam3xa)

file(GLOB A_LIBSAM_SRC   ${A_LIBSAM}/source/*.c)
file(GLOB A_CORE_C       ${A_CORE}/*.c)
file(GLOB A_CORE_CXX     ${A_CORE}/*.cpp)
file(GLOB A_CORE_USB_CXX ${A_CORE}/USB/*.cpp)
file(GLOB A_VARIANT_CXX  ${A_VARIANT}/*.cpp)

# The source list is what arduino-cli actually produced, enumerated
# object by object out of its build tree, rather than a glob that looked
# reasonable. It is **30 objects**, and two of them a `*.c`/`*.cpp` glob
# over `cores/arduino/` does not reach: `wiring_pulse_asm.S`, and
# `avr/dtostrf.c` in a subdirectory. `USB/` is a subdirectory too and
# holds three more - CDC, PluggableUSB, USBCore - which the sketch needs
# for `SerialUSB`, `USBDevice` and `PluggableUSB_::plug()`.
#
# Worth recording because it cost a wrong turn: `ls build/track_a/core/`
# lists 26 objects and none from USB/, so it reads as though arduino-cli
# does not compile them. It does - they are one directory down. The
# `find` is the honest command here and the `ls` is not.
file(GLOB A_SKETCH_CXX   ${CMAKE_SOURCE_DIR}/sketches/bringup/*.cpp)
file(GLOB A_SHARED_C     ${CMAKE_SOURCE_DIR}/lib/due_shared/src/*.c)

# `bringup.ino` is a sketch, and two things arduino-cli did for it have
# to be done here instead: it prepends `#include <Arduino.h>`, and it
# generates forward declarations so a function may be called above its
# definition. Only two symbols in 2320 lines actually need the second -
# measured, not assumed - so a generated header is cheaper than
# reimplementing arduino-cli's parser.
#
# Generated into the build tree rather than written into
# sketches/bringup/, so the sketch directory is byte-identical to what
# arduino-cli still compiles. That is what lets the two build paths be
# compared while #55 is being verified; it can be simplified once the
# arduino-cli path is retired.
set(A_INO_PROTO ${CMAKE_BINARY_DIR}/track_a_ino_prototypes.h)
file(WRITE ${A_INO_PROTO}
"/* Generated by cmake/track_a.cmake - see the comment there. */\n"
"#pragma once\n"
"#include <stdint.h>\n"
"static inline void usbtrace_sample(uint32_t pass);\n"
"static inline void devept_restore(void);\n")

set(A_INO ${CMAKE_SOURCE_DIR}/sketches/bringup/bringup.ino)
# `-x c++` as well as LANGUAGE CXX, and they do different jobs: the
# property tells CMake which compiler to invoke, and the flag tells that
# compiler what a `.ino` file is. Without the flag g++ does not
# recognise the extension, decides the file must be a linker input, and
# the build fails at link time with a missing .obj rather than at
# compile time with anything informative.
set_source_files_properties(${A_INO} PROPERTIES
    LANGUAGE CXX
    COMPILE_OPTIONS "-x;c++;-include;Arduino.h;-include;${A_INO_PROTO}")

# The vendored core is a library of its own, and that is structural
# rather than cosmetic - it is how arduino-cli builds it too, as
# `core.a`.
#
# The core must be compiled WITHOUT the sketch or shared directories on
# its include path. `sketches/bringup/stream.h` and the core's
# `Stream.h` differ only in case, and macOS and Windows filesystems do
# not: with the sketch directory on the path, the core's own
# `#include "Stream.h"` inside USBAPI.h resolves to the sketch's header
# and `class Serial_ : public Stream` fails to parse, three files from
# the cause.
#
# A single target cannot express that, because include directories in
# CMake are per target. Two targets can, and the split is the same one
# Arduino makes. It also means a future header added to
# sketches/bringup/ can never shadow a core header by accident.
set(A_CORE_INCLUDES
    ${A_LIBSAM} ${A_LIBSAM}/include
    ${A_CMSIS}/CMSIS/Include ${A_CMSIS}/Device/ATMEL ${A_DEVICE}/include
    ${A_CORE} ${A_VARIANT})

add_library(track_a_core STATIC EXCLUDE_FROM_ALL
    ${A_LIBSAM_SRC}
    ${A_DEVICE}/source/gcc/startup_sam3xa.c   # Reset_Handler
    ${A_DEVICE}/source/system_sam3xa.c        # SystemInit
    ${A_CORE_C} ${A_CORE_CXX} ${A_CORE_USB_CXX}
    ${A_CORE}/wiring_pulse_asm.S
    ${A_CORE}/avr/dtostrf.c
    ${A_VARIANT_CXX})
target_include_directories(track_a_core SYSTEM PUBLIC ${A_CORE_INCLUDES})

add_executable(track_a_bringup EXCLUDE_FROM_ALL
    ${A_SHARED_C}
    ${A_SKETCH_CXX}
    ${A_INO})

# PRIVATE, and after the core's: the sketch may shadow nothing of the
# core's, but the core is entitled to be found first.
target_include_directories(track_a_bringup PRIVATE
    ${CMAKE_SOURCE_DIR}/lib/due_shared/src
    ${CMAKE_SOURCE_DIR}/sketches/bringup
    ${FW_GIT_REV_DIR})
target_link_libraries(track_a_bringup PRIVATE track_a_core)

# Exactly what boards.txt and platform.txt hand the compiler for
# `arduino:sam:arduino_due_x_dbg`, with one deliberate substitution:
# **F_CPU is 78000000L, not the stock 84000000L.** That substitution was
# a `--build-property` that had to be remembered on every invocation and
# is silently wrong when forgotten - `micros()` divides by it. See
# CLAUDE.md, "MCK is 78 MHz here, not 84".
foreach(t track_a_core track_a_bringup)
target_compile_definitions(${t} PRIVATE
    F_CPU=78000000L
    __SAM3X8E__
    ARDUINO=10819
    ARDUINO_SAM_DUE
    ARDUINO_ARCH_SAM
    # `build.vid`/`build.pid`, NOT `vid.0`/`pid.0`. boards.txt carries
    # both and they mean different things: `pid.0` is how the IDE
    # *identifies a board it finds*, and for `arduino_due_x_dbg` that is
    # 0x003d, the programming port. `build.pid` is what the firmware
    # *reports as its own native device*, 0x003e - the same PID Track B
    # answers with.
    #
    # Getting this wrong is quiet and expensive. The image built, booted,
    # printed a correct identity line and enumerated - as the programming
    # port. `ports.find_all_ports()` then returned (control, None, None),
    # `flash.py` refused with "more than one programming port", and 12 of
    # 21 board tests failed with "native port did not open ... nodes
    # seen: none" while `ls /dev/cu.*` plainly showed two native nodes.
    # Nothing pointed at a USB descriptor.
    USB_VID=0x2341
    USB_PID=0x003e
    USBCON
    "USB_MANUFACTURER=\"Arduino LLC\""
    "USB_PRODUCT=\"Arduino Due\"")
endforeach()

# The vendored core is 2014 C and C++ and does not compile as C23, which
# is GCC 15's default: `libsam` does `typedef unsigned char bool;` and
# `bool` has been a keyword since C23. Pinning the standard the source
# was written for is the honest fix - it is a statement about the
# vendored code, not a workaround - and it is scoped to this target, so
# Track B keeps the project default.
# These are `platform.txt`'s `compiler.c.flags` and `compiler.cpp.flags`
# verbatim, and matching them exactly is not superstition - it was
# measured. A first cut that merely looked equivalent (`-Os
# -ffunction-sections -fdata-sections` plus `--specs=nano.specs`) built
# and booted with a correct identity line and then failed 12 of 21 board
# tests, against 21 of 21 for the arduino-cli image from the same
# sources on the same board minutes apart.
#
# The ones that are easy to leave out and should not be:
#   -nostdlib                      the core provides its own syscalls
#                                  (syscalls_sam3.c); the stock link
#                                  does NOT use --specs=nano.specs, and
#                                  mixing a default-specs compile with a
#                                  nano-specs link is two C libraries
#   -Dprintf=iprintf               the core maps printf to the
#                                  integer-only variant, which changes
#                                  what the sketch's own printf costs
#   --param max-inline-insns-single=500
#   -fno-threadsafe-statics        C++ only
foreach(t track_a_core track_a_bringup)
target_compile_options(${t} PRIVATE
    $<$<COMPILE_LANGUAGE:C>:-std=gnu11>
    $<$<COMPILE_LANGUAGE:CXX>:-std=gnu++11;-fno-rtti;-fno-exceptions;-fno-threadsafe-statics>
    -mcpu=cortex-m3 -mthumb -g -Os -ffunction-sections -fdata-sections
    -nostdlib -Dprintf=iprintf --param max-inline-insns-single=500
    # The vendored core is not warning-clean under a modern compiler and
    # is not ours to fix.
    #
    # `-w` REACHES THE SKETCH TOO, and it is the whole of Track A's own
    # code. Both targets are in this loop, so the sketch and the
    # lib/due_shared sources it compiles are unchecked as well - and
    # `-w` is not positional, so appending `-Wall -Wextra` after it
    # re-enables nothing. It disarms `-Werror`, and every diagnostic
    # any analyser reports as a warning, on this track with it.
    #
    # What that hides today is 11 `-Wunused-variable` in
    # sketches/bringup/bringup.ino, measured on GCC 14.2.1. Splitting
    # the loop so only track_a_core is silenced is the fix, and it needs
    # those eleven gone first or Track A stops building under the
    # project default of -Werror.
    -w)
endforeach()

# The capture ring lives in SRAM bank 1, and the stock flash.ld declares
# `ram` as all 96 KB - bank 0 and bank 1 - so `.bss` grows straight into
# anything pinned there with no diagnostic. This script shrinks `ram` to
# bank 0 and moves the stack with it. Under arduino-cli this was a
# build property whose path had to be computed relative to the installed
# variant directory; here it is a path in this repository.
set(A_LINKER_SCRIPT ${CMAKE_SOURCE_DIR}/linker/arduino_due_x_sram1.ld)
# platform.txt's `recipe.c.combine.pattern`, minus the prebuilt
# libsam archive which is compiled from source here instead.
# NOT --specs=nano.specs: the stock link does not use it, and the
# sources are compiled -nostdlib expecting the core's own syscalls.
target_link_options(track_a_bringup PRIVATE
    -mcpu=cortex-m3 -mthumb -Os
    -T${A_LINKER_SCRIPT}
    -Wl,-Map=${CMAKE_BINARY_DIR}/track_a_bringup.map
    -Wl,--cref -Wl,--check-sections -Wl,--gc-sections
    -Wl,--entry=Reset_Handler
    -Wl,--unresolved-symbols=report-all
    -Wl,--warn-common
    -Wl,--warn-section-align)
target_link_libraries(track_a_bringup PRIVATE m gcc)
set_target_properties(track_a_bringup PROPERTIES
    LINK_DEPENDS ${A_LINKER_SCRIPT}
    SUFFIX ".elf")

add_custom_command(TARGET track_a_bringup POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:track_a_bringup>
            $<TARGET_FILE_DIR:track_a_bringup>/track_a_bringup.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:track_a_bringup>
    COMMENT "Generating .bin and reporting size")

# Every build of the firmware is a full build, and Track A is firmware.
#
# The same shape as `firmware` for Track B and `firmware_rtos` for Track
# C, and for the same reason spelled out at length in CMakeLists.txt: the
# clean and the build are two *child* invocations of CMake, sequenced by
# the shell rather than by the generator, because Ninja plans the whole
# graph first and would delete the objects the same plan is about to
# link. `add_dependencies(track_a_bringup <a clean target>)` is the
# version of this that works under Make and fails under Ninja, which is
# how it stayed broken unnoticed once before (issue #35).
#
# Not ALL: Track A is opt-in behind BUILD_TRACK_A, and a bench that asked
# for it by configuring should still get it by asking for it by name,
# the way Track C does. `track_a_bringup` stays EXCLUDE_FROM_ALL so this
# target's inner invocation cannot recurse into the wrapper.
#
# This was missing from the first cut of this file. The image it
# produced was correct - the tree was configured fresh each time while
# it was being developed - but an incremental build of it would not have
# been clean, and "it happened to be fresh" is exactly the reasoning the
# rule exists to remove.
add_custom_target(firmware_track_a
    COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}" --target clean
    COMMAND ${FW_GIT_REV_COMMAND}
    COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}"
            --target track_a_bringup --parallel
    COMMENT "Enforcing a clean build of Track A (see tests/test_clean_build.py)"
    VERBATIM)
