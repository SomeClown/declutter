---
name: declutter
description: Use when the user wants to clean up, organize, tidy, declutter, or reorganize a folder such as Downloads, Desktop, Documents, or a code directory. Runs the declutter pipeline: probe the environment, survey with hashes, propose a per-folder taxonomy for confirmation, write a TSV plan for approval, execute with logged renames only, verify by manifest, and report. Never deletes anything; deletions are staged in a review folder the user empties.
---

# declutter

**What this owns.** The end-to-end cleanup of one target folder, with two human gates and no destructive
step. Judgment is delegated to the `planner` agent; every side effect goes through `scripts/execute.py`,
which enforces the invariants in `docs/SAFETY.md` no matter what the plan says.

`$PLUGIN` below means this plugin's root directory. `$WORK` is `<target>/_declutter` unless the user
names another location.

## Stage 1: probe (read-only)

    python3 $PLUGIN/scripts/probe.py <target> --work $WORK

Read `probe.json`. If `readable`, `writable`, or `can_create` is false, **stop** and tell the user
exactly what to grant or change, quoting the `issues` list. On macOS the usual cause is Files and Folders
access for Desktop, Documents, or Downloads; the user grants it in System Settings and you re-run probe.
Do not work around a blocked target through Finder scripting or any other bridge.

Relay any other issues (iCloud sync, dataless files, package bundles) before continuing.

## Stage 2: survey (read-only)

    python3 $PLUGIN/scripts/survey.py <target> --work $WORK

Large or cloud-evicted folders take minutes; run it in the background and wait for it. Summarize
`summary.json` for the user in a short table: entries, files, size, duplicate groups, dependency bloat,
secret candidates, date range. If `secrets.tsv` is non-empty, say so now.

## Stage 3: taxonomy (planner, mode 1)

Spawn the `planner` agent with the work directory and the instruction to run in taxonomy mode. Show the
user `taxonomy.md` and wait for confirmation or edits. Do not proceed on silence.

## Stage 4: plan (planner, mode 2)

Continue the same planner with the confirmed taxonomy in mapping mode. It writes `mapping.tsv`.
Run a dry run so the user sees exactly what would happen:

    python3 $PLUGIN/scripts/execute.py --work $WORK

Send the user `mapping.tsv` (with SendUserFile when available) and the dry-run counts by action. Call out
the rows the planner was least sure about and every `vault` row.

## Stage 5: review (human)

The user edits `mapping.tsv` or says go. **A plain go-ahead in chat approves the file as it is on disk.**
If they change it, re-run the dry run before applying.

## Stage 6: execute

    python3 $PLUGIN/scripts/execute.py --work $WORK --apply

Read `execute.log`. Any `ERROR`, `MISSING`, or `WARN` line is reported verbatim (a `WARN` on a directory
move means the destination repeats the folder's own name; fix the row before applying). Never re-run with hand edits to
the script; fix the mapping and re-apply the remaining rows.

## Stage 7: verify

    python3 $PLUGIN/scripts/verify.py --work $WORK

`missing` must be 0. If it is not, stop, report the missing paths, and check `moves.tsv` for where they
went before anything else happens.

## Stage 8: report

Lead with the outcome, then a table of the new layout with sizes, then what is staged in
`_Review-Before-Trash/` and `_Vault/`, then the user's follow-ups: empty the review folder, move vaulted
credentials into a password manager and revoke exposed ones, anything the planner flagged. Point to
`$WORK` for the manifest, plan, and move log, and note that any move can be reversed from `moves.tsv`.

## Rules

- Never delete, `rm`, `rmdir`, or Trash anything, even on request; stage it and let the user empty the folder.
- Never enter, print, or move credential *values*; move the files into the vault and name them.
- Never bypass a probe failure.
- Prefer boring: if something needs a one-off script, it needs a mapping row instead.
