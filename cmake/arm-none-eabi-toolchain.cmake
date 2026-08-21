# Toolchain definition for bare-metal SAM3X8E (Cortex-M3).
#
# The toolchain is expected under tools/, fetched separately; see
# docs/toolchain.md. It is deliberately NOT the compiler bundled with
# arduino:sam, which is gcc 4.8.3 from 2014.

set(CMAKE_SYSTEM_NAME       Generic)
set(CMAKE_SYSTEM_PROCESSOR  arm)

# Without this CMake tries to link a test executable during compiler
# detection, fails for want of _exit, and refuses to configure.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Prefer the xPack distribution. ARM's own macOS x86_64 build of
# 14.2.rel1 links cc1 against Homebrew's zstd at an absolute path
# (/usr/local/opt/zstd/lib/libzstd.1.dylib) and therefore cannot run on a
# machine without Homebrew. The driver starts, but cc1 dies in dyld. The
# xPack build bundles its dependencies via @rpath and is self-contained.
if(NOT DEFINED ARM_TOOLCHAIN_DIR)
    file(GLOB _candidates
         "${CMAKE_CURRENT_LIST_DIR}/../tools/xpack-arm-none-eabi-gcc-*/bin"
         "${CMAKE_CURRENT_LIST_DIR}/../tools/arm-gnu-toolchain-*/bin")
    if(NOT _candidates)
        message(FATAL_ERROR
            "No ARM toolchain under tools/. See docs/toolchain.md.")
    endif()
    list(GET _candidates 0 ARM_TOOLCHAIN_DIR)
endif()
message(STATUS "ARM toolchain: ${ARM_TOOLCHAIN_DIR}")

set(CMAKE_C_COMPILER   "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc")
set(CMAKE_CXX_COMPILER "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-g++")
set(CMAKE_ASM_COMPILER "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-gcc")
set(CMAKE_OBJCOPY      "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-objcopy" CACHE FILEPATH "")
set(CMAKE_SIZE         "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-size"    CACHE FILEPATH "")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
