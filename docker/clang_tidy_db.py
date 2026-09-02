#!/usr/bin/env python3
"""Rewrite a CMake compile database into one clang can parse.

Called by docker/run-clang-tidy.sh, which is the thing to read first.
This file is the flag filter that script needs, kept separate because it
is the part with the reasoning in it and the part a change is most
likely to break.

WHY A REWRITE RATHER THAN --extra-arg. Three jobs, and only the first is
reachable from clang-tidy's command line:

  1. add what clang needs and gcc does not - the target triple, and the
     libc headers,
  2. drop what would abort the parse - -Werror, which promotes any
     clang-only warning into an error that ends the translation unit,
  3. SELECT. build-a's database holds 108 entries and only 80 of them
     are Track A's; the other 28 are baremetal_bringup, and the shared
     lib/due_shared/src sources appear in BOTH, compiled with different
     flags. clang-tidy takes the first entry whose file matches, so
     without a selection step "analyse Track A's copy" is a coin toss
     that nothing reports the outcome of.

THE LIBC HEADERS ARE ASKED FOR, NOT WRITTEN DOWN. Without them the
parse dies at the first #include <stdio.h> - measured, on
drivers/stream.c and lib/due_shared/src/console.c - because clang's
builtin headers cover stdint.h and stddef.h and stop there. The path is
harvested from the cross compiler named in the database itself, with
`-E -v` on an empty file, so it follows the toolchain a bench actually
resolved rather than a path hardcoded for one image. A hardcoded
/opt/xpack-... would be right in the container and wrong on every bench.

WHAT IS DROPPED, AND WHY EACH ONE.

  -Werror     a clang-only warning would otherwise end the parse, and a
              translation unit that did not compile reports no findings
              at all - which is the failure mode this whole script is
              built to make visible. Warnings still appear; they are
              read rather than fatal.
  -w          Track A's, from cmake/track_a.cmake, where it silences the
              vendored core and reaches the sketch with it. It does NOT
              disable clang-tidy's own checks - measured: bugprone-*
              fires through it - but it does disable the
              clang-diagnostic-* half, which is half of what an analyser
              is for. The vendored core is on -isystem and stays quiet
              either way, so dropping it exposes our code and not
              Arduino's.
  --param     gcc tuning knobs clang has no equivalent for. clang 18
  -specs=     accepts both with an unused-argument warning rather than
              an error, so this is belt and braces - but that warning
              becomes fatal the moment a -Werror survives, and one of
              them did until the line above.
  -o <path>   nothing may write into the tree. clang-tidy does not emit
              an object, and the flag is removed so it cannot.

Nothing that changes what the code MEANS is touched: every -D, -I,
-isystem, -std and -m flag is passed through exactly as gcc got it.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

# Flags to drop, matched against the whole argument.
DROP_EXACT = {"-Werror", "-w"}
DROP_PREFIX = ("-specs=",)
# Dropped together with the argument that follows them. `--param` is
# spelled `--param max-inline-insns-single=500` in cmake/track_a.cmake,
# two words, and dropping only the first leaves clang reading the second
# as a filename: "no such file or directory:
# 'max-inline-insns-single=500'", which ends the parse of every Track A
# translation unit. Found by running it.
DROP_WITH_VALUE = {"--param", "-o"}

# Added in front of every command. --target is belt and braces: clang's
# driver already infers arm-none-eabi from the arm-none-eabi-gcc in
# argv[0], which is why an unfiltered database appears to work. That is
# an inference from a filename, and this says it out loud so a rename or
# a compiler wrapper cannot silently move the analysis to the host
# triple - where sizeof(void *) is 8 and every packed wire-layout
# assertion in frame.h means something else.
EXTRA_BEFORE = [
    "--target=arm-none-eabi",
    # clang and gcc do not have the same warning names, and a -Wno-...
    # gcc understands is not necessarily one clang does.
    "-Wno-unknown-warning-option",
    "-Wno-unused-command-line-argument",
]


def gcc_system_includes(cc, lang_args):
    """The -isystem list the named cross compiler would use itself.

    `<cc> -E -v -` on an empty file prints its search path between two
    marker lines. Parsed rather than guessed, because it is the one
    answer that follows whichever toolchain the build resolved.
    """
    proc = subprocess.run(
        [cc, "-E", "-v", *lang_args, "-"],
        input="", capture_output=True, text=True)
    out, inside, dirs = proc.stderr, False, []
    for line in out.splitlines():
        if line.startswith("#include <...> search starts here:"):
            inside = True
            continue
        if line.startswith("End of search list."):
            break
        if inside:
            d = line.strip()
            if d and os.path.isdir(d):
                dirs.append(d)
    if not dirs:
        sys.exit("clang_tidy_db: %s printed no include search path.\n%s"
                 % (cc, out[-2000:]))
    return dirs


def rewrite(entry, sysincludes):
    args = shlex.split(entry["command"])
    cc, rest, out = args[0], args[1:], []
    skip = False
    for a in rest:
        if skip:
            skip = False
            continue
        if a in DROP_WITH_VALUE:
            skip = True
            continue
        if a in DROP_EXACT or a.startswith(DROP_PREFIX):
            continue
        out.append(a)
    flags = EXTRA_BEFORE + [x for d in sysincludes for x in ("-isystem", d)]
    return {
        "directory": entry["directory"],
        "arguments": [cc] + flags + out,
        "file": entry["file"],
        "output": entry["output"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="input compile_commands.json")
    ap.add_argument("--out", required=True, help="directory to write the rewritten db into")
    ap.add_argument("--target-dir", required=True,
                    help="object-path prefix that selects one CMake target, "
                         "e.g. CMakeFiles/track_a_bringup.dir/")
    ap.add_argument("--under", action="append", required=True,
                    help="repository-relative directory whose sources are ours "
                         "to analyse; repeatable")
    ap.add_argument("--repo", required=True, help="repository root, as the db spells it")
    ap.add_argument("--canary-src",
                    help="a source file to give a database entry of its own, "
                         "carrying this pass's flags with only the filename "
                         "changed. docker/run-clang-tidy.sh runs it as the "
                         "positive control")
    ap.add_argument("--canary-out",
                    help="directory to write the canary's one-entry database into")
    args = ap.parse_args()

    with open(args.db) as fh:
        db = json.load(fh)

    roots = [os.path.join(args.repo, u.rstrip("/")) + "/" for u in args.under]
    picked = [e for e in db
              if e.get("output", "").startswith(args.target_dir)
              and any(e["file"].startswith(r) for r in roots)]

    if not picked:
        sys.exit("clang_tidy_db: %s selected no entry from %s (%d entries). "
                 "The target or the source layout has moved."
                 % (args.target_dir, args.db, len(db)))

    # One harvest per language, not one per file: the C++ search path
    # carries the libstdc++ headers and the C one must not.
    cache = {}
    rewritten = []
    for e in picked:
        cc = shlex.split(e["command"])[0]
        std = re.search(r"-std=\S+", e["command"])
        lang = ["-xc++"] if os.path.basename(cc).endswith(("g++", "c++")) else ["-xc"]
        if std:
            lang.append(std.group(0))
        key = (cc, tuple(lang))
        if key not in cache:
            cache[key] = gcc_system_includes(cc, lang)
        rewritten.append(rewrite(e, cache[key]))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "compile_commands.json"), "w") as fh:
        json.dump(rewritten, fh, indent=1)

    # The canary rides on a REAL entry from this pass rather than on a
    # command written here, so that it tests the flags the pass will
    # actually use. A control assembled from what the author believes
    # the flags are certifies the author, not the run.
    if args.canary_src:
        model = dict(rewritten[0])
        argv = [args.canary_src if a == model["file"] else a
                for a in model["arguments"]]
        entry = {"directory": model["directory"],
                 "arguments": argv,
                 "file": args.canary_src,
                 "output": "canary.obj"}
        os.makedirs(args.canary_out, exist_ok=True)
        with open(os.path.join(args.canary_out, "compile_commands.json"), "w") as fh:
            json.dump([entry], fh, indent=1)

    for e in rewritten:
        print(e["file"])


if __name__ == "__main__":
    main()
