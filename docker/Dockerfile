# A pinned environment that builds both firmware tracks and runs the
# board-free test tier.
#
# The image exists so the build environment stops being an unrecorded
# variable: docs/build-container.md, phases 1 and 2. It compiles and
# tests the repository that is bind-mounted at /work; nothing of the
# project is baked in.
#
# EVERY INPUT IS PINNED, and that is the whole property. Two benches
# building this file weeks apart must get the same compiler, or the
# container delivers nothing a bare `apt install` does not. So: the base
# image is named by digest and never by a tag; the Ubuntu archive is a
# dated snapshot rather than "whatever is current"; every apt package
# names an exact version; and the two downloads are checked against a
# sha256 before anything is unpacked. A download that is not
# checksum-verified is a defect here, not a shortcut.
#
# WHAT IT DELIBERATELY DOES NOT DO. Nothing opens a serial port and no
# USB device is passed in, and the board tier stays on metal. A board
# test with no board SKIPS, and a skip is scored as a pass by whichever
# harness greps for failures - so the whole-suite run in here is worth
# only what --require-board beside it is worth.
#
# /dev IS WHAT HIDES THE BOARD, NOT /sys, and the difference decides
# which container arrangements are safe. Measured on linux-x1 with a
# board attached and enumerated on the host:
#
#   default run   /sys/class/tty lists ttyACM0/1/2 and their idVendor
#                 and idProduct read 2341:003d and 2341:003e - sysfs is
#                 the host's and is not namespaced. But /dev carries no
#                 ttyACM node, and pyserial's Linux backend GLOBS /dev
#                 first and only then annotates from sysfs, so
#                 comports() returns 0 ports and find_all_ports()
#                 returns (None, None, None)
#   -v /dev:/dev  all three appear with the right ids and discovery
#                 succeeds; an open is then the thing that fails
#
# So discovery is a /dev glob wearing sysfs metadata, not a sysfs walk,
# and this image is blind to the board because of the device nodes it
# does not have. Mount /dev - which is what surviving a re-enumeration
# would need - and the board is discoverable again.

FROM ubuntu@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517

# xPack 15.2.1-1.1: the release the project already characterises.
# `mac-bench` builds Track B with it and `windows-desk` carries it as an
# opt-in second arm, so the container standardises on a code generator
# the tree has data for rather than introducing a third.
#
# Changing it is this line and the sha256 below, which xPack publishes
# beside the tarball as `<asset>.sha`.
ARG XPACK_VERSION=15.2.1-1.1
ARG XPACK_SHA256=da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6

# Track A globs its sources out of an installed arduino:sam core, so the
# core ships here. The version is pinned for the reason toolchains.json
# already gives: a bench silently building against a different core is
# the mixed-revision hazard the clean-build rule exists for. The sha256
# is Arduino's own, out of package_index.json.
ARG SAM_CORE_VERSION=1.6.12
ARG SAM_CORE_SHA256=1d56d0ceea12a920c4a5c12fff793499354ffba7e93d330786bd2d6f3a191c47

# A dated Ubuntu archive. The exact versions below pin what is asked
# for; the snapshot pins what those packages drag in with them, which an
# `=version` on the command line does not reach.
ARG UBUNTU_SNAPSHOT=20260901T000000Z

# Installed from the live archive because the snapshot cannot be reached
# without it - apt has no trust roots in the bare base image. It is
# still pinned to a version, so it is a stated input like the rest.
ARG CA_CERTIFICATES_VERSION=20260601~24.04.1

ARG CMAKE_VERSION=3.28.3-1build7
ARG NINJA_VERSION=1.11.1-2
ARG MAKE_VERSION=4.3-4.1build2
ARG GIT_VERSION=1:2.43.0-1ubuntu7.3
ARG PYTHON3_VERSION=3.12.3-0ubuntu2.1
ARG CURL_VERSION=8.5.0-2ubuntu10.13
ARG XZ_UTILS_VERSION=5.6.1+really5.4.5-1ubuntu0.3
ARG BZIP2_VERSION=1.0.8-5.1ubuntu0.1

# A HOST compiler, which is a different tool from the cross compiler
# above and is not substitutable for it: arm-none-eabi-gcc -dumpmachine
# says arm-none-eabi and cannot run what it builds. Two board-free tests
# build a native harness and execute it - tests/test_framer_close.py
# builds it twice, real and mutant, and the mutant must fail - so
# without gcc here they skip, and a silent skip inside the tier whose
# honesty this image exists to test would be self-defeating.
#
# libc6-dev is named because --no-install-recommends does not pull it,
# and gcc without headers compiles nothing.
ARG GCC_VERSION=4:13.2.0-7ubuntu1
ARG LIBC6_DEV_VERSION=2.39-0ubuntu8.8

# THE 32-BIT ABI, WHICH IS THE TARGET'S AND NOT THE BENCH'S. Every
# machine this project runs on is x86-64 LP64; the SAM3X8E is a 32-bit
# Cortex-M3 where size_t, unsigned long, uintptr_t and every pointer are
# four bytes. So a defect in shared firmware C that needs 32-bit widths -
# a length that wraps, a cast that truncates, a struct that pads
# differently - cannot be reached by a harness built the way the bench
# is, and it is hidden in the direction that matters, because LP64 is
# the wider type in each case.
#
# gcc-multilib is what makes `gcc -m32` link: without it the front end
# accepts the flag and the LINK fails with "cannot find Scrt1.o", which
# names a path rather than a package. It drags gcc-13-multilib,
# lib32gcc-13-dev and libc6-dev-i386 with it and the snapshot pins those.
#
# The two lib32 sanitizer runtimes are NOT among them and are named here
# for the same reason libclang-rt-18-dev is: a harness that silently
# loses its instrumentation looks exactly like clean code. Their version
# is not gcc's - the compat runtimes for the gcc-13 ABI are built from
# the gcc-14 source package on this release, so 14.2.0 beside a 13.2.0
# compiler is correct and not a mismatch.
#
# tests/hostcc.py probes by building and running rather than trusting
# this line, and DUE_HOSTCC_ABI=32 re-runs the board-free tier's native
# harnesses against it.
ARG GCC_MULTILIB_VERSION=4:13.2.0-7ubuntu1
ARG LIB32ASAN_VERSION=14.2.0-4ubuntu2~24.04.1
ARG LIB32UBSAN_VERSION=14.2.0-4ubuntu2~24.04.1

# The suite is not stdlib: pytest and pyserial at least, and host/scope.py
# imports pyusb. python3-venv carries ensurepip, which is what builds the
# venv below.
ARG PYTHON3_VENV_VERSION=3.12.3-0ubuntu2.1

# THE EXTERNAL ANALYSERS, and they are pinned for a second reason on top
# of the one every other line here is pinned for. An unpinned analyser
# breaks "same Dockerfile, same image"; it also makes a *finding set*
# unreproducible, because a different version reports a different set and
# nobody can then tell a new defect from a new check. A backlog that
# moves under the reader is a backlog nobody reads.
#
# `clang` is here because `clang-tidy` is a clang front end: the builtin
# headers it parses against - stddef.h, stdint.h, the ones the freestanding
# target needs - ship with clang-18, and clang-tidy without them reports
# a wall of missing includes instead of findings. Installing it is NOT
# adopting clang as a firmware compiler; that is a port (target triple, a
# sysroot at the GCC toolchain's newlib and libgcc, linking through the
# GCC driver) and is a later phase.
#
# `clang` and `clang-tidy` are the default-version metapackages, so the
# version below says which LLVM series the image carries and the snapshot
# fixes the point release underneath it, exactly as it does for every
# other package here.
ARG CPPCHECK_VERSION=2.13.0-2ubuntu3
ARG CLANG_VERSION=1:18.0-59~exp2
ARG CLANG_TIDY_VERSION=1:18.0-59~exp2

# libFuzzer, and the sanitizer runtimes clang links against. NOT part of
# the clang metapackage: `clang -fsanitize=fuzzer` without this fails at
# the LINK with `cannot find libclang_rt.fuzzer-x86_64.a`, which names a
# path rather than a package and reads as a broken toolchain. The
# version is the real one - the metapackages above carry the 18.0-59
# series number and this carries the point release underneath it.
#
# gcc's own libasan and libubsan need no line here: libgcc-13-dev pulls
# them, and docker/run-tests.sh's tier builds its native harnesses with
# gcc. This package is what makes a libFuzzer CAMPAIGN possible, which
# the tier deliberately does not run - docker/run-fuzz.sh does.
ARG LIBCLANG_RT_VERSION=1:18.1.3-1ubuntu1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y --no-install-recommends \
        "ca-certificates=${CA_CERTIFICATES_VERSION}"; \
    printf '%s\n' \
        'Types: deb' \
        "URIs: https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}" \
        'Suites: noble noble-updates noble-security' \
        'Components: main universe' \
        'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' \
        > /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get -o Acquire::Check-Valid-Until=false update -qq; \
    apt-get install -y --no-install-recommends \
        "cmake=${CMAKE_VERSION}" \
        "ninja-build=${NINJA_VERSION}" \
        "make=${MAKE_VERSION}" \
        "git=${GIT_VERSION}" \
        "python3=${PYTHON3_VERSION}" \
        "curl=${CURL_VERSION}" \
        "xz-utils=${XZ_UTILS_VERSION}" \
        "bzip2=${BZIP2_VERSION}" \
        "gcc=${GCC_VERSION}" \
        "libc6-dev=${LIBC6_DEV_VERSION}" \
        "gcc-multilib=${GCC_MULTILIB_VERSION}" \
        "lib32asan8=${LIB32ASAN_VERSION}" \
        "lib32ubsan1=${LIB32UBSAN_VERSION}" \
        "python3-venv=${PYTHON3_VENV_VERSION}" \
        "cppcheck=${CPPCHECK_VERSION}" \
        "clang=${CLANG_VERSION}" \
        "clang-tidy=${CLANG_TIDY_VERSION}" \
        "libclang-rt-18-dev=${LIBCLANG_RT_VERSION}"; \
    rm -rf /var/lib/apt/lists/*

# /opt/xpack-arm-none-eabi-gcc-*/bin is already a Linux search pattern in
# toolchains.json, so unpacking here needs no registry change.
#
# NOT ON PATH, deliberately. If the toolchain were on PATH a build could
# find it while the registry lookup was broken, and the image would then
# be certifying a resolution it never performed. `hosttools_find` has to
# do the work, and `python3 tools/toolchain.py` reports what it resolved.
RUN set -eux; \
    url="https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v${XPACK_VERSION}/xpack-arm-none-eabi-gcc-${XPACK_VERSION}-linux-x64.tar.gz"; \
    curl -fsSL "$url" -o /tmp/xpack.tar.gz; \
    echo "${XPACK_SHA256}  /tmp/xpack.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/xpack.tar.gz -C /opt; \
    rm /tmp/xpack.tar.gz; \
    "/opt/xpack-arm-none-eabi-gcc-${XPACK_VERSION}/bin/arm-none-eabi-gcc" --version

# HOME is a container path holding only the vendored core, because that
# is where toolchains.json looks for it on Linux -
# {home}/.arduino15/packages/arduino/hardware/sam/<version>. Setting HOME
# rather than adding a pattern keeps the registry describing benches, and
# means the container resolves the core by the same rule a bench does.
#
# The tarball unpacks to an unversioned `sam/`, so the version lives in
# the destination name and nowhere else - which is what the registry
# pattern matches on, and what arduino-cli would have produced.
ENV HOME=/opt/due
RUN set -eux; \
    url="https://downloads.arduino.cc/cores/sam-${SAM_CORE_VERSION}.tar.bz2"; \
    curl -fsSL "$url" -o /tmp/sam.tar.bz2; \
    echo "${SAM_CORE_SHA256}  /tmp/sam.tar.bz2" | sha256sum -c -; \
    mkdir -p "${HOME}/.arduino15/packages/arduino/hardware/sam"; \
    tar -xjf /tmp/sam.tar.bz2 -C /tmp; \
    mv /tmp/sam \
       "${HOME}/.arduino15/packages/arduino/hardware/sam/${SAM_CORE_VERSION}"; \
    rm /tmp/sam.tar.bz2; \
    test -f "${HOME}/.arduino15/packages/arduino/hardware/sam/${SAM_CORE_VERSION}/cores/arduino/Arduino.h"; \
    chmod -R a+rX "${HOME}"

# The suite's venv, built at image time because docker/run.sh runs with
# --network none and pip cannot reach an index from there. It lives
# outside /work on purpose: /work is a bind mount of the bench's own
# tree, so a venv written there would collide with the bench's .venv,
# and a venv holds absolute paths and does not travel anyway.
#
# ON PATH, unlike the cross compiler. The toolchain is kept off PATH so
# that toolchains.json has to do the resolving; nothing resolves a venv
# through a registry, so the alternative here is every caller spelling
# out an absolute path. `python3` in this image is therefore the venv's,
# and `pip freeze` says so.
COPY requirements-lock.txt /tmp/requirements-lock.txt
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN set -eux; \
    /usr/bin/python3 -m venv "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/pip" install --no-cache-dir --require-hashes \
        -r /tmp/requirements-lock.txt; \
    rm /tmp/requirements-lock.txt; \
    chmod -R a+rX "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/python" -m pytest --version

# The container runs as the invoking user - docker/run.sh passes --user -
# so anything it writes into the mounted tree stays that user's. git then
# sees a repository owned by a uid with no passwd entry and refuses it,
# so state the exception once here rather than in every invocation.
RUN git config --system --add safe.directory '*'

WORKDIR /work
CMD ["/bin/bash"]
