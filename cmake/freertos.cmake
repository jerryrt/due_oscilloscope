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
# discipline: `firmware_track_c` deletes every object before it compiles,
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

# THE BUILD IMAGE CARRIES A COPY. docker/Dockerfile fetches this same pin
# when the image is built and names the directory in DUE_FREERTOS_DIR, so a
# container build, which has no network, configures from it. An explicit
# FETCHCONTENT_SOURCE_DIR_FREERTOS still wins.
if(NOT FETCHCONTENT_SOURCE_DIR_FREERTOS AND DEFINED ENV{DUE_FREERTOS_DIR})
    set(FETCHCONTENT_SOURCE_DIR_FREERTOS "$ENV{DUE_FREERTOS_DIR}")
endif()

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

# A local copy is held to the same pin a fetch is. FREERTOS_COMMIT is an
# annotated tag object, so both sides are peeled to the commit before they
# are compared, and a copy with local edits is refused as well: an edited
# kernel under the pinned hash is the mixed-revision image again.
if(FETCHCONTENT_SOURCE_DIR_FREERTOS)
    find_package(Git QUIET)
    if(NOT GIT_EXECUTABLE)
        message(FATAL_ERROR "Track C: FreeRTOS at ${freertos_SOURCE_DIR} "
                "cannot be checked against ${FREERTOS_COMMIT} without git")
    endif()
    execute_process(
        COMMAND ${GIT_EXECUTABLE} -C "${freertos_SOURCE_DIR}" rev-parse "HEAD^{commit}"
        OUTPUT_VARIABLE _freertos_head OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE _freertos_head_rc ERROR_QUIET)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} -C "${freertos_SOURCE_DIR}" rev-parse "${FREERTOS_COMMIT}^{commit}"
        OUTPUT_VARIABLE _freertos_pin OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE _freertos_pin_rc ERROR_QUIET)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} -C "${freertos_SOURCE_DIR}" diff --quiet HEAD
        RESULT_VARIABLE _freertos_dirty_rc ERROR_QUIET)
    if(NOT _freertos_head_rc EQUAL 0 OR NOT _freertos_pin_rc EQUAL 0
            OR NOT _freertos_head STREQUAL _freertos_pin)
        message(FATAL_ERROR "Track C: FreeRTOS at ${freertos_SOURCE_DIR} is not "
                "the pinned ${FREERTOS_TAG} (${FREERTOS_COMMIT}): HEAD is "
                "'${_freertos_head}', the pin names '${_freertos_pin}'")
    endif()
    if(NOT _freertos_dirty_rc EQUAL 0)
        message(FATAL_ERROR "Track C: FreeRTOS at ${freertos_SOURCE_DIR} has "
                "local changes on top of the pinned ${FREERTOS_TAG}")
    endif()
endif()

# WHERE THE SOURCES SIT IS NOT PART OF THE IMAGE. FreeRTOSConfig.h's
# configASSERT passes __FILE__, so without these a Track C image carries
# the absolute path of the checkout and of FreeRTOS, and two builds of one
# commit differ by where they were built: measured at 18,203 differing
# bytes between one FreeRTOS copy in two directories. The FreeRTOS map is
# last so it wins where FreeRTOS sits inside the tree, as it does under
# build-c/_deps.
set(FREERTOS_PREFIX_MAP
    -ffile-prefix-map=${CMAKE_SOURCE_DIR}=.
    -ffile-prefix-map=${freertos_SOURCE_DIR}=freertos
)

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
