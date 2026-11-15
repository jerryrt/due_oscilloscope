#!/bin/bash
# Interactive HTML BOM for one board, inside the pinned image.
#
#     docker/pcb/run.sh docker/pcb/ibom.sh BOARD.kicad_pcb [--dest-dir DIR] [--name-format FMT] [--no-compression] ...
#
# Runs InteractiveHtmlBom 2.12.0 (the plugin, unpacked at $IBOM_HOME, hash-pinned in the Dockerfile) headless: no
# display, no browser. Every other argument is the plugin's own (--help lists them); with no --dest-dir the page
# lands in bom/ beside the board, the plugin's default. The log line "Created file <path>" names the output.
# Exit status is the plugin's.
set -uo pipefail
if [ ! -d "${IBOM_HOME:-/nonexistent}/InteractiveHtmlBom" ]; then
    echo "ibom.sh: InteractiveHtmlBom is not in this image; run it through docker/pcb/run.sh" >&2
    exit 3
fi
if [ $# -lt 1 ]; then
    echo "usage: ibom.sh BOARD.kicad_pcb [plugin options]" >&2
    exit 2
fi
export PYTHONPATH="$IBOM_HOME${PYTHONPATH:+:$PYTHONPATH}" INTERACTIVE_HTML_BOM_NO_DISPLAY=1
# wx prints a dozen "Debug: Adding duplicate image handler" lines on import; drop only those.
python3 -m InteractiveHtmlBom.generate_interactive_bom "$1" --no-browser "${@:2}" \
    2> >(grep -v 'Debug: Adding duplicate image handler' >&2)
rc=$?
wait
exit $rc
