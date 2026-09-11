#!/usr/bin/env python3
"""survey: read-only inventory of a target directory.

Writes into <work>/:
  manifest.tsv    hash  size  mtime  flags  relpath      (every file; hash '-' when skipped)
  toplevel.tsv    one row per top-level entry with counts, dates, git state, env bloat
  duplicates.tsv  groups of byte-identical files
  bloat.tsv       dependency/build directories and their sizes
  secrets.tsv     files that look like credentials (by name or content); values are never printed
  summary.json    totals and histograms
"""
import argparse, collections, hashlib, json, os, re, subprocess, sys, time

ENV_DIRS = {"venv", ".venv", "env", "node_modules", ".terraform", "__pycache__", ".idea", ".pytest_cache",
            "site-packages", ".tox", "build", "dist", ".gradle", ".cache", "Pods", "DerivedData", ".mypy_cache"}
SECRET_NAME = re.compile(r"(^\.env$|^\.env\.|\.pem$|\.key$|\.asc$|\.gpg$|_rsa$|id_ed25519|creds|credential|secret|"
                         r"token|apikey|api_key|passw|\.p12$|\.pfx$|backup.?codes|recovery|\.kdbx$|\.ovpn$)", re.I)
SECRET_CONTENT = re.compile(rb"(BEGIN (RSA|PGP|OPENSSH|EC|DSA) PRIVATE KEY|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|"
                            rb"ghp_[0-9A-Za-z]{30,}|sk-[0-9A-Za-z]{20,}|consumer_secret\s*=|access_token_secret\s*=|"
                            rb"BEGIN PGP MESSAGE)")


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_info(p):
    def g(*args):
        try:
            return subprocess.run(["git", "-C", p, *args], capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            return ""
    remote = g("remote", "get-url", "origin") or "(no remote)"
    last = g("log", "-1", "--format=%cs") or "-"
    dirty = len(g("status", "--porcelain").splitlines())
    ahead = g("rev-list", "--count", "@{u}..HEAD") or "?"
    return remote, last, dirty, ahead


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--work", required=True)
    ap.add_argument("--hash-max-mb", type=int, default=500, help="skip hashing files larger than this (default 500)")
    ap.add_argument("--no-hash-envs", action="store_true", default=True,
                    help="do not hash files inside dependency dirs or .git (default on)")
    a = ap.parse_args()
    t = os.path.abspath(os.path.expanduser(a.target))
    os.makedirs(a.work, exist_ok=True)
    W = lambda name: open(os.path.join(a.work, name), "w")

    manifest, by_hash, bloat, secrets = [], collections.defaultdict(list), [], []
    ext_hist, year_hist = collections.Counter(), collections.Counter()
    total_bytes = 0
    top_stats = {}
    work_abs = os.path.abspath(a.work)
    for root, dirs, files in os.walk(t):
        dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) != work_abs]
        rel_root = os.path.relpath(root, t)
        top = rel_root.split(os.sep)[0] if rel_root != "." else None
        in_git = ".git" in rel_root.split(os.sep)
        # dependency dirs: record size, do not descend for hashing purposes
        for d in list(dirs):
            if d in ENV_DIRS:
                p = os.path.join(root, d)
                sz = n = 0
                for r2, _, f2 in os.walk(p):
                    for f in f2:
                        try:
                            sz += os.lstat(os.path.join(r2, f)).st_size; n += 1
                        except OSError:
                            pass
                bloat.append((sz, n, os.path.relpath(p, t)))
                if top:
                    top_stats.setdefault(top, {}).setdefault("env_bytes", 0)
                    top_stats[top]["env_bytes"] += sz
        in_env = any(part in ENV_DIRS for part in rel_root.split(os.sep))
        for f in files:
            if f == ".DS_Store":
                continue
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            rel = os.path.relpath(p, t)
            flags = []
            if in_git: flags.append("git")
            if in_env: flags.append("env")
            if os.path.islink(p): flags.append("link")
            h = "-"
            skip_hash = in_git or in_env or os.path.islink(p) or st.st_size > a.hash_max_mb * 1024 * 1024
            if not skip_hash:
                try:
                    h = md5(p)
                except OSError:
                    h = "-"
            mtime = time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))
            manifest.append((h, st.st_size, mtime, ",".join(flags) or "-", rel))
            if not (in_git or in_env):
                total_bytes += st.st_size
                ext_hist[os.path.splitext(f)[1].lower() or "(none)"] += 1
                year_hist[mtime[:4]] += 1
                if h != "-" and st.st_size > 0:
                    by_hash[h].append(rel)
                why = []
                if SECRET_NAME.search(f):
                    why.append("name")
                if st.st_size < 1_000_000 and not os.path.islink(p):
                    try:
                        with open(p, "rb") as fh:
                            if SECRET_CONTENT.search(fh.read()):
                                why.append("content")
                    except OSError:
                        pass
                if why:
                    secrets.append((rel, "+".join(why), st.st_size))
            if top:
                s = top_stats.setdefault(top, {})
                s["files"] = s.get("files", 0) + 1
                s["bytes"] = s.get("bytes", 0) + st.st_size
                s["newest"] = max(s.get("newest", "0000"), mtime)
                s["oldest"] = min(s.get("oldest", "9999"), mtime)

    manifest.sort(key=lambda r: r[4])
    with W("manifest.tsv") as fh:
        fh.write("hash\tsize\tmtime\tflags\tpath\n")
        for r in manifest:
            fh.write("\t".join(map(str, r)) + "\n")

    with W("toplevel.tsv") as fh:
        fh.write("entry\tkind\tfiles\tbytes\tenv_bytes\toldest\tnewest\tgit_remote\tgit_last_commit\tgit_dirty\tgit_ahead\n")
        for e in sorted(os.listdir(t), key=str.lower):
            if e == ".DS_Store" or os.path.abspath(os.path.join(t, e)) == work_abs:
                continue
            p = os.path.join(t, e)
            s = top_stats.get(e, {})
            if os.path.islink(p):
                kind = "link"
            elif os.path.isdir(p):
                kind = "git" if os.path.exists(os.path.join(p, ".git")) else "dir"
            else:
                kind = "file"
                try:
                    st = os.lstat(p)
                    s = {"files": 1, "bytes": st.st_size,
                         "oldest": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                         "newest": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))}
                except OSError:
                    pass
            gi = git_info(p) if kind == "git" else ("-", "-", "-", "-")
            fh.write("\t".join(map(str, [e, kind, s.get("files", 0), s.get("bytes", 0), s.get("env_bytes", 0),
                                          s.get("oldest", "-"), s.get("newest", "-"), *gi])) + "\n")

    dup_groups = [(k, v) for k, v in by_hash.items() if len(v) > 1]
    with W("duplicates.tsv") as fh:
        fh.write("hash\tcount\tpaths\n")
        for k, v in sorted(dup_groups, key=lambda kv: -len(kv[1])):
            fh.write(f"{k}\t{len(v)}\t" + " | ".join(sorted(v)) + "\n")
    with W("bloat.tsv") as fh:
        fh.write("bytes\tfiles\tpath\n")
        for sz, n, p in sorted(bloat, reverse=True):
            fh.write(f"{sz}\t{n}\t{p}\n")
    with W("secrets.tsv") as fh:
        fh.write("path\tmatched_by\tsize\n")
        for r in secrets:
            fh.write("\t".join(map(str, r)) + "\n")
    summary = {"target": t, "surveyed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "files": len(manifest), "bytes_excluding_env_and_git": total_bytes,
               "top_level_entries": len([e for e in os.listdir(t) if e != ".DS_Store"]),
               "duplicate_groups": len(dup_groups), "duplicate_extra_files": sum(len(v) - 1 for _, v in dup_groups),
               "env_bytes": sum(b[0] for b in bloat), "secret_candidates": len(secrets),
               "extensions_top": ext_hist.most_common(20), "years": sorted(year_hist.items())}
    with W("summary.json") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
