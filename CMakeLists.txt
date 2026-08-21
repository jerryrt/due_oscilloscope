cmake_minimum_required(VERSION 3.16)
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

include_directories(bsp drivers)

# SYSTEM: vendor headers are not ours to fix, and -Wall -Wextra otherwise
# buries real diagnostics under warnings from the CMSIS pack.
include_directories(SYSTEM
    ${CMSIS}/Include
    ${CMSIS}/Device/ATMEL          # sam.h -> sam3.h -> sam3xa/include/
    ${DEVICE}/include
)

set(LINKER_SCRIPT ${CMAKE_SOURCE_DIR}/linker/sam3x8e_flash.ld)

add_executable(baremetal_bringup
    apps/baremetal_bringup/main.c
    bsp/startup_sam3x8e.c
    bsp/uart.c
    bsp/led.c
    bsp/systick.c
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

add_custom_command(TARGET baremetal_bringup POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:baremetal_bringup>
            $<TARGET_FILE_DIR:baremetal_bringup>/baremetal_bringup.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:baremetal_bringup>
    COMMENT "Generating .bin and reporting size"
)
