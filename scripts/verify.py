#!/usr/bin/env python3
"""verify: prove nothing was lost. Rescans the target (including the review and vault folders) and checks that
every file recorded in <work>/manifest.tsv still exists somewhere, by hash when one was recorded, otherwise by
size and basename. Exit 1 if anything is unaccounted for.
"""
import argparse, collections, hashlib, json, os, sys

ENV_DIRS = {"venv", ".venv", "env", "node_modules", ".terraform", "__pycache__", ".idea", ".pytest_cache",
            "site-packages", ".tox", "build", "dist", ".gradle", ".cache", "Pods", "DerivedData", ".mypy_cache"}


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    ap.add_argument("--show", type=int, default=50, help="how many missing paths to print")
    a = ap.parse_args()
    probe = json.load(open(os.path.join(a.work, "probe.json")))
    T = probe["target"]
    before = []
    with open(os.path.join(a.work, "manifest.tsv")) as fh:
        next(fh)
        for line in fh:
            h, size, mtime, flags, path = line.rstrip("\n").split("\t", 4)
            before.append((h, int(size), flags, path))

    by_hash, by_sizename, sizes_seen = collections.Counter(), collections.Counter(), 0
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
            if not (in_git or in_env or os.path.islink(p)) and st.st_size <= 500 * 1024 * 1024:
                try:
                    by_hash[md5(p)] += 1; hashed_after += 1
                except OSError:
                    pass

    missing = []
    for h, size, flags, path in before:
        key = (size, os.path.basename(path))
        if h != "-" and by_hash[h] > 0:
            by_hash[h] -= 1
        elif by_sizename[key] > 0:
            by_sizename[key] -= 1
        else:
            missing.append(path)
    report = {"target": T, "before_files": len(before), "hashed_after": hashed_after, "missing": len(missing),
              "missing_sample": missing[:a.show]}
    json.dump(report, open(os.path.join(a.work, "verify.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
