#!/usr/bin/env python3
"""probe: discover environment constraints for a target directory. Read-only.

Writes <work>/probe.json. Exit 0 when the target is usable, 2 when it is not.
"""
import argparse, json, os, platform, subprocess, sys, time

PKG_EXT = {".app", ".scriv", ".key", ".numbers", ".pages", ".bundle", ".photoslibrary",
           ".xcodeproj", ".playground", ".framework", ".sparsebundle", ".band", ".logicx", ".fcpbundle"}


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target")
    ap.add_argument("--work", required=True, help="working directory for pipeline artifacts")
    a = ap.parse_args()
    t = os.path.abspath(os.path.expanduser(a.target))
    os.makedirs(a.work, exist_ok=True)
    r = {"target": t, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "platform": platform.system(), "issues": []}

    try:
        entries = os.listdir(t)
        r["readable"] = True
    except (PermissionError, FileNotFoundError, NotADirectoryError) as e:
        r["readable"] = False
        r["issues"].append(f"target not readable by this process: {e}. On macOS grant the app Files and Folders access "
                           f"(System Settings > Privacy & Security) or Full Disk Access, then re-run probe.")
        entries = []
    r["writable"] = os.access(t, os.W_OK)
    probe_dir = os.path.join(t, f".declutter-probe-{os.getpid()}")
    try:
        os.mkdir(probe_dir); os.rmdir(probe_dir); r["can_create"] = True
    except Exception as e:
        r["can_create"] = False
        r["issues"].append(f"cannot create directories inside target: {e}")

    home = os.path.expanduser("~")
    r["icloud_synced"] = False
    r["tcc_protected_location"] = None
    if platform.system() == "Darwin":
        prefs = sh(["defaults", "read", "com.apple.finder"])
        desk = "FXICloudDriveDesktop = 1" in prefs
        docs = "FXICloudDriveDocuments = 1" in prefs
        if ((t.startswith(os.path.join(home, "Desktop")) and desk)
                or (t.startswith(os.path.join(home, "Documents")) and docs)
                or "Mobile Documents/com~apple~CloudDocs" in t):
            r["icloud_synced"] = True
            r["issues"].append("target is iCloud-synced: files may be evicted (dataless), directory moves through Finder "
                               "scripting fail, and anything sensitive here is mirrored to iCloud")
        for p in ("Desktop", "Documents", "Downloads"):
            if t == os.path.join(home, p) or t.startswith(os.path.join(home, p) + os.sep):
                r["tcc_protected_location"] = p
        snaps = sh(["tmutil", "listlocalsnapshots", "/"])
        r["local_snapshots"] = [l.strip() for l in snaps.splitlines() if "com.apple" in l]
        r["time_machine_configured"] = "Name" in sh(["tmutil", "destinationinfo"])

    repos, pkgs, links, mounts = [], [], [], []
    for e in entries:
        p = os.path.join(t, e)
        if os.path.islink(p):
            links.append(e); continue
        if os.path.isdir(p):
            if os.path.exists(os.path.join(p, ".git")):
                repos.append(e)
            if os.path.splitext(e)[1].lower() in PKG_EXT:
                pkgs.append(e)
            if os.path.ismount(p):
                mounts.append(e)
    r.update(git_repos=sorted(repos), packages=sorted(pkgs), symlinks=sorted(links), mounts=sorted(mounts),
             entry_count=len(entries))

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
        r["issues"].append(f"{dataless} files are evicted to the cloud (dataless); hashing them forces a download")
    if pkgs:
        r["issues"].append(f"{len(pkgs)} package bundles at top level; treat each as a single item, never recurse into them")

    with open(os.path.join(a.work, "probe.json"), "w") as fh:
        json.dump(r, fh, indent=1)
    print(json.dumps(r, indent=1))
    return 0 if (r["readable"] and r["writable"] and r["can_create"]) else 2


if __name__ == "__main__":
    sys.exit(main())
