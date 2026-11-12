# A pinned environment for the AFE PCB and simulation tools: KiCad's
# headless pcbnew and kicad-cli, ngspice, and the numpy tier, all on the
# Python KiCad's bindings are built for.
#
# It is a different image from docker/Dockerfile and stays one. The firmware
# image carries an ARM compiler, clang and a 24.04 userland; this one needs
# 26.04 (Python 3.14, which is what KiCad 10's bindings link). Nothing of
# the project is baked in: the repository is mounted at /work, as it is for
# the firmware image. Principles are docs/build-container.md's.
#
# EVERY INPUT IS PINNED. The base is named by digest. Ubuntu packages come
# from a dated snapshot at exact versions, and the snapshot pins what they
# drag in. KiCad is not in the Ubuntu archive; it comes from the KiCad
# project's PPA, and a PPA is not a snapshot (it serves the newest build
# and drops the old), so the three KiCad packages are fetched by exact
# file name and checked against a sha256 before apt sees them. Python
# packages come from a lock file with hashes, wheels only.
#
# HEADLESS. kicad-cli and `import pcbnew`; no GUI is started. The KiCad
# package depends on GTK and wx libraries and they come with it, unused.
# The 3D model package is not installed (3 GB, nothing here renders it).
#
# NO NETWORK AT RUN TIME. docker/pcb/run.sh passes --network none, memory
# limits and a timeout; what the tools need is here or it is a defect.

FROM ubuntu@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96

ARG UBUNTU_SNAPSHOT=20260901T000000Z

# Same bootstrap as the firmware image: the bare base has no trust roots,
# so a current ca-certificates comes from the live archive first, UNPINNED,
# and is replaced by this snapshot version, which keeps resolving.
ARG CA_CERTIFICATES_VERSION=20260601~26.04.1
ARG CURL_VERSION=8.18.0-1ubuntu2.4
ARG PYTHON314_VERSION=3.14.4-1ubuntu0.1
ARG NGSPICE_VERSION=45.2+ds-1
ARG TIME_VERSION=1.9-0.4

# KiCad 10.0.8 from ppa:kicad/kicad-10.0-releases, resolute. The version
# string is part of the file name; the sha256 is from the PPA's own
# Packages index at the time of pinning.
ARG KICAD_PPA=https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/pool/main
ARG KICAD_VERSION=10.0.8~ubuntu26.04.1
ARG KICAD_SHA256=eb8e81d7e9fc468ba26264debb5ce089fc078d5f91025790ecc92f51b91e536c
ARG KICAD_SYMBOLS_SHA256=9dce5b0530a1913ed1a62772370f0c63a45f210f6382e36bf7330525b3eccfee
ARG KICAD_FOOTPRINTS_SHA256=135a10dbb5d3aa1da66ccefeba44a389365d6c026877305e91eb4c575c1cf514

# Set to 0 to build the image WITHOUT ngspice. This exists for exactly one
# purpose: the gate's own control, which must FAIL on that image because a
# missing tool is an error there and never a skip. tests/test_image_gate.py
# builds it. Nothing else sets it.
ARG WITH_NGSPICE=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y --no-install-recommends ca-certificates; \
    printf '%s\n' \
        'Types: deb' \
        "URIs: https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}" \
        'Suites: resolute resolute-updates resolute-security' \
        'Components: main universe' \
        'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' \
        > /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get -o Acquire::Check-Valid-Until=false update -qq; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        --allow-downgrades \
        "ca-certificates=${CA_CERTIFICATES_VERSION}" \
        "curl=${CURL_VERSION}" \
        "python3.14=${PYTHON314_VERSION}" \
        "python3.14-venv=${PYTHON314_VERSION}" \
        "time=${TIME_VERSION}"; \
    if [ "${WITH_NGSPICE}" = 1 ]; then \
        apt-get install -y --no-install-recommends "ngspice=${NGSPICE_VERSION}"; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# The KiCad debs, verified before apt unpacks them, then installed with
# their dependencies resolved from the snapshot above (apt-get install on
# local files does that). The apt lists were removed above, so refresh.
RUN set -eux; \
    cd /tmp; \
    for spec in \
        "k/kicad/kicad_${KICAD_VERSION}_amd64.deb ${KICAD_SHA256}" \
        "k/kicad-library-symbols/kicad-symbols_${KICAD_VERSION}_all.deb ${KICAD_SYMBOLS_SHA256}" \
        "k/kicad-library-footprints/kicad-footprints_${KICAD_VERSION}_all.deb ${KICAD_FOOTPRINTS_SHA256}"; do \
        set -- $spec; \
        curl -fsSL --retry 5 "${KICAD_PPA}/$1" -o "$(basename "$1")"; \
        echo "$2  $(basename "$1")" | sha256sum -c -; \
    done; \
    apt-get -o Acquire::Check-Valid-Until=false update -qq; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends ./*.deb; \
    rm -rf /var/lib/apt/lists/* /tmp/*.deb; \
    kicad-cli version

# The numpy tier's interpreter: a venv on the system 3.14, with system site
# packages so `import pcbnew` (installed under /usr/lib/python3/dist-packages
# by the KiCad package) resolves, and numpy, scipy and pytest from the lock
# file, with hashes. On PATH, so `python3` here is this one.
COPY requirements-lock.txt /tmp/requirements-lock.txt
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN set -eux; \
    /usr/bin/python3.14 -m venv --system-site-packages "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true; \
    "$VIRTUAL_ENV/bin/python" -m pip --version; \
    "$VIRTUAL_ENV/bin/python" -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
        -r /tmp/requirements-lock.txt; \
    rm /tmp/requirements-lock.txt; \
    chmod -R a+rX "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/python" -c "import numpy, scipy, pytest, pcbnew; print(numpy.__version__, scipy.__version__, pcbnew.Version())"

# The container runs as the invoking user, which has no passwd entry; KiCad
# wants a writable home for its config, and a sticky world-writable
# directory serves any uid. It is empty at image time and gone with --rm.
ENV HOME=/opt/pcbhome
RUN mkdir -m 1777 /opt/pcbhome

WORKDIR /work
CMD ["/bin/bash"]
