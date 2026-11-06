#!/usr/bin/env bash
# Copy the AFE contractor material into a destination folder.
#
#   tools/afe_export_contractor.sh DEST [--force] [--dry-run]
#
# What is sent is the list in docs/afe/contractor-inventory.txt, nothing
# else. Before copying, the written documents in that list under docs/ are
# scanned for wording that only makes sense inside this repository (our
# requirement IDs, paths, bench names). A hit stops the export and nothing
# is copied.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INVENTORY="$ROOT/docs/afe/contractor-inventory.txt"

# Internal-only wording. Plain words such as "bench test" are allowed.
LEAK='\b(SC|DF|AW|PR|PW|P2|CA|EN|MC|VT|AN)-[0-9]+\b|docs/|\.\./|\.py\b|\.jsonl?\b|issue[ ]*#?[0-9]+|#[0-9]{2,}|windows-desk|mac-bench|linux-x1|\bTrack[ ]+[ABC]\b|DS\.Projects|CLAUDE'

dest= force=0 dry=0
for a in "$@"; do
    case "$a" in
        --force) force=1 ;;
        --dry-run) dry=1 ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
        -*) echo "unknown option: $a" >&2; exit 2 ;;
        *) [ -z "$dest" ] || { echo "one destination only" >&2; exit 2; }
           dest=$a ;;
    esac
done
[ -n "$dest" ] || { echo "usage: $0 DEST [--force] [--dry-run]" >&2; exit 2; }
[ -f "$INVENTORY" ] || { echo "missing $INVENTORY" >&2; exit 1; }

# Expand the inventory into a list of files.
files=()
while IFS= read -r line; do
    line=${line%%#*}
    line=$(echo "$line" | xargs)          # trim
    [ -n "$line" ] || continue
    src="$ROOT/$line"
    if [ -d "$src" ]; then
        while IFS= read -r f; do files+=("${f#"$ROOT"/}"); done \
            < <(find "$src" -type f | LC_ALL=C sort)
    elif [ -f "$src" ]; then
        files+=("$line")
    else
        echo "missing source: $line" >&2; exit 1
    fi
done < "$INVENTORY"
[ "${#files[@]}" -gt 0 ] || { echo "inventory is empty" >&2; exit 1; }

# Leak scan of the written documents.
bad=0
for f in "${files[@]}"; do
    case "$f" in docs/*)
        if hits=$(grep -n -E -i "$LEAK" "$ROOT/$f"); then
            [ "$bad" = 1 ] || echo "internal wording in the documents; nothing copied:" >&2
            bad=1
            echo "$hits" | sed "s|^|  $f:|" >&2
        fi ;;
    esac
done
[ "$bad" = 0 ] || exit 1

dest=$(realpath -m "$dest")
case "$dest/" in "$ROOT"/*) echo "destination must be outside the repository" >&2; exit 1 ;; esac
if [ "$force" = 0 ] && [ -d "$dest" ] && [ -n "$(ls -A "$dest")" ]; then
    echo "$dest is not empty; use --force to copy into it" >&2; exit 1
fi
[ "$dry" = 1 ] || mkdir -p "$dest"

bytes=0
for f in "${files[@]}"; do
    bytes=$((bytes + $(stat -c %s "$ROOT/$f")))
    if [ "$dry" = 1 ]; then echo "$f"; continue; fi
    mkdir -p "$dest/$(dirname "$f")"
    cp -p "$ROOT/$f" "$dest/$f"
    cmp -s "$ROOT/$f" "$dest/$f" || { echo "copy differs from source: $f" >&2; exit 1; }
done

if [ "$dry" = 1 ]; then
    echo "would copy ${#files[@]} files, $((bytes / 1000)) kB"
else
    echo "copied ${#files[@]} files, $((bytes / 1000)) kB to $dest"
fi
