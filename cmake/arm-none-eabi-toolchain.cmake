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
