#!/usr/bin/env python3
"""
verify.py -- stage 7 of the declutter pipeline.

Prove that nothing was lost. Rescan the target, including the review and vault
folders, and check that every file the survey recorded in manifest.tsv still
exists somewhere: by hash when the survey recorded one, otherwise by size and
basename. Anything unaccounted for is reported and the exit status is 1.

The manifest is the "before" picture and this script is the "after". Between
them sits every rename the executor made, and the whole point is that the two
pictures contain the same files, just in different places.

    "Our lives are defined by opportunities, even the ones we miss."
        -- The Curious Case of Benjamin Button

Usage:
    verify.py --work <workdir> [--show N]

Output:
    <workdir>/verify.json   before_files, hashed_after, missing, missing_sample
"""

import argparse
import collections
import hashlib
import json
import os
import sys


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Must match survey.py. Files inside these directories were never hashed, so
# they are matched by size and name on the way back.
ENV_DIRS = {
    "venv", ".venv", "env", "node_modules", ".terraform", "__pycache__", ".idea",
    ".pytest_cache", "site-packages", ".tox", "build", "dist", ".gradle", ".cache",
    "Pods", "DerivedData", ".mypy_cache",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def md5(p):
    """MD5 hex digest of a file, read in 1 MB chunks. Identity, not security."""
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--show", type=int, default=50, help="how many missing paths to print")
    a = ap.parse_args()

    probe = json.load(open(os.path.join(a.work, "probe.json")))
    T = probe["target"]

    # -- The "before" picture: manifest.tsv --------------------------------
    before = []

    with open(os.path.join(a.work, "manifest.tsv")) as fh:
        next(fh)                                 # header row
        for line in fh:
            h, size, mtime, flags, path = line.rstrip("\n").split("\t", 4)
            before.append((h, int(size), flags, path))

    # -- The "after" picture: rescan the target ----------------------------
    #
    # Two multisets are built. by_hash counts every hashable file by content;
    # by_sizename counts every file by (size, basename) as the fallback for
    # rows the survey could not hash. Counters, not sets, so that three
    # identical files before must still be three identical files after.
    by_hash = collections.Counter()
    by_sizename = collections.Counter()
    hashed_after = 0

    work_abs = os.path.abspath(a.work)

    for root, dirs, files in os.walk(T):
        dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) != work_abs]

        in_git = ".git" in os.path.relpath(root, T).split(os.sep)
        in_env = any(p in ENV_DIRS for p in os.path.relpath(root, T).split(os.sep))

        for f in files:
            if f == ".DS_Store":
                continue

            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue

            by_sizename[(st.st_size, f)] += 1

            # Same hashing rules as the survey, with the same 500 MB ceiling.
            if not (in_git or in_env or os.path.islink(p)) and st.st_size <= 500 * 1024 * 1024:
                try:
                    by_hash[md5(p)] += 1
                    hashed_after += 1
                except OSError:
                    pass

    # -- Reconcile ---------------------------------------------------------
    #
    # Each "before" row consumes one matching "after" entry. A row that finds
    # nothing to consume is missing.
    missing = []

    for h, size, flags, path in before:
        key = (size, os.path.basename(path))

        if h != "-" and by_hash[h] > 0:
            by_hash[h] -= 1
        elif by_sizename[key] > 0:
            by_sizename[key] -= 1
        else:
            missing.append(path)

    # -- Report ------------------------------------------------------------
    report = {
        "target": T,
        "before_files": len(before),
        "hashed_after": hashed_after,
        "missing": len(missing),
        "missing_sample": missing[:a.show],
    }

    json.dump(report, open(os.path.join(a.work, "verify.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
