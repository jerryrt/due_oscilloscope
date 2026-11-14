# Task: five status LEDs on AFE-2

An intern task: add one power LED and four GPIO status LEDs to the
COPPIA AFE-2 shield, and predict what they do to the analog side before
drawing them. The intern does the whole design and validation flow on
their own, from the package this folder builds, and uses nothing else
in this repository.

| File | Reader | What |
|---|---|---|
| `brief.md` | the intern | the task: four points and the file list. Goes out as `BRIEF.md` in the package |
| `answer-sheet.md` | the owner, then the intern | expected answers, the impact table, the marking checklist. Sent only after marking, for study |
| `package/sim/scope_v2.cir` | the intern | the scope netlist with the clean-room amplifier model in place of the vendor macro |
| `make_package.py` | the owner | builds the package |

## How to give the task

1. **Build the package** from a checkout of `main` on a machine that has
   the five part datasheets (they are vendor PDFs kept out of git, under
   the checkout's untracked `hardware/afe-proto/models/`):

       python3 hardware/afe-proto/v2/tasks/status-leds/make_package.py OUT_DIR

   It writes `OUT_DIR/coppia-led-task/` and `OUT_DIR/coppia-led-task.zip`
   (about 18 MB, 54 files). Elsewhere, pass `--datasheets DIR` or
   `--no-datasheets` and have the intern download the five from their
   makers.
2. **Send the zip.** It holds the brief, the design files exactly as on
   `main`, the clean-room SPICE models and the datasheets. It holds no
   vendor model, no generator script, no fabrication output or render,
   and not the answer sheet.
3. **Hold the intern at the impact note.** Ask for the one-page note
   before any design work, and mark it against the answer sheet's
   impact table first; missing the AREF trap (row 1) fails the task.
4. **Mark the rest** with the answer sheet's checklist once the design,
   simulation, renders and bench plan come back, then send
   `answer-sheet.md`.

The intern's files are never merged as they are. If their design is
taken into AFE-2, it is re-entered through the project's own tools and
checks.
