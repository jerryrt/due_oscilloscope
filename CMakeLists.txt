# string(JSON) needs 3.19; the registry in toolchains.json is read with it.
cmake_minimum_required(VERSION 3.19)
project(due_oscilloscope C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# clang-tidy and every other out-of-tree analyser reads the compile
# database, and producing one is a line. Makefile and Ninja generators
# only - it is silently nothing under any other.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMSIS vendor/CMSIS)
set(DEVICE ${CMSIS}/Device/ATMEL/sam3xa)

# ---------------------------------------------------------------------------
# Diagnostics.
#
# NONE OF THESE MAY CHANGE THE GENERATED CODE, and that is a constraint
# rather than a preference. A flag that moved a byte would produce a new
# image, and a new image is a fresh draw of the DAC-phase defect's site
# set and of its severity - so a hygiene pass would arrive as an
# unrecorded experiment. `tools/reproducible.py --compare` is what
# settles it: 0 differing bytes, Track A and Track B, analysed against
# plain.
#
# -Werror IS ON EVERYWHERE AND THE OFF SWITCH IS NOT DECORATION. Three
# benches build this tree with three GCC majors, warning sets differ
# across them, and a warning only one of them emits must not fail
# another bench's build while somebody is mid-diagnosis on something
# unrelated. The container never passes it.
#
#     -DFIRMWARE_WERROR=OFF        stop promoting warnings to errors
#     -DFIRMWARE_ANALYZER=ON       GCC's symbolic execution pass
#     -DFIRMWARE_STACK_USAGE=ON    a .su per object, read by
#                                  tools/stack_frames.py
#
# Directory-wide, so every track gets them. Track A's vendored core
# carries `-w` and is exempt by design; Track A's own code is not, and
# the reason that distinction has to be made by target rather than by
# directory is recorded at the `-w` in cmake/track_a.cmake.
#
# -fanalyzer is gated on COMPILE_LANGUAGE:C, so it sees the C sources
# and never the C++ ones. On Track A that is the shared library and not
# the sketch.
option(FIRMWARE_WERROR      "Treat firmware compiler warnings as errors" ON)
option(FIRMWARE_ANALYZER    "Run GCC's -fanalyzer over the C sources"    OFF)
option(FIRMWARE_STACK_USAGE "Emit per-function stack frame sizes (.su)"  OFF)

# The analyser is a pass somebody asks for, in a build directory of its
# own, and it REPORTS. It is expensive and noisy by design, and one new
# diagnostic that stopped every bench from building would be the fastest
# route to having the whole thing switched off. So -Werror stands down
# where -fanalyzer stands up. Nothing is silenced either way: a finding
# is read, and answered or explained.
set(_fw_werror ${FIRMWARE_WERROR})
if(FIRMWARE_ANALYZER AND _fw_werror)
    set(_fw_werror OFF)
    message(STATUS "diagnostics:   -fanalyzer on, so -Werror is off here")
endif()

# C only. GCC's analyser is a C pass; the Arduino core Track A compiles
# is C++, where it costs time and reports nothing.
add_compile_options(
    -mcpu=cortex-m3 -mthumb
    -ffunction-sections -fdata-sections
    -Wall -Wextra
    $<$<BOOL:${_fw_werror}>:-Werror>
    $<$<AND:$<BOOL:${FIRMWARE_ANALYZER}>,$<COMPILE_LANGUAGE:C>>:-fanalyzer>
    $<$<AND:$<BOOL:${FIRMWARE_STACK_USAGE}>,$<OR:$<COMPILE_LANGUAGE:C>,$<COMPILE_LANGUAGE:CXX>>>:-fstack-usage>
    $<$<CONFIG:Debug>:-Og> $<$<CONFIG:Debug>:-g3>
    $<$<CONFIG:Release>:-Os>
)

# __SAM3X8E__ selects the device through sam.h -> sam3.h -> sam3xa.h.
# Do NOT define DONT_USE_CMSIS_INIT: it suppresses the system_sam3xa.h
# include, which is where SystemInit and SystemCoreClock are declared.
add_compile_definitions(__SAM3X8E__)

# ---------------------------------------------------------------------------
# FW_GIT_REV: which commit an image was built from.
#
# The header is written by cmake/fw_git_rev.cmake, which is a script and
# not an `include()` because it has to run again on every build. A SHA
# resolved at configure time is correct on the day the tree was
# configured and silently wrong every day after, and a stale commit on a
# board is worse than none: measurements get attributed to source that
# did not produce them. The script leaves the file untouched when the
# value has not moved, so restamping costs no recompilation.
#
# All three firmware wrappers run it, between the clean and the build.
# The header lands in the build tree, where .gitignore already keeps it
# out of the working-tree delta it reports.
#
# find_package(Git) rather than PATH: on Windows git is where CMake's
# own FindGit looks and PATH often does not carry it. toolchains.json
# does not list git because nothing else in this project shells out to
# it from CMake.
find_package(Git QUIET)

set(FW_GIT_REV_DIR    "${CMAKE_BINARY_DIR}/generated")
set(FW_GIT_REV_HEADER "${FW_GIT_REV_DIR}/fw_git_rev.h")
set(FW_GIT_REV_COMMAND
    "${CMAKE_COMMAND}"
    "-DREPO_DIR=${CMAKE_SOURCE_DIR}"
    "-DOUT_FILE=${FW_GIT_REV_HEADER}"
    "-DGIT_EXECUTABLE=${GIT_EXECUTABLE}"
    -P "${CMAKE_SOURCE_DIR}/cmake/fw_git_rev.cmake")

# Once here as well, so the header exists for anything that reaches the
# executable target without going through its wrapper - an IDE indexing
# the tree, or a `--target baremetal_bringup` typed by hand.
execute_process(COMMAND ${FW_GIT_REV_COMMAND} COMMAND_ERROR_IS_FATAL ANY)

# lib/due_shared/src is the wire contract both tracks compile.
# Track A reaches the same files by compiling them directly - the
# A_SHARED_C glob in cmake/track_a.cmake (#55). It used to reach them as
# an Arduino library via arduino-cli's --libraries.
# Per target, NOT per directory, and that is load-bearing rather than
# tidiness. `include_directories()` applies to every target defined
# afterwards, including Track A's - and Track A brings its own Arduino
# core, which ships `Stream.h`, `Print.h` and a whole second CMSIS.
#
# On a case-insensitive filesystem - macOS, and Windows - the core's
# `#include "Stream.h"` then resolved to this project's `drivers/stream.h`
# and the build failed with a linkage conflict three headers away from
# the cause (issue #55). The CMSIS pair would have collided the same way
# and had no reason to fail loudly.
#
# Invariant 3 already says the two tracks share no hardware source.
# Scoping the include path to the target is that invariant made
# mechanical: Track A cannot reach `drivers/` or `bsp/` even by
# accident, because they are not on its path at all.
set(TRACK_B_INCLUDES bsp drivers lib/due_shared/src)

# SYSTEM: vendor headers are not ours to fix, and -Wall -Wextra otherwise
# buries real diagnostics under warnings from the CMSIS pack.
set(TRACK_B_SYSTEM_INCLUDES
    ${CMSIS}/Include
    ${CMSIS}/Device/ATMEL          # sam.h -> sam3.h -> sam3xa/include/
    ${DEVICE}/include
)

set(LINKER_SCRIPT ${CMAKE_SOURCE_DIR}/linker/sam3x8e_flash.ld)

add_executable(baremetal_bringup EXCLUDE_FROM_ALL
    apps/baremetal_bringup/main.c
    bsp/startup_sam3x8e.c
    bsp/uart.c
    bsp/led.c
    bsp/systick.c
    lib/due_shared/src/load.c
    bsp/clock.c
    bsp/fault.c
    bsp/syscalls.c
    drivers/dac.c
    drivers/adc.c
    drivers/acq.c
    drivers/gen.c
    drivers/play.c
    drivers/usb_cdc.c
    drivers/clockref.c
    drivers/stream.c
    lib/due_shared/src/ctl.c
    drivers/ctl_port.c
    lib/due_shared/src/console.c
    drivers/console_port.c
    lib/due_shared/src/crc32.c
    lib/due_shared/src/play_report.c
    lib/due_shared/src/console_cmds.c
    lib/due_shared/src/console_out.c
    lib/due_shared/src/stream_core.c
    lib/due_shared/src/stream_bench.c
    ${DEVICE}/source/system_sam3xa.c
)

target_include_directories(baremetal_bringup PRIVATE
    ${TRACK_B_INCLUDES} ${FW_GIT_REV_DIR})
target_include_directories(baremetal_bringup SYSTEM PRIVATE ${TRACK_B_SYSTEM_INCLUDES})

target_link_options(baremetal_bringup PRIVATE
    -mcpu=cortex-m3 -mthumb
    -T${LINKER_SCRIPT}
    -Wl,--gc-sections
    -Wl,-Map=${CMAKE_BINARY_DIR}/baremetal_bringup.map
    -specs=nano.specs
    -nostartfiles
)
set_target_properties(baremetal_bringup PROPERTIES
    SUFFIX ".elf"
    LINK_DEPENDS ${LINKER_SCRIPT}
)

# Every build of this target is a full build, and that is deliberate.
#
# An incremental build here has already shipped a mixed-revision image.
# On 2026-08-29 arduino-cli's cache produced a Track A binary from a new
# ctl_port.cpp and a stale ctl.c: the capability word had the new bit set
# so the opcode worked, while the capability *report* omitted it, because
# that table lived in the file the cache reused. A board that answers
# correctly and describes itself wrongly is worse than one that fails,
# and nothing in the build output said a cached object had been used -
# the only tell was 8 bytes of flash.
#
# CMake's dependency tracking is better than that cache, but the failure
# is not worth the saving: a full build of this target is about 0.6 s on
# the slowest bench, against measurement runs of nine minutes to eight
# hours that quote the resulting image by commit. `firmware_track_a` in
# cmake/track_a.cmake cleans first for the same reason on the other
# track, and tests/test_clean_build.py fails if either is removed.
#
# Delete the object directory rather than depend on the compiler: it is
# the one step that cannot be fooled by a timestamp.
# Every build of the firmware is a full build, and the ordering is
# process sequencing rather than graph planning.
#
# This used to be `add_dependencies(baremetal_bringup
# enforce_clean_build)`, which asks the build system to run a clean
# inside the same graph that is about to link. Make re-evaluates between
# steps and got away with it - measured on linux-x1, 25 of 25 objects
# recompiled on every invocation - but Ninja plans the whole graph first
# and then deletes the objects the same plan is about to link:
#
#     ld: cannot find CMakeFiles/baremetal_bringup.dir/drivers/stream.c.obj
#
# Not a parallelism race; -j 1 fails identically (issue #35). It was my
# mechanism relying on an ordering guarantee CMake does not offer, and it
# had been silently Make-works / Ninja-broken since it landed.
#
# So the clean and the build are two *child* invocations of CMake,
# sequenced by the shell rather than by the generator. `firmware` is what
# `all` builds; `baremetal_bringup` leaves `all` so the inner invocation
# cannot recurse into this target, and naming it explicitly is what makes
# the second command build the firmware rather than the driver.
#
# CMake's own clean target, not `rm -rf` on the object directory: that
# also removes build.make, which the generator needs, and the build then
# fails with "No rule to make target".
add_custom_target(firmware ALL
    COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}" --target clean
    COMMAND ${FW_GIT_REV_COMMAND}
    COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}"
            --target baremetal_bringup --parallel
    COMMENT "Enforcing a clean build (see tests/test_clean_build.py)"
    USES_TERMINAL VERBATIM)

add_custom_command(TARGET baremetal_bringup POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:baremetal_bringup>
            $<TARGET_FILE_DIR:baremetal_bringup>/baremetal_bringup.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:baremetal_bringup>
    COMMENT "Generating .bin and reporting size"
)

# ---------------------------------------------------------------------------
# Track C: the FreeRTOS build (issue #45).
#
# OPT-IN, and that is not timidity. FreeRTOS is fetched at configure
# time by the owner's ruling on decision (3), so a bench that configures
# without this flag never needs a network to build Track B - which is
# every bench, today, on every existing workflow. The ruling also says
# Track C "should build on all platforms given the current setup, when
# Track C is ready": ready is C4, this is C1, and the flag is how those
# two facts live together until then.
#
#     cmake -B build -DCMAKE_TOOLCHAIN_FILE=... -DBUILD_TRACK_C=ON
#
option(BUILD_TRACK_C "Fetch FreeRTOS and build the Track C image" OFF)

# Track A, built here rather than by arduino-cli (issue #55).
#
# Opt-in for the same reason BUILD_TRACK_C is: it needs the Arduino SAM
# core *sources* installed, and a bench without them should not fail to
# configure a Track B build over it. Nothing is fetched and no compiler
# but this project's own is used - see cmake/track_a.cmake, which also
# records what aligning the toolchains costs.
#
#     cmake -B build -DCMAKE_TOOLCHAIN_FILE=... -DBUILD_TRACK_A=ON
option(BUILD_TRACK_A "Build the Track A image from CMake, without arduino-cli" OFF)

if(BUILD_TRACK_A)
    include(cmake/track_a.cmake)
endif()

if(BUILD_TRACK_C)
    include(cmake/freertos.cmake)

    # C2: the same driver set Track B links, plus the application.
    #
    # This is invariant 4's claim made literal - "bare-metal and FreeRTOS
    # builds link identical driver code and differ only in main()". The
    # list below is baremetal_bringup's with exactly two substitutions:
    # apps/rtos_bringup/main.c for apps/baremetal_bringup/main.c, and
    # apps/rtos_bringup/time_rtos.c for bsp/systick.c.
    add_executable(rtos_bringup EXCLUDE_FROM_ALL
        apps/rtos_bringup/main.c
        apps/rtos_bringup/time_rtos.c
        bsp/startup_sam3x8e.c
        bsp/uart.c
        bsp/led.c
        bsp/clock.c
        bsp/fault.c
        bsp/syscalls.c
        lib/due_shared/src/load.c
        drivers/dac.c
        drivers/adc.c
        drivers/acq.c
        drivers/gen.c
        drivers/play.c
        drivers/usb_cdc.c
        drivers/stream.c
        drivers/clockref.c
        lib/due_shared/src/ctl.c
        drivers/ctl_port.c
        lib/due_shared/src/console.c
        drivers/console_port.c
        lib/due_shared/src/crc32.c
        lib/due_shared/src/play_report.c
        lib/due_shared/src/console_cmds.c
        lib/due_shared/src/console_out.c
        lib/due_shared/src/stream_core.c
        lib/due_shared/src/stream_bench.c
        ${DEVICE}/source/system_sam3xa.c
        ${FREERTOS_SOURCES}
    )
    # bsp/systick.c is ABSENT and must stay absent: it defines
    # SysTick_Handler strongly, and FreeRTOSConfig.h routes that name to
    # the kernel's handler. Two strong definitions are a duplicate
    # symbol, not an override. millis() and micros() live there too, so
    # anything Track C links must not need them until the kernel offers
    # an equivalent - see FreeRTOSConfig.h.

    target_include_directories(rtos_bringup PRIVATE
        apps/rtos_bringup ${FREERTOS_INCLUDE})

    # State the track at the build rather than leaving it to whichever
    # track_id.h the include path reaches first. drivers/ctl_port.c is
    # linked by this target and includes "track_id.h" from its own
    # directory, so without this Track C's control channel answers
    # track=b while its console answers track=C - measured, not
    # hypothetical.
    target_compile_definitions(rtos_bringup PRIVATE FW_TRACK='C')

    target_include_directories(rtos_bringup PRIVATE
        ${TRACK_B_INCLUDES} ${FW_GIT_REV_DIR})
    target_include_directories(rtos_bringup SYSTEM PRIVATE ${TRACK_B_SYSTEM_INCLUDES})

    target_link_options(rtos_bringup PRIVATE
        -mcpu=cortex-m3 -mthumb
        -T${LINKER_SCRIPT}
        -Wl,--gc-sections
        -Wl,-Map=${CMAKE_BINARY_DIR}/rtos_bringup.map
        -specs=nano.specs
        -nostartfiles
    )
    set_target_properties(rtos_bringup PROPERTIES
        SUFFIX ".elf"
        LINK_DEPENDS ${LINKER_SCRIPT}
    )

    # The same full-build enforcement as `firmware`, and for the same
    # reason - see the long comment above it. A third build path that
    # skipped it would be exactly the silent drift
    # tests/test_clean_build.py exists to catch, so the shape is copied
    # deliberately rather than the target being left to `all`.
    add_custom_target(firmware_rtos
        COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}" --target clean
        COMMAND ${FW_GIT_REV_COMMAND}
        COMMAND ${CMAKE_COMMAND} --build "${CMAKE_BINARY_DIR}"
                --target rtos_bringup --parallel
        COMMENT "Enforcing a clean build of Track C (tests/test_clean_build.py)"
        USES_TERMINAL VERBATIM)

    add_custom_command(TARGET rtos_bringup POST_BUILD
        COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:rtos_bringup>
                $<TARGET_FILE_DIR:rtos_bringup>/rtos_bringup.bin
        COMMAND ${CMAKE_SIZE} $<TARGET_FILE:rtos_bringup>
        COMMENT "Generating Track C .bin and reporting size"
    )
endif()

# ---------------------------------------------------------------------------
# One build system, two tracks.
#
# CMake is the single entry point, but it does NOT build Track A itself: it
# drives arduino-cli. Invariant 3 - the two toolchains share no source, and
# Track A is a reference oracle only for as long as a different compiler and
# a different USB stack produce it. Consolidating the *interface* is free;
# consolidating the *toolchains* would destroy the thing Track A is for.
#
# Tool locations come from toolchains.json via cmake/hosttools.cmake, so
# platform differences are resolved here rather than inside the scripts.
# ---------------------------------------------------------------------------
include(${CMAKE_CURRENT_LIST_DIR}/cmake/hosttools.cmake)

# Prefer the project venv: tools/flash.py needs pyserial, which is declared
# in requirements-dev.txt and installed there, not in the system interpreter.
# Scripts/ on Windows, bin/ elsewhere - resolved here so no script has to ask.
find_package(Python3 COMPONENTS Interpreter)
set(PY "${Python3_EXECUTABLE}")
foreach(_cand "${CMAKE_SOURCE_DIR}/.venv/Scripts/python.exe"
              "${CMAKE_SOURCE_DIR}/.venv/bin/python")
    if(EXISTS "${_cand}")
        set(PY "${_cand}")
        break()
    endif()
endforeach()
message(STATUS "python:        ${PY}")

hosttools_find(arduino_cli ARDUINO_CLI_DIR ARDUINO_CLI)
hosttools_find(bossac      BOSSAC_DIR      BOSSAC)

add_custom_target(tools
    COMMAND "${PY}" "${CMAKE_SOURCE_DIR}/tools/toolchain.py"
    COMMENT "Host tools resolved from toolchains.json"
    USES_TERMINAL VERBATIM)

# Track A -- the reference oracle. Built here the way Track B and Track C
# are, by cmake/track_a.cmake, under -DBUILD_TRACK_A=ON (#55).
#
# The `track_a` and `flash_track_a` targets that used to live here shelled
# out to tools/sketch.py and arduino-cli, and they were the last live
# callers of it. They are gone rather than re-pointed: `firmware_track_a`
# already builds Track A with a clean-build wrapper, `tools/flash.py`
# already flashes any .bin, and a second target that does the same thing
# by another route is precisely the "third path" tests/test_clean_build.py
# forbids -- the criterion #55 is written against says two ways to build
# Track A must not both exist.
#
# What those targets knew and this must not lose: build.f_cpu MUST match
# the runtime clock, because micros() divides by it and MCK is 78 MHz
# here; and build.ldscript pins the capture ring to SRAM bank 1. Passed
# to arduino-cli they were silent when missing and cost 35-44 ADC
# overruns per 4 s. They are now two lines in cmake/track_a.cmake, under
# version control, where neither can be forgotten.
#
#   cmake -B build-a -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake #         -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON
#   cmake --build build-a --target firmware_track_a
#
# arduino-cli is still resolved above, because bossac and the port
# discovery come from the same install and Track A's *sources* are the
# Arduino core's.

# Track B -- this project. The 1200-baud touch and bossac call live in
# tools/flash.py because pyserial does them identically everywhere; CMake
# supplies the tool path it resolved.
if(BOSSAC)
    message(STATUS "bossac:        ${BOSSAC}")
    add_custom_target(flash
        COMMAND "${PY}" "${CMAKE_SOURCE_DIR}/tools/flash.py"
                --bin  "$<TARGET_FILE_DIR:baremetal_bringup>/baremetal_bringup.bin"
                --bossac "${BOSSAC}"
        COMMENT "Flashing Track B over the programming port"
        USES_TERMINAL VERBATIM)
    # The driver, not the executable: depending on baremetal_bringup
    # directly would build it incrementally and step straight past the
    # clean, which is the hole this whole arrangement exists to close.
    add_dependencies(flash firmware)
else()
    message(STATUS "bossac:        not found -- the flash target is unavailable")
endif()
