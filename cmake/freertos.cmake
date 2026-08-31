# FreeRTOS for Track C, fetched at configure time and pinned by commit.
#
# The owner's ruling on issue #45 decision (3): **fetch at configure
# time, locked version, for build stability.**
#
# Pinned by COMMIT and not by tag. A tag is a moving reference - it can
# be repointed in the upstream repository without any change here - and
# "locked" has to mean an object that cannot change under us. The tag is
# recorded beside it so a human can see which release this is, but the
# tag is a comment and the hash is the contract.
#
# Fetching at configure time rather than at build time is what keeps
# this compatible with the project's "every build is a full build"
# discipline: `firmware_rtos` deletes every object before it compiles,
# and a fetch inside that loop would mean a network round trip per
# build. FetchContent populates once into the build tree and a clean
# does not touch it.
#
# OFFLINE AND OTHER BENCHES. This is opt-in - see BUILD_TRACK_C in
# CMakeLists.txt - so a bench that configures without it never reaches
# this file and its Track B build is unaffected by the network. A bench
# that has the sources already can point FETCHCONTENT_SOURCE_DIR_FREERTOS
# at them and no fetch happens at all:
#
#     cmake -B build -DBUILD_TRACK_C=ON \
#           -DFETCHCONTENT_SOURCE_DIR_FREERTOS=/path/to/FreeRTOS-Kernel
#
# That is FetchContent's own override, not a mechanism of ours, and it
# is what makes this work on a machine with no route to github.

include(FetchContent)

# V11.1.0. Read the hash, not the tag.
set(FREERTOS_TAG    "V11.1.0")
set(FREERTOS_COMMIT "f388a5c8078e152913e4eb3c5d75bf89561392df")

# SOURCE_SUBDIR names a directory that does not exist, which is the
# documented way to say "download it, do not build it".
#
# FreeRTOS-Kernel v11 ships its own CMakeLists.txt, and adding it would
# hand our source list to it: it wants a `freertos_config` INTERFACE
# target and a FREERTOS_PORT string, and it decides which files to
# compile - including a MemMang heap, which decision (4) on issue #45
# explicitly does not want. We name the sources below instead, for the
# reason given there: a version bump must not silently change what gets
# compiled, and that is the whole point of pinning.
FetchContent_Declare(freertos
    GIT_REPOSITORY https://github.com/FreeRTOS/FreeRTOS-Kernel.git
    GIT_TAG        ${FREERTOS_COMMIT}
    GIT_SHALLOW    FALSE      # a hash cannot be fetched shallowly
    GIT_PROGRESS   TRUE
    SOURCE_SUBDIR  do-not-add-this-subdirectory
)
FetchContent_MakeAvailable(freertos)

message(STATUS "Track C: FreeRTOS ${FREERTOS_TAG} (${FREERTOS_COMMIT}) "
               "at ${freertos_SOURCE_DIR}")

# The kernel sources this project compiles. Named rather than globbed:
# a glob would silently pick up whatever a version bump adds, and the
# point of pinning is that what gets compiled changes only on purpose.
#
# portable/GCC/ARM_CM3 is the full Cortex-M3 port. The SAM3X8E has
# BASEPRI, so the restricted CM0 variant is not needed - docs/rtos.md.
#
# No heap file. Decision (4) on #45 settled on
# configSUPPORT_STATIC_ALLOCATION with no heap at all, because it
# satisfies invariant 7 literally rather than by interpretation.
set(FREERTOS_SOURCES
    ${freertos_SOURCE_DIR}/tasks.c
    ${freertos_SOURCE_DIR}/list.c
    ${freertos_SOURCE_DIR}/queue.c
    ${freertos_SOURCE_DIR}/timers.c
    ${freertos_SOURCE_DIR}/portable/GCC/ARM_CM3/port.c
)
set(FREERTOS_INCLUDE
    ${freertos_SOURCE_DIR}/include
    ${freertos_SOURCE_DIR}/portable/GCC/ARM_CM3
)
