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
# HEADLESS. kicad-cli and `import pcbnew`; no GUI is started. `kicad-cli pcb
# render` works here: it rasterises through Mesa's software driver, which the
# KiCad package's own dependencies bring in, so no GL pin of ours is needed -
# but nothing is rendered with component bodies (no 3D model package), and a
# software render is not byte-stable, so the gate checks that a render is
# produced and not what it looks like. The KiCad
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
# The 3D package is 279 MB to fetch and 3.3 GB to install, and the repository's
# boards use sixteen of its models. Only those are taken (docker/pcb/3dmodels.txt,
# one path per line under the package's 3dmodels directory); the rest never
# reaches a layer. A gate test requires every model a repository board names to
# resolve, so a board that starts using a new model fails until its path is added.
ARG KICAD_PACKAGES3D_SHA256=435ac54a87f6188a8e8817f335c0b79ba29f25f59c16665fdc0c24ee9b2f74d2

# Set to 0 to build the image WITHOUT ngspice. This exists for exactly one
# purpose: the gate's own control, which must FAIL on that image because a
# missing tool is an error there and never a skip. tests/test_image_gate.py
# builds it. Nothing else sets it.
ARG WITH_NGSPICE=1

# Freerouting, the autorouter, headless. Java comes from the same dated archive snapshot at an exact version; the
# jar is the project's GitHub release asset, verified against its sha256 before it is used (the release page
# publishes the digest beside the asset). The jar is built for Java 25, hence openjdk-25. WITH_FREEROUTING=0
# builds the image WITHOUT it, for the gate's own control, which must FAIL there: a missing router is an error and
# never a skip. docker/pcb/freeroute.sh is the one way it is run.
#
# WHY THE JAR AND NOT THE NATIVE CLI, to be revisited on a later release. 2.5.0 also ships a GraalVM native
# executable (freerouting-cli-2.5.0-linux-x64.tar.gz, sha256 64a957a9ef2a2fbde6ab2001bb32800f5ba34f9fd15575e363512934b870d63a,
# 20.7 MB, needing only libc and libz), which would drop the JDK (about 480 MB). Measured in the r3 image on a
# 4-resistor board, 2026-11-13: it prints its usage and starts, then routing dies with
#   UnsupportedFeatureError: SerializationConstructorAccessor class not found for declaringClass:
#   app.freerouting.board.model.items.ComponentOutline
# (a missing GraalVM serialization configuration) and the process HANGS instead of exiting; no session is written.
# The jar routes the same board in 0.3 s. To retry: fetch the CLI tarball of the new release, verify its sha256
# against the release's checksums file, and run tests/test_freerouting.py with it in place of `java -jar`.
ARG OPENJDK_VERSION=25.0.4+7-1~26.04
ARG FREEROUTING_VERSION=2.5.0
ARG FREEROUTING_SHA256=f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7
ARG WITH_FREEROUTING=1

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

# The 3D bodies the boards use, extracted from the pinned package without
# installing it. KICAD10_3DMODEL_DIR is KiCad's own default for this directory,
# so board files that say ${KICAD10_3DMODEL_DIR}/... resolve with no setting.
COPY 3dmodels.txt /tmp/3dmodels.txt
RUN set -eux; \
    cd /tmp; \
    f="kicad-packages3d_${KICAD_VERSION}_all.deb"; \
    curl -fsSL --retry 5 "${KICAD_PPA}/k/kicad-library-packages3d/$f" -o "$f"; \
    echo "${KICAD_PACKAGES3D_SHA256}  $f" | sha256sum -c -; \
    sed 's|^|./usr/share/kicad/3dmodels/|' 3dmodels.txt > members.txt; \
    dpkg-deb --fsys-tarfile "$f" | tar -x -C / --no-same-owner -T members.txt; \
    while read -r m; do test -f "/usr/share/kicad/3dmodels/$m"; done < 3dmodels.txt; \
    rm -f "$f" members.txt 3dmodels.txt

# The autorouter. Its own layer, after KiCad, so the control image (WITH_FREEROUTING=0) shares everything before it.
# The snapshot source is still configured; only the package lists were removed, so refresh them.
RUN set -eux; \
    if [ "${WITH_FREEROUTING}" = 1 ]; then \
        apt-get -o Acquire::Check-Valid-Until=false update -qq; \
        apt-get -o Acquire::Retries=5 install -y --no-install-recommends "openjdk-25-jre-headless=${OPENJDK_VERSION}"; \
        rm -rf /var/lib/apt/lists/*; \
        mkdir -p /opt/freerouting; \
        curl -fsSL --retry 5 "https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar" \
            -o /opt/freerouting/freerouting.jar; \
        echo "${FREEROUTING_SHA256}  /opt/freerouting/freerouting.jar" | sha256sum -c -; \
        chmod -R a+rX /opt/freerouting; \
        java -version; \
    fi
ENV FREEROUTING_JAR=/opt/freerouting/freerouting.jar

# The numpy tier's interpreter: a venv on the system 3.14, with system site
# packages so `import pcbnew` (installed under /usr/lib/python3/dist-packages
# by the KiCad package) resolves, and numpy, scipy and pytest from the lock
# file, with hashes. On PATH, so `python3` here is this one.
COPY requirements-lock.txt /tmp/requirements-lock.txt
ENV VIRTUAL_ENV=/opt/venv
# Nothing a run does may write bytecode into the mounted repository: a
# __pycache__ beside a fixture changed it, and the second gate run failed on
# the first one's leavings. test_image_gate runs the gate twice.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH=/opt/venv/bin:$PATH
RUN set -eux; \
    /usr/bin/python3.14 -m venv --system-site-packages "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/python" -m pip --version; \
    "$VIRTUAL_ENV/bin/python" -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
        -r /tmp/requirements-lock.txt; \
    rm /tmp/requirements-lock.txt; \
    chmod -R a+rX "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/python" -c "import numpy, scipy, pytest, pcbnew; print(numpy.__version__, scipy.__version__, pcbnew.Version())"

# The container runs as the invoking user, which has no passwd entry; KiCad
# wants a writable home for its config, and a sticky world-writable
# directory serves any uid. It is gone with --rm.
#
# KiCad's GLOBAL library tables live in the user's config, and an empty
# home has none: kicad-cli then cannot resolve a standard symbol or
# footprint, and ERC on the v1 schematic reports 252 violations against 5
# with them (lib_symbol_issues and footprint_link_issues are the 247).
# So the two tables KiCad ships as its template are installed here, fixed
# in the image rather than left to whoever runs it. tests/test_image_gate.py
# runs ERC on a fixture and requires the libraries to resolve.
ENV HOME=/opt/pcbhome
RUN set -eux; \
    mkdir -m 1777 /opt/pcbhome; \
    mkdir -p /opt/pcbhome/.config; \
    mkdir -m 1777 /opt/pcbhome/.config/kicad /opt/pcbhome/.config/kicad/10.0; \
    install -m 0644 /usr/share/kicad/template/sym-lib-table /usr/share/kicad/template/fp-lib-table \
        /opt/pcbhome/.config/kicad/10.0/

WORKDIR /work
CMD ["/bin/bash"]
