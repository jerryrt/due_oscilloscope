# Toolchain definition for bare-metal SAM3X8E (Cortex-M3).
#
# Where the compiler lives is a property of the machine, not of the
# project, so it is not hardcoded. Search patterns live in the shared,
# committed ../toolchains.json and are resolved by cmake/hosttools.cmake;
# describing a new host means adding a pattern there, not editing CMake.
#
# Resolution order, first hit wins:
#
#   1. -DARM_TOOLCHAIN_DIR=...      one-off, and what CI passes
#   2. $ENV{ARM_TOOLCHAIN_DIR}      per shell
#   3. toolchains.local.json        per machine, gitignored
#   4. toolchains.json              the shared registry
#
# See docs/toolchain.md.

set(CMAKE_SYSTEM_NAME       Generic)
set(CMAKE_SYSTEM_PROCESSOR  arm)

# Without this CMake tries to link a test executable during compiler
# detection, fails for want of _exit, and refuses to configure.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

include("${CMAKE_CURRENT_LIST_DIR}/hosttools.cmake")

if(NOT DEFINED ARM_TOOLCHAIN_DIR AND DEFINED ENV{ARM_TOOLCHAIN_DIR})
    set(ARM_TOOLCHAIN_DIR "$ENV{ARM_TOOLCHAIN_DIR}")
    message(STATUS "ARM toolchain: ARM_TOOLCHAIN_DIR from the environment")
endif()

if(NOT DEFINED ARM_TOOLCHAIN_DIR)
    hosttools_find(arm_toolchain ARM_TOOLCHAIN_DIR)
endif()

if(NOT DEFINED ARM_TOOLCHAIN_DIR OR NOT ARM_TOOLCHAIN_DIR)
    hosttools_platform(_plat)
    message(FATAL_ERROR
        "No ARM toolchain found for host '${_plat}'.\n"
        "Checked every pattern in toolchains.json. Install one, add a "
        "pattern there (shared), create toolchains.local.json (this "
        "machine only), or pass -DARM_TOOLCHAIN_DIR=<dir>.\n"
        "Run  python3 tools/toolchain.py  to see what resolved.\n"
        "See docs/toolchain.md.")
endif()

# Executable suffix is a host property, not a target one, and CMake wants
# the full path including it. Probe rather than assume: ARM_TOOLCHAIN_DIR
# may have come from -D or the environment, where no suffix is known.
set(_exe "")
if(EXISTS "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc.exe")
    set(_exe ".exe")
elseif(NOT EXISTS "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc")
    message(FATAL_ERROR
        "ARM_TOOLCHAIN_DIR holds no arm-none-eabi-gcc: ${ARM_TOOLCHAIN_DIR}")
endif()

message(STATUS "ARM toolchain: ${ARM_TOOLCHAIN_DIR}")

set(CMAKE_C_COMPILER   "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc${_exe}")
set(CMAKE_CXX_COMPILER "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-g++${_exe}")
set(CMAKE_ASM_COMPILER "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc${_exe}")
set(CMAKE_OBJCOPY      "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-objcopy${_exe}" CACHE FILEPATH "")
set(CMAKE_SIZE         "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-size${_exe}"    CACHE FILEPATH "")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)

# ---------------------------------------------------------------------------
# Optional: clang as the firmware compiler.
#
#     cmake -B build-clang \
#           -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
#           -DCMAKE_BUILD_TYPE=Release -DFIRMWARE_CLANG=ON
#
# GCC IS THE DEFAULT AND NOTHING ABOVE THIS LINE MOVES. Everything below
# it is inert unless FIRMWARE_CLANG is on, and a default build produces
# the same bytes it did before this block existed.
#
# ONE TOOLCHAIN FILE, NOT TWO, because the clang build needs the GCC one
# resolved anyway: clang supplies a front end and a code generator and
# nothing else. The libc headers, newlib, libgcc and the linker come
# from ARM_TOOLCHAIN_DIR, so a second toolchain file would have to
# repeat the whole registry lookup above and could then disagree with it
# about which cross toolchain this bench has. Every caller in the tree
# spells `-DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake`
# by hand - docker/build-firmware.sh, tools/reproducible.py,
# tools/stack_frames.py, host/measure.py's error message, four
# documents - and a flag beside it costs those none.
#
# A BUILD DIRECTORY IS ONE COMPILER'S. CMake caches CMAKE_C_COMPILER, so
# adding this flag to a configured GCC tree makes it refuse; configure a
# separate directory rather than trying to flip one.
if(FIRMWARE_CLANG)
    # Not resolved through toolchains.json. That registry exists because
    # the cross tools are in a different place on every bench and on
    # none of them is Windows' PATH; clang is a system package that
    # installs onto PATH, and the only place this project has one is the
    # build image. -DCLANG_C_COMPILER=/path/to/clang is the escape hatch
    # for a bench that keeps it somewhere else.
    if(NOT CLANG_C_COMPILER)
        find_program(CLANG_C_COMPILER NAMES clang)
    endif()
    if(NOT CLANG_CXX_COMPILER)
        find_program(CLANG_CXX_COMPILER NAMES clang++)
    endif()
    if(NOT CLANG_C_COMPILER OR NOT CLANG_CXX_COMPILER)
        message(FATAL_ERROR
            "FIRMWARE_CLANG=ON but no clang on PATH.\n"
            "Install one, or pass -DCLANG_C_COMPILER=<path to clang> "
            "and -DCLANG_CXX_COMPILER=<path to clang++>.\n"
            "docker/run.sh runs the pinned image, which carries clang 18.")
    endif()

    # THE LIBC HEADERS ARE ASKED FOR, NOT WRITTEN DOWN.
    #
    # clang ships builtin headers for the freestanding set - stddef.h,
    # stdint.h, float.h - and stops there. Every translation unit that
    # includes <stdio.h> or <stdlib.h> then dies "file not found", which
    # is most of them. The search path that answers it belongs to
    # whichever cross toolchain this bench resolved, so it is harvested
    # from that compiler with `-E -v` rather than hardcoded: a literal
    # /opt/xpack-... would be right in the container and wrong on every
    # bench. docker/clang_tidy_db.py harvests the same way for the same
    # reason.
    #
    # -isystem rather than -I: these are not ours and their warnings are
    # not ours to fix.
    #
    # Once per language. The C++ list carries the libstdc++ headers and
    # the C one must not.
    function(_fw_clang_sysincludes out_var lang std)
        set(_probe "${CMAKE_BINARY_DIR}/fw_clang_probe_${lang}")
        file(WRITE "${_probe}" "")
        execute_process(
            COMMAND "${CMAKE_C_COMPILER}" -E -v -x${lang} ${std} "${_probe}"
            OUTPUT_VARIABLE _out ERROR_VARIABLE _err RESULT_VARIABLE _rc)
        set(_inside FALSE)
        set(_flags "")
        string(REPLACE "\n" ";" _lines "${_err}")
        foreach(_line IN LISTS _lines)
            string(STRIP "${_line}" _line)
            if(_line MATCHES "^#include <\\.\\.\\.> search starts here:")
                set(_inside TRUE)
            elseif(_line MATCHES "^End of search list\\.")
                break()
            elseif(_inside AND IS_DIRECTORY "${_line}")
                string(APPEND _flags " -isystem ${_line}")
            endif()
        endforeach()
        if(NOT _flags)
            message(FATAL_ERROR
                "${CMAKE_C_COMPILER} printed no ${lang} include search "
                "path (exit ${_rc}); clang cannot be given the libc "
                "headers.\n${_err}")
        endif()
        set(${out_var} "${_flags}" PARENT_SCOPE)
    endfunction()

    _fw_clang_sysincludes(_fw_clang_inc_c   c   -std=gnu11)
    _fw_clang_sysincludes(_fw_clang_inc_cxx c++ -std=gnu++11)

    # The GCC driver is still the linker, so keep hold of it before the
    # compiler variables are pointed at clang.
    set(_fw_link_c   "${CMAKE_C_COMPILER}")
    set(_fw_link_cxx "${CMAKE_CXX_COMPILER}")

    set(CMAKE_C_COMPILER   "${CLANG_C_COMPILER}")
    set(CMAKE_CXX_COMPILER "${CLANG_CXX_COMPILER}")
    set(CMAKE_ASM_COMPILER "${CLANG_C_COMPILER}")

    # Said out loud rather than inferred. clang's driver reads a target
    # out of argv[0] when it is called arm-none-eabi-clang, and it is
    # not called that here: without this it compiles for the host, where
    # sizeof(void *) is 8 and every packed wire-layout assertion in
    # frame.h means something else. CMake turns these into --target= on
    # the compile line.
    set(CMAKE_C_COMPILER_TARGET   arm-none-eabi)
    set(CMAKE_CXX_COMPILER_TARGET arm-none-eabi)
    set(CMAKE_ASM_COMPILER_TARGET arm-none-eabi)

    # -Wno-unused-command-line-argument, and it is load-bearing rather
    # than tidiness: -Werror is on by default, and clang 18 ACCEPTS
    # gcc's tuning knobs - `--param max-inline-insns-single=` and
    # `-specs=` - as unused arguments rather than rejecting them. An
    # unused-argument warning promoted to an error would fail every
    # Track A translation unit over a flag that changes nothing.
    # -Wno-unknown-warning-option for the same shape: a -Wno-... gcc
    # understands is not necessarily one clang does.
    #
    # -fshort-enums IS AN ABI FLAG AND NOT A PREFERENCE. The ARM EABI
    # leaves enum size variable and arm-none-eabi-gcc takes that
    # default; clang takes `int`. Two objects that disagree about the
    # width of an enum have a calling convention between them, and the
    # link says so - `uses variable-size enums yet the output is to use
    # 32-bit enums; use of enum values across objects may fail`, once
    # per newlib and libgcc member, on an image that still links. With
    # this, arm-none-eabi-readelf -A reports `Tag_ABI_enum_size: small`
    # on a clang object exactly as it does on a gcc one, and the link is
    # quiet.
    set(_fw_clang_common
        "-fshort-enums -Wno-unused-command-line-argument -Wno-unknown-warning-option")
    set(CMAKE_C_FLAGS_INIT   "${_fw_clang_common}${_fw_clang_inc_c}")
    set(CMAKE_CXX_FLAGS_INIT "${_fw_clang_common}${_fw_clang_inc_cxx}")
    set(CMAKE_ASM_FLAGS_INIT "${_fw_clang_common}")

    # LINK THROUGH THE GCC DRIVER. clang cannot link a bare-metal image
    # here on its own - newlib, libgcc, the nano specs and the crt are
    # the GCC toolchain's, and an image linked against anything else is
    # not the image this project measures. So the object files are
    # clang's and everything below them is unchanged.
    #
    # <FLAGS> IS DROPPED FROM THE LINK RULE, and that is the one thing
    # to know before editing these lines. It expands to CMAKE_<LANG>_FLAGS,
    # which above carries clang's --target= and clang's -isystem list;
    # arm-none-eabi-gcc rejects the first outright. Everything the link
    # genuinely needs - -mcpu, -mthumb, -T, -specs=nano.specs,
    # -nostartfiles - is in target_link_options and arrives through
    # <LINK_FLAGS>. Anything a bench puts in CMAKE_C_FLAGS expecting it
    # to reach the linker will not.
    set(CMAKE_C_LINK_EXECUTABLE
        "${_fw_link_c} <CMAKE_C_LINK_FLAGS> <LINK_FLAGS> <OBJECTS> -o <TARGET> <LINK_LIBRARIES>")
    set(CMAKE_CXX_LINK_EXECUTABLE
        "${_fw_link_cxx} <CMAKE_CXX_LINK_FLAGS> <LINK_FLAGS> <OBJECTS> -o <TARGET> <LINK_LIBRARIES>")

    # The archiver comes from the cross toolchain too. Left to itself
    # CMake picks whatever ar sits beside clang, which is the host's.
    set(CMAKE_AR      "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-ar${_exe}"      CACHE FILEPATH "")
    set(CMAKE_RANLIB  "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-ranlib${_exe}"  CACHE FILEPATH "")

    # WHAT BUILDS AND WHAT DOES NOT, so the next reader does not have to
    # diagnose it twice.
    #
    # Track B and Track C build. TRACK A DOES NOT, and the cause is the
    # vendored Arduino core rather than anything here:
    # arm-none-eabi-gcc predefines __INT32_TYPE__ as `long int` and
    # clang predefines it as `int`, so `uint32_t` and `unsigned long`
    # are one type under GCC and two under clang - and
    # cores/arduino/USB/CDC.cpp declares `uint32_t Serial_::baud()`
    # while defining `unsigned long Serial_::baud()`. It is a hard
    # error with no -Wno- form, and three lines reproduce it with no
    # Arduino source in sight:
    #
    #     #include <stdint.h>
    #     struct S { uint32_t f(); };
    #     unsigned long S::f() { return 0; }
    #
    # Redefining clang's predefined type macros on the command line
    # does compile the core, and is deliberately not done here.
    # Scoped to the vendored core it would leave the core mangling a
    # 32-bit parameter as `m` and the sketch as `j`; applied to
    # everything it changes what `uint32_t` *is* in the shared
    # wire-contract sources, which is a semantic change made to satisfy
    # a 2014 declaration.
    #
    # The clang link also reports `missing .note.GNU-stack section
    # implies executable stack` against a newlib member. clang emits
    # that section and gcc does not, so the check only runs on this
    # path; a Cortex-M3 has no such protection to lose. It is left
    # visible rather than silenced, because the flag that hides it
    # would hide the next one too.
    message(STATUS "firmware compiler: ${CLANG_C_COMPILER} (linking through ${_fw_link_c})")
endif()
