# declutter

A safety-first folder cleanup pipeline for Claude Code.

Point it at a messy folder. It probes the environment, inventories everything with hashes, proposes a
category set for *that* folder, writes a plain TSV plan you edit and approve, executes the plan with
logged renames only, and then proves by manifest that nothing was lost. It never deletes: "delete"
means "stage in a review folder for you to empty."

## Pipeline

| Stage | Component | Changes anything? |
|---|---|---|
| 1. Probe | `scripts/probe.py` | No |
| 2. Survey | `scripts/survey.py` | No |
| 3. Taxonomy | `agents/planner.md` | No (writes `taxonomy.md`) |
| 4. Plan | `agents/planner.md` | No (writes `mapping.tsv`) |
| 5. Review | you, editing `mapping.tsv` | No |
| 6. Execute | `scripts/execute.py --apply` | Renames only |
| 7. Verify | `scripts/verify.py` | No |
| 8. Report | the driving skill | No |

Judgment lives in the agent. Side effects live in scripts with fixed invariants. See `docs/SAFETY.md`.

## Install

    /plugin marketplace add SomeClown/declutter
    /plugin install declutter

Or from a local checkout: `/plugin marketplace add /path/to/declutter`.

## Use

    /declutter ~/Downloads

The skill walks the eight stages and stops for you twice: once to confirm the category set, once to
approve the plan. Everything it writes goes to `<target>/_declutter/`.

## Scripts standalone

    python3 scripts/probe.py   ~/Downloads --work ~/Downloads/_declutter
    python3 scripts/survey.py  ~/Downloads --work ~/Downloads/_declutter
    # write or edit _declutter/mapping.tsv
    python3 scripts/execute.py --work ~/Downloads/_declutter            # dry run
    python3 scripts/execute.py --work ~/Downloads/_declutter --apply
    python3 scripts/verify.py  --work ~/Downloads/_declutter

Python 3.9+, standard library only. `python3 tests/test_pipeline.py` runs the fixture test.

## Known limits

* macOS restricts Desktop, Documents, and Downloads to apps you have granted Files and Folders access.
  The probe detects this and stops; grant access and re-run.
* iCloud-synced folders may contain evicted files. Hashing downloads them. The probe warns.
* Package bundles are single items. Symlinks are moved as links, never followed.

## License

MIT
