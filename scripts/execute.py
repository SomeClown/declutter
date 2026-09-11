#!/usr/bin/env python3
"""execute: apply an approved mapping.tsv to the target. Moves only. Nothing is ever unlinked.

mapping.tsv columns (tab-separated, header required): action  source  destination  reason
  action       keep | move | delete | vault
  source       path relative to the target (file, directory, package, or symlink)
  destination  for move: directory relative to the target root, created if absent; ignored otherwise
  reason       free text, kept in the log

Rules this script enforces regardless of who wrote the mapping:
  * refuses to run unless <work>/probe.json says the target is readable, writable, and can create dirs
  * 'delete' moves the item to <target>/_Review-Before-Trash/<same relative path>; a human empties that folder
  * 'vault'  moves the item to <target>/_Vault/<relative path with '/' replaced by '__'>
  * never overwrites: a name collision gets ' (2)', ' (3)', ...
  * same-filesystem rename only; a cross-device move is reported as an error, never copied-and-deleted
  * rows are applied deepest-path-first, so a child (e.g. a venv) can be routed before its parent moves
  * sources must stay inside the target; '..' and absolute paths are rejected
  * default is a dry run; pass --apply to change anything
Outputs: <work>/moves.tsv (source, destination, action, time) and <work>/execute.log
"""
import argparse, csv, json, os, sys, time

ACTIONS = {"keep", "move", "delete", "vault"}
REVIEW = "_Review-Before-Trash"
VAULT = "_Vault"


def uniq(dst):
    if not os.path.lexists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    n = 2
    while os.path.lexists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mapping", help="default <work>/mapping.tsv")
    ap.add_argument("--apply", action="store_true", help="actually move things (default: dry run)")
    a = ap.parse_args()
    mapping = a.mapping or os.path.join(a.work, "mapping.tsv")
    try:
        probe = json.load(open(os.path.join(a.work, "probe.json")))
    except FileNotFoundError:
        print("ERROR: no probe.json in work dir; run probe.py first", file=sys.stderr); return 2
    if not (probe.get("readable") and probe.get("writable") and probe.get("can_create")):
        print("ERROR: probe says the target is not usable:", probe.get("issues"), file=sys.stderr); return 2
    T = probe["target"]
    log = open(os.path.join(a.work, "execute.log"), "a")
    mv_log = open(os.path.join(a.work, "moves.tsv"), "a")
    if os.path.getsize(os.path.join(a.work, "moves.tsv")) == 0:
        mv_log.write("source\tdestination\taction\ttime\n")

    def out(*s):
        line = " ".join(str(x) for x in s)
        print(line); log.write(line + "\n"); log.flush()

    rows = []
    with open(mapping, newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        need = {"action", "source", "destination", "reason"}
        if not rd.fieldnames or not need.issubset(set(rd.fieldnames)):
            out("ERROR: mapping header must include", sorted(need)); return 2
        for i, r in enumerate(rd, 2):
            act = (r["action"] or "").strip().lower(); src = (r["source"] or "").strip().rstrip("/")
            if act not in ACTIONS:
                out(f"ERROR line {i}: unknown action '{act}'"); return 2
            if not src or src.startswith("/") or ".." in src.split("/"):
                out(f"ERROR line {i}: bad source '{src}'"); return 2
            rows.append((act, src, (r["destination"] or "").strip().strip("/"), r["reason"] or ""))
    rows.sort(key=lambda r: (-r[1].count("/"), r[1].lower()))
    out(f"=== execute {'APPLY' if a.apply else 'DRY-RUN'} {time.strftime('%Y-%m-%d %H:%M:%S')} target={T} rows={len(rows)}")

    errors = done = 0
    for act, src, dest, reason in rows:
        sp = os.path.join(T, src)
        if not os.path.lexists(sp):
            out("MISSING", src); errors += 1; continue
        if act == "keep":
            out("KEEP", src); continue
        if act == "move":
            if not dest:
                out("ERROR move without destination:", src); errors += 1; continue
            ddir = os.path.join(T, dest)
        elif act == "delete":
            ddir = os.path.join(T, REVIEW, os.path.dirname(src))
        else:
            ddir = os.path.join(T, VAULT)
        name = src.replace("/", "__") if act == "vault" else os.path.basename(src)
        dst = uniq(os.path.join(ddir, name))
        if os.path.realpath(dst).startswith(os.path.realpath(sp) + os.sep):
            out("ERROR destination is inside source:", src, "->", dst); errors += 1; continue
        if a.apply:
            try:
                os.makedirs(ddir, exist_ok=True)
                os.rename(sp, dst)
            except OSError as e:
                out(f"ERROR {act} {src}: {e}"); errors += 1; continue
            mv_log.write(f"{src}\t{os.path.relpath(dst, T)}\t{act}\t{time.strftime('%H:%M:%S')}\n"); mv_log.flush()
        out(act.upper(), src, "->", os.path.relpath(dst, T)); done += 1

    mapped = {r[1].split("/")[0] for r in rows}
    left = sorted(e for e in os.listdir(T) if e not in mapped and e not in (REVIEW, VAULT, ".DS_Store")
                  and not any(r[0] == "move" and r[2].split("/")[0] == e for r in rows))
    if left:
        out("NOTE top-level entries not mentioned in the mapping (left untouched):", left)
    out(f"DONE {'applied' if a.apply else 'planned'}={done} errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
