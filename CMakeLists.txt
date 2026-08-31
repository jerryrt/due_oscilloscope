# string(JSON) needs 3.19; the registry in toolchains.json is read with it.
cmake_minimum_required(VERSION 3.19)
project(due_oscilloscope C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(CMSIS vendor/CMSIS)
set(DEVICE ${CMSIS}/Device/ATMEL/sam3xa)

add_compile_options(
    -mcpu=cortex-m3 -mthumb
    -ffunction-sections -fdata-sections
    -Wall -Wextra
    $<$<CONFIG:Debug>:-Og> $<$<CONFIG:Debug>:-g3>
    $<$<CONFIG:Release>:-Os>
)

# __SAM3X8E__ selects the device through sam.h -> sam3.h -> sam3xa.h.
# Do NOT define DONT_USE_CMSIS_INIT: it suppresses the system_sam3xa.h
# include, which is where SystemInit and SystemCoreClock are declared.
add_compile_definitions(__SAM3X8E__)

# lib/due_shared/src is the wire contract both tracks compile.
# arduino-cli reaches the same files as an Arduino library, via
# --libraries lib in tools/sketch.py.
include_directories(bsp drivers lib/due_shared/src)

# SYSTEM: vendor headers are not ours to fix, and -Wall -Wextra otherwise
# buries real diagnostics under warnings from the CMSIS pack.
include_directories(SYSTEM
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
# hours that quote the resulting image by commit. tools/sketch.py passes
# --clean for the same reason on the other track, and
# tests/test_clean_build.py fails if either is removed.
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

# Track A -- the reference oracle, built by arduino-cli against the Arduino
# core. build.f_cpu MUST match the runtime clock: micros() divides by it,
# and MCK is 78 MHz here so the ADC clock stays inside its 20 MHz limit.
if(ARDUINO_CLI)
    message(STATUS "arduino-cli:   ${ARDUINO_CLI}")
    # Both targets go through tools/sketch.py, which is the single place
    # that knows Track A's build properties. Repeating build.f_cpu here -
    # as this file did - builds a Track A that links, runs, and silently
    # costs 35-44 ADC overruns per 4 s, because build.ldscript is missing
    # and the capture ring is not in SRAM bank 1.
    add_custom_target(track_a
        COMMAND "${PY}" "${CMAKE_SOURCE_DIR}/tools/sketch.py" compile
                --arduino-cli "${ARDUINO_CLI}"
                --build-path "${CMAKE_BINARY_DIR}/track_a"
        COMMENT "Track A (arduino-cli, Arduino core -- the oracle)"
        USES_TERMINAL VERBATIM)

    add_custom_target(flash_track_a
        COMMAND "${PY}" "${CMAKE_SOURCE_DIR}/tools/sketch.py" upload
                --arduino-cli "${ARDUINO_CLI}"
                --build-path "${CMAKE_BINARY_DIR}/track_a"
        COMMENT "Flashing Track A"
        USES_TERMINAL VERBATIM)
else()
    message(STATUS "arduino-cli:   not found -- Track A targets unavailable")
endif()

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
