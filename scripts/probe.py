#!/usr/bin/env python3
"""
probe.py -- stage 1 of the declutter pipeline.

Look at a target directory and write down everything about the ENVIRONMENT that
would change how the later stages behave: can this process even read the folder,
can it write there, is the folder cloud-synced, are there git repos, package
bundles, symlinks, mounted volumes, or cloud-evicted files inside it.

This script is strictly read-only. The one thing it creates is a throwaway
directory used to test whether directory creation works, and it removes that
immediately.

    "A paranoid is someone who knows a little of what's going on."
        -- William S. Burroughs

Usage:
    probe.py <target> --work <workdir>

Output:
    <workdir>/probe.json

Exit status:
    0  the target is readable, writable, and allows directory creation
    2  something about the target makes the pipeline unsafe to run
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directory extensions that macOS presents as a single "file" (a package or
# bundle). The rest of the pipeline treats these as one opaque item and never
# routes anything inside them. Splitting a package apart usually breaks the
# application that owns it.
PKG_EXT = {
    ".app", ".scriv", ".key", ".numbers", ".pages", ".bundle", ".photoslibrary",
    ".xcodeproj", ".playground", ".framework", ".sparsebundle", ".band",
    ".logicx", ".fcpbundle",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sh(cmd):
    """Run a command and return its stdout as text.

    Any failure (missing binary, timeout, non-zero exit) returns an empty string
    instead of raising, because every caller treats the output as optional
    evidence, not as a requirement.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--work", required=True, help="working directory for pipeline artifacts")
    a = ap.parse_args()

    t = os.path.abspath(os.path.expanduser(a.target))
    os.makedirs(a.work, exist_ok=True)

    # The report we will write. "issues" is the human-readable list the skill
    # relays to the user before deciding whether to continue.
    r = {
        "target": t,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform": platform.system(),
        "issues": [],
    }

    # -- Can we read it? ---------------------------------------------------
    #
    # On macOS, Desktop, Documents, and Downloads are guarded by the privacy
    # system (TCC). A process without a grant gets "Operation not permitted"
    # on listdir. The grant has to go to whatever bundle macOS holds
    # *responsible* for this process, which for Claude Code launched from the
    # Claude desktop app is a separate helper bundle, not the app itself.
    # That distinction cost real time once, hence the very specific message.
    try:
        entries = os.listdir(t)
        r["readable"] = True
    except (PermissionError, FileNotFoundError, NotADirectoryError) as e:
        r["readable"] = False
        r["issues"].append(
            f"target not readable by this process: {e}. On macOS this is a Files and Folders "
            f"(privacy) block. The grant must go to the process macOS holds responsible, which for "
            f"Claude Code inside the Claude desktop app is the 'Claude Code' helper "
            f"(com.anthropic.claude-code), not 'Claude'. Enable the folder under that row in "
            f"System Settings > Privacy & Security > Files and Folders, or clear a remembered "
            f"denial so the prompt reappears: tccutil reset SystemPolicy<Folder>Folder "
            f"com.anthropic.claude-code. Then re-run probe."
        )
        entries = []

    # -- Can we write to it, and create directories in it? -----------------
    #
    # os.access answers the permission-bits question. The mkdir/rmdir pair
    # answers the real question, because privacy protection can allow one
    # and deny the other.
    r["writable"] = os.access(t, os.W_OK)

    probe_dir = os.path.join(t, f".declutter-probe-{os.getpid()}")
    try:
        os.mkdir(probe_dir)
        os.rmdir(probe_dir)
        r["can_create"] = True
    except Exception as e:
        r["can_create"] = False
        r["issues"].append(f"cannot create directories inside target: {e}")

    # -- macOS specifics: iCloud sync, protected locations, backups --------
    home = os.path.expanduser("~")
    r["icloud_synced"] = False
    r["tcc_protected_location"] = None

    if platform.system() == "Darwin":
        # Finder's preferences record whether "Desktop & Documents Folders"
        # sync is switched on. If it is, files here can be evicted to the
        # cloud (present in the listing, absent on disk) and anything
        # sensitive is being mirrored off the machine.
        prefs = sh(["defaults", "read", "com.apple.finder"])
        desk = "FXICloudDriveDesktop = 1" in prefs
        docs = "FXICloudDriveDocuments = 1" in prefs

        if ((t.startswith(os.path.join(home, "Desktop")) and desk)
                or (t.startswith(os.path.join(home, "Documents")) and docs)
                or "Mobile Documents/com~apple~CloudDocs" in t):
            r["icloud_synced"] = True
            r["issues"].append(
                "target is iCloud-synced: files may be evicted (dataless), directory moves through "
                "Finder scripting fail, and anything sensitive here is mirrored to iCloud"
            )

        # Record which protected location we are in, if any, so the skill
        # can name it in its advice.
        for p in ("Desktop", "Documents", "Downloads"):
            if t == os.path.join(home, p) or t.startswith(os.path.join(home, p) + os.sep):
                r["tcc_protected_location"] = p

        # Backups are the only thing that can undo a mistake the pipeline's
        # own invariants do not catch, so note whether any exist.
        snaps = sh(["tmutil", "listlocalsnapshots", "/"])
        r["local_snapshots"] = [l.strip() for l in snaps.splitlines() if "com.apple" in l]
        r["time_machine_configured"] = "Name" in sh(["tmutil", "destinationinfo"])

    # -- Classify the top-level entries ------------------------------------
    #
    # Git repos get special handling by the planner (never delete unpushed
    # work). Packages are opaque. Symlinks are moved as links, never
    # followed. Mount points are somebody else's disk.
    repos, pkgs, links, mounts = [], [], [], []

    for e in entries:
        p = os.path.join(t, e)

        if os.path.islink(p):
            links.append(e)
            continue

        if os.path.isdir(p):
            if os.path.exists(os.path.join(p, ".git")):
                repos.append(e)
            if os.path.splitext(e)[1].lower() in PKG_EXT:
                pkgs.append(e)
            if os.path.ismount(p):
                mounts.append(e)

    r.update(
        git_repos=sorted(repos),
        packages=sorted(pkgs),
        symlinks=sorted(links),
        mounts=sorted(mounts),
        entry_count=len(entries),
    )

    # -- Count files and detect cloud-evicted ones -------------------------
    #
    # An evicted ("dataless") file reports its full size but occupies zero
    # blocks on disk. Hashing it forces a download, which the survey stage
    # needs to warn about before it starts.
    #
    #     "When the going gets weird, the weird turn pro."
    #         -- Hunter S. Thompson
    total = dataless = 0

    for root, dirs, files in os.walk(t):
        dirs[:] = [d for d in dirs if d != ".git"]

        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue

            total += 1
            if st.st_size > 0 and getattr(st, "st_blocks", 1) == 0:
                dataless += 1

    r["file_count"] = total
    r["dataless_files"] = dataless

    if dataless:
        r["issues"].append(
            f"{dataless} files are evicted to the cloud (dataless); hashing them forces a download"
        )
    if pkgs:
        r["issues"].append(
            f"{len(pkgs)} package bundles at top level; treat each as a single item, never recurse into them"
        )

    # -- Write the report --------------------------------------------------
    with open(os.path.join(a.work, "probe.json"), "w") as fh:
        json.dump(r, fh, indent=1)

    print(json.dumps(r, indent=1))

    # The executor re-checks these three flags before it will move anything.
    return 0 if (r["readable"] and r["writable"] and r["can_create"]) else 2


if __name__ == "__main__":
    sys.exit(main())
