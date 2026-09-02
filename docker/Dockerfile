# A pinned environment that builds both firmware tracks.
#
# The image exists so the build environment stops being an unrecorded
# variable: docs/build-container.md, phase 1. It compiles the repository
# that is bind-mounted at /work; nothing of the project is baked in.
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
# USB device is passed in. /sys is the host's and is not namespaced, so
# port discovery inside a container succeeds and every open then fails -
# a board test would skip, and a skip is scored as a pass by whichever
# harness reads it. The board tier stays on metal.

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
        "bzip2=${BZIP2_VERSION}"; \
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

# The container runs as the invoking user - docker/run.sh passes --user -
# so anything it writes into the mounted tree stays that user's. git then
# sees a repository owned by a uid with no passwd entry and refuses it,
# so state the exception once here rather than in every invocation.
RUN git config --system --add safe.directory '*'

WORKDIR /work
CMD ["/bin/bash"]
