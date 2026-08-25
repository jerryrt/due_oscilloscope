# Resolve host build tools from the shared registry (../toolchains.json).
#
# One lookup used by everything: the ARM toolchain file, and the Track A
# and flash targets in CMakeLists.txt. tools/toolchain.py implements the
# same rules for the scripts, reading the same file, so the build and the
# tooling around it can never disagree about where something lives.
#
# See docs/toolchain.md.

if(DEFINED _HOSTTOOLS_INCLUDED)
    return()
endif()
set(_HOSTTOOLS_INCLUDED TRUE)

set(HOSTTOOLS_REGISTRY_DIR "${CMAKE_CURRENT_LIST_DIR}/.." CACHE INTERNAL "")

# CMAKE_HOST_SYSTEM_NAME is normally set by the time a toolchain file is
# read, but that is not contractual this early; derive it if it is empty
# so a missing value cannot silently select another platform's patterns.
function(hosttools_platform out_var)
    set(_p "${CMAKE_HOST_SYSTEM_NAME}")
    if(NOT _p)
        if(CMAKE_HOST_WIN32)
            set(_p "Windows")
        elseif(CMAKE_HOST_APPLE)
            set(_p "Darwin")
        else()
            set(_p "Linux")
        endif()
    endif()
    set(${out_var} "${_p}" PARENT_SCOPE)
endfunction()

# HOME is set by Git Bash on Windows too, and points at a POSIX-style path
# CMake cannot glob. Prefer USERPROFILE where the host is actually Windows.
function(hosttools_home out_var)
    if(CMAKE_HOST_WIN32 AND DEFINED ENV{USERPROFILE})
        set(_h "$ENV{USERPROFILE}")
    else()
        set(_h "$ENV{HOME}")
    endif()
    string(REPLACE "\\" "/" _h "${_h}")
    set(${out_var} "${_h}" PARENT_SCOPE)
endfunction()

# Read tools.<tool>.<path...> from one registry file as a CMake list.
function(_hosttools_array out_var file tool)
    set(${out_var} "" PARENT_SCOPE)
    if(NOT EXISTS "${file}")
        return()
    endif()
    file(READ "${file}" _json)
    string(JSON _len ERROR_VARIABLE _err
           LENGTH "${_json}" tools ${tool} ${ARGN})
    if(_err OR NOT _len)
        return()
    endif()
    set(_acc "")
    math(EXPR _last "${_len} - 1")
    foreach(_i RANGE ${_last})
        string(JSON _item ERROR_VARIABLE _e
               GET "${_json}" tools ${tool} ${ARGN} ${_i})
        if(NOT _e)
            list(APPEND _acc "${_item}")
        endif()
    endforeach()
    set(${out_var} "${_acc}" PARENT_SCOPE)
endfunction()

# hosttools_find(<tool> <dir_var> [<exe_var>])
#
# Sets <dir_var> to the directory holding the tool, and <exe_var> to the
# executable inside it, or leaves both unset. toolchains.local.json is
# searched before toolchains.json; a local entry prepends rather than
# replaces, so an override for one machine cannot break the fallbacks
# every other machine relies on.
function(hosttools_find tool dir_var)
    set(exe_var "${ARGV2}")
    hosttools_platform(_plat)
    hosttools_home(_home)
    set(_repo "${HOSTTOOLS_REGISTRY_DIR}")

    # Read `requires` and `reject` from the LOCAL file first, then the
    # shared one - the same layering tools/toolchain.py does. Reading
    # only the shared file meant a tool declared solely in
    # toolchains.local.json resolved for the scripts and silently did not
    # for CMake, which is exactly the divergence one registry exists to
    # prevent.
    set(_requires "")
    foreach(_file "${_repo}/toolchains.local.json" "${_repo}/toolchains.json")
        if(_requires OR NOT EXISTS "${_file}")
            continue()
        endif()
        file(READ "${_file}" _json)
        string(JSON _r ERROR_VARIABLE _e GET "${_json}" tools ${tool} requires)
        if(NOT _e)
            set(_requires "${_r}")
        endif()
    endforeach()
    if(NOT _requires)
        set(_requires "${tool}")
    endif()

    set(_reject "")
    foreach(_file "${_repo}/toolchains.local.json" "${_repo}/toolchains.json")
        if(_reject)
            continue()
        endif()
        _hosttools_array(_reject "${_file}" ${tool} reject)
    endforeach()

    set(_patterns "")
    foreach(_file "${_repo}/toolchains.local.json" "${_repo}/toolchains.json")
        _hosttools_array(_p "${_file}" ${tool} search "${_plat}")
        list(APPEND _patterns ${_p})
    endforeach()

    foreach(_pattern IN LISTS _patterns)
        string(REPLACE "{repo}" "${_repo}" _pattern "${_pattern}")
        string(REPLACE "{home}" "${_home}" _pattern "${_pattern}")
        file(GLOB _hits "${_pattern}")
        list(SORT _hits ORDER DESCENDING)
        foreach(_hit IN LISTS _hits)
            if(NOT IS_DIRECTORY "${_hit}")
                continue()
            endif()
            set(_rejected FALSE)
            foreach(_r IN LISTS _reject)
                string(REPLACE "*" ".*" _rx "${_r}")
                if("${_hit}" MATCHES "${_rx}")
                    set(_rejected TRUE)
                endif()
            endforeach()
            if(_rejected)
                continue()
            endif()
            # Existence of the directory is not enough: a stale install
            # outlives its contents and would otherwise shadow a working
            # tool further down the list.
            foreach(_suffix "" ".exe")
                if(EXISTS "${_hit}/${_requires}${_suffix}")
                    set(${dir_var} "${_hit}" PARENT_SCOPE)
                    if(exe_var)
                        set(${exe_var} "${_hit}/${_requires}${_suffix}" PARENT_SCOPE)
                    endif()
                    return()
                endif()
            endforeach()
        endforeach()
    endforeach()
endfunction()
