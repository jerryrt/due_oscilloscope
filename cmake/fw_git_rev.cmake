# The commit an image was built from, written into a generated header.
#
# Run as a script - `cmake -DREPO_DIR=... -DOUT_FILE=... -P` - once at
# configure time and again from every firmware build wrapper, which is
# the whole point of it being a script rather than a `set()` in
# CMakeLists.txt. A value computed at configure time is right on the day
# the tree was configured and silently wrong every day after, and an
# image that names the wrong commit is worse than one that names none:
# the figures measured on it are then attributed to source that did not
# produce them.
#
# The written value is one of:
#
#   a905380            a clean tree: `git rev-parse --short HEAD`
#   a905380+1f2e3d4a   dirty: the commit, `+`, and the first eight hex
#                      characters of the working-tree delta hash
#   unknown            git could not answer
#
# THE DIRTY HASH IS tools/flash.py's `dirty_sha` AND MUST STAY SO. That
# field answers "same dirty or different dirty", which `repo_rev` cannot
# - it is identical for every dirty state of one commit, so a
# deliberately-reverted control image and a main image log as the same
# thing. A board that reports one quantity and the flash log another
# would put two names on one state and answer neither question. The
# definition copied here is that function's, down to the strip: sha256
# of `git diff HEAD` and `git status --porcelain`, each stripped, joined
# by a newline. `string(STRIP)` is Python's `str.strip()` for this
# input, and it is load-bearing rather than tidiness - porcelain lines
# for an unstaged edit begin with a space.
#
# `unknown` rather than an empty string or a zeroed SHA. A stated
# absence is this project's convention (`provenance.missing()`), and the
# alternative is a plausible-looking value that reads as a measurement.

if(NOT DEFINED REPO_DIR OR NOT DEFINED OUT_FILE)
    message(FATAL_ERROR
        "fw_git_rev.cmake needs -DREPO_DIR=<source tree> and "
        "-DOUT_FILE=<header to write>")
endif()

# Not `find_program` on PATH alone: on Windows git is installed where
# CMake's own FindGit looks and PATH frequently does not carry it. The
# caller passes GIT_EXECUTABLE from `find_package(Git)`; this fallback
# is for a direct `cmake -P` invocation.
if(NOT GIT_EXECUTABLE)
    find_program(GIT_EXECUTABLE NAMES git)
endif()

# Empty on any failure at all - no git, no work tree, a broken index.
# Never raises: a build that cannot name its commit still builds, and
# says `unknown`.
function(_fw_git out_var)
    set(${out_var} "" PARENT_SCOPE)
    if(NOT GIT_EXECUTABLE)
        return()
    endif()
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" ${ARGN}
        WORKING_DIRECTORY "${REPO_DIR}"
        RESULT_VARIABLE _rc
        OUTPUT_VARIABLE _out
        ERROR_QUIET)
    if(NOT _rc EQUAL 0)
        return()
    endif()
    string(STRIP "${_out}" _out)
    set(${out_var} "${_out}" PARENT_SCOPE)
endfunction()

set(FW_GIT_REV "unknown")

_fw_git(_rev rev-parse --short HEAD)
if(_rev)
    set(FW_GIT_REV "${_rev}")
    _fw_git(_porcelain status --porcelain)
    if(_porcelain)
        _fw_git(_diff diff HEAD)
        string(SHA256 _delta_sha "${_diff}\n${_porcelain}")
        string(SUBSTRING "${_delta_sha}" 0 8 _delta_short)
        set(FW_GIT_REV "${_rev}+${_delta_short}")
    endif()
endif()

# ctl_wire.h declares the wire field as `uint8_t build[24]`, so 23
# characters and a NUL. Fail here rather than truncate: a silently
# shortened commit is a wrong commit, and this is the one place that
# knows the length before anything depends on it.
string(LENGTH "${FW_GIT_REV}" _len)
if(_len GREATER 23)
    message(FATAL_ERROR
        "FW_GIT_REV is ${_len} characters ('${FW_GIT_REV}') and "
        "ctl_wire.h's build[24] holds 23 plus a NUL")
endif()

# configure_file, not file(WRITE): it leaves the file untouched when the
# content is unchanged, so a rebuild with no commit between does not
# restamp a header every translation unit includes.
configure_file("${CMAKE_CURRENT_LIST_DIR}/fw_git_rev.h.in" "${OUT_FILE}" @ONLY)
