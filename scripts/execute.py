#!/usr/bin/env python3
"""
execute.py -- stage 6 of the declutter pipeline.

Apply an approved mapping.tsv to the target directory. This is the only script
in the pipeline that changes anything, and the only thing it ever does is
rename. There is no code path here that unlinks a file or removes a directory,
and the fixture test checks the source text to keep it that way.

    "Buy the ticket, take the ride."
        -- Hunter S. Thompson

mapping.tsv is tab-separated with a header row of exactly these columns:

    action       keep | move | delete | vault
    source       path relative to the target (file, directory, package, or symlink)
    destination  for move: a directory relative to the target root, created if absent;
                 ignored for the other actions
    reason       free text, carried into the log

Rules this script enforces no matter who wrote the mapping:

  * It refuses to run unless <work>/probe.json says the target is readable,
    writable, and allows directory creation by this process.
  * "delete" means: rename into <target>/_Review-Before-Trash/ keeping the same
    relative path. A human empties that folder later, in the Finder, after
    looking at it.
  * "vault" means: rename into <target>/_Vault/ with the relative path flattened
    ("a/b/c.pem" becomes "a__b__c.pem") so nothing collides.
  * It never overwrites. A name collision gets " (2)", " (3)", and so on.
  * It only renames within one filesystem. A cross-device move is an error,
    never a copy followed by a delete.
  * Rows are applied deepest path first, so a child (a venv, a nested secret)
    can be routed somewhere else before its parent folder moves.
  * Sources must stay inside the target. Absolute paths and ".." are rejected
    before anything runs.
  * The default is a dry run. Nothing changes without --apply.

Usage:
    execute.py --work <workdir> [--mapping FILE] [--apply]

Outputs:
    <workdir>/execute.log   every decision, appended
    <workdir>/moves.tsv     source  destination  action  time, one row per rename
"""

import argparse
import csv
import json
import os
import sys
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTIONS = {"keep", "move", "delete", "vault"}

# Where "delete" and "vault" rows actually go. Both live inside the target so
# every rename stays on the same filesystem.
#
#     "Abandon all hope, ye who enter here."
#         -- Dante Alighieri, Inferno, Canto III (the sign over the review folder)
REVIEW = "_Review-Before-Trash"
VAULT = "_Vault"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def uniq(dst):
    """Return dst, or the first "dst (n)" variant that does not already exist.

    lexists is used rather than exists so that a dangling symlink at the
    destination still counts as occupied.
    """
    if not os.path.lexists(dst):
        return dst

    stem, ext = os.path.splitext(dst)
    n = 2
    while os.path.lexists(f"{stem} ({n}){ext}"):
        n += 1

    return f"{stem} ({n}){ext}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mapping", help="default <work>/mapping.tsv")
    ap.add_argument("--apply", action="store_true",
                    help="actually move things (default: dry run)")
    a = ap.parse_args()

    mapping = a.mapping or os.path.join(a.work, "mapping.tsv")

    # -- Gate: the probe must have said the target is usable ---------------
    try:
        probe = json.load(open(os.path.join(a.work, "probe.json")))
    except FileNotFoundError:
        print("ERROR: no probe.json in work dir; run probe.py first", file=sys.stderr)
        return 2

    if not (probe.get("readable") and probe.get("writable") and probe.get("can_create")):
        print("ERROR: probe says the target is not usable:", probe.get("issues"), file=sys.stderr)
        return 2

    T = probe["target"]

    # -- Logs --------------------------------------------------------------
    #
    # execute.log is the narrative; moves.tsv is the reversible record. Both
    # are opened in append mode so a second run adds to the history rather
    # than erasing it.
    log = open(os.path.join(a.work, "execute.log"), "a")
    mv_log = open(os.path.join(a.work, "moves.tsv"), "a")

    if os.path.getsize(os.path.join(a.work, "moves.tsv")) == 0:
        mv_log.write("source\tdestination\taction\ttime\n")

    def out(*s):
        """Print a line and append it to execute.log."""
        line = " ".join(str(x) for x in s)
        print(line)
        log.write(line + "\n")
        log.flush()

    # -- Read and validate the mapping -------------------------------------
    #
    # Every row is checked before any row is applied. A single bad row aborts
    # the whole run with exit 2 and nothing moved.
    rows = []

    with open(mapping, newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")

        need = {"action", "source", "destination", "reason"}
        if not rd.fieldnames or not need.issubset(set(rd.fieldnames)):
            out("ERROR: mapping header must include", sorted(need))
            return 2

        for i, r in enumerate(rd, 2):          # 2 = first data line in the file
            act = (r["action"] or "").strip().lower()
            src = (r["source"] or "").strip().rstrip("/")

            if act not in ACTIONS:
                out(f"ERROR line {i}: unknown action '{act}'")
                return 2

            if not src or src.startswith("/") or ".." in src.split("/"):
                out(f"ERROR line {i}: bad source '{src}'")
                return 2

            rows.append((act, src, (r["destination"] or "").strip().strip("/"), r["reason"] or ""))

    # Deepest paths first, so nested rows run before their parents move out
    # from under them. Ties break alphabetically for a stable log.
    rows.sort(key=lambda r: (-r[1].count("/"), r[1].lower()))

    out(f"=== execute {'APPLY' if a.apply else 'DRY-RUN'} "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} target={T} rows={len(rows)}")

    # -- Apply (or plan) each row ------------------------------------------
    errors = done = 0

    for act, src, dest, reason in rows:
        sp = os.path.join(T, src)

        if not os.path.lexists(sp):
            out("MISSING", src)
            errors += 1
            continue

        if act == "keep":
            out("KEEP", src)
            continue

        # Work out the destination directory for this action.
        if act == "move":
            if not dest:
                out("ERROR move without destination:", src)
                errors += 1
                continue
            ddir = os.path.join(T, dest)
        elif act == "delete":
            ddir = os.path.join(T, REVIEW, os.path.dirname(src))
        else:  # vault
            ddir = os.path.join(T, VAULT)

        # Vaulted files keep their whole relative path in the name so two
        # ".env" files from different folders cannot collide.
        name = src.replace("/", "__") if act == "vault" else os.path.basename(src)
        dst = uniq(os.path.join(ddir, name))

        # Moving a directory into itself would either fail or recurse forever.
        if os.path.realpath(dst).startswith(os.path.realpath(sp) + os.sep):
            out("ERROR destination is inside source:", src, "->", dst)
            errors += 1
            continue

        if a.apply:
            try:
                os.makedirs(ddir, exist_ok=True)
                os.rename(sp, dst)          # the one and only side effect in this file
            except OSError as e:
                out(f"ERROR {act} {src}: {e}")
                errors += 1
                continue

            mv_log.write(f"{src}\t{os.path.relpath(dst, T)}\t{act}\t{time.strftime('%H:%M:%S')}\n")
            mv_log.flush()

        out(act.upper(), src, "->", os.path.relpath(dst, T))
        done += 1

    # -- Report anything the mapping forgot --------------------------------
    #
    # Untouched entries are not an error, but the human should know about
    # them. Category folders created by "move" rows are excluded, as are the
    # review and vault folders themselves.
    mapped = {r[1].split("/")[0] for r in rows}
    left = sorted(
        e for e in os.listdir(T)
        if e not in mapped
        and e not in (REVIEW, VAULT, ".DS_Store")
        and not any(r[0] == "move" and r[2].split("/")[0] == e for r in rows)
    )
    if left:
        out("NOTE top-level entries not mentioned in the mapping (left untouched):", left)

    out(f"DONE {'applied' if a.apply else 'planned'}={done} errors={errors}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
