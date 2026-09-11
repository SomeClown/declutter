# File formats

All pipeline artifacts live in one work directory, by default `<target>/_declutter/`. They are plain
TSV or JSON so they can be opened in a spreadsheet or diffed.

## probe.json  (probe.py)
Environment facts about the target: `readable`, `writable`, `can_create`, `icloud_synced`,
`tcc_protected_location`, `git_repos`, `packages`, `symlinks`, `mounts`, `file_count`, `dataless_files`,
`local_snapshots`, `time_machine_configured`, and a human-readable `issues` list.

## manifest.tsv  (survey.py)
    hash    size    mtime    flags    path
One row per file. `hash` is `-` for files inside `.git`, inside dependency directories, symlinks, or
files above `--hash-max-mb`. `flags` is a comma list from `git`, `env`, `link`, or `-`.

## toplevel.tsv  (survey.py)
One row per top-level entry: kind (`file`, `dir`, `git`, `link`), file count, bytes, bytes inside
dependency dirs, oldest and newest mtime, and for git repos the remote, last commit date, dirty count,
and unpushed count. This is the planner's main input.

## duplicates.tsv, bloat.tsv, secrets.tsv  (survey.py)
Byte-identical groups; dependency and build directories with sizes; files whose name or content looks
like a credential (matched-by `name`, `content`, or both). Secret values are never written anywhere.

## taxonomy.md  (planner)
The proposed category set for this folder with one line of rationale each, written before the mapping
so the human can confirm or rename categories first.

## mapping.tsv  (planner writes, human edits, execute.py runs)
    action    source    destination    reason
* `action`: `keep`, `move`, `delete`, `vault`
* `source`: path relative to the target as it exists **before** execution
* `destination`: for `move`, a directory relative to the target root; created if absent
* `reason`: why, in a few words; carried into the log

Rows are applied deepest path first, so `Spork/venv  delete` and `Spork  move  archive/` can coexist:
the venv goes to the review folder before Spork moves.

## moves.tsv, execute.log  (execute.py)
Every rename as `source  destination  action  time`. Reverse a move by renaming the destination back.

## verify.json  (verify.py)
`before_files`, `missing`, and a sample of missing paths. `missing` must be 0.
