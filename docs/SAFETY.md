# Safety model

declutter exists because folder cleanups go wrong in one specific way: a script or an agent decides a
directory is empty, or redundant, or "already handled", and removes it. The pipeline is built so that
decision can never turn into data loss.

## Invariants the scripts enforce

1. **Nothing is unlinked.** `execute.py` has no code path that calls `unlink`, `rmdir`, `rmtree`, or a
   shell `rm`. "delete" means "rename into `_Review-Before-Trash/` preserving the relative path". A
   person empties that folder, in the Finder, after looking at it.
2. **Same-filesystem renames only.** A cross-device move is reported as an error. The script never
   copies and then removes the original.
3. **Never overwrite.** A destination that already exists gets a ` (2)` suffix.
4. **Sources stay inside the target.** Absolute paths and `..` segments are rejected before anything runs.
5. **Dry run by default.** `--apply` is required to change anything.
6. **Refuse an unusable target.** `execute.py` will not run unless `probe.json` says the target is
   readable, writable, and allows directory creation by this process. On macOS that catches the
   Files-and-Folders permission block on Desktop, Documents, and Downloads before any half-finished run.
7. **A manifest exists before the first move** and `verify.py` proves every file in it still exists
   afterwards, by hash where one was recorded.
8. **Credentials never go to an archive.** Anything the survey flags as a secret defaults to the `vault`
   action, which stages it in `_Vault/` for the human to move into a password manager and then delete.

## Invariants the skill enforces on the agent

* The planner only writes `taxonomy.md` and `mapping.tsv`. It has no tool that can move or delete.
* The plan is a file the human edits and approves. The executor runs the file, not the conversation.
* Rows for things the planner cannot identify go to `_Unsorted-Review/` inside the target rather than
  being guessed at.

## What is deliberately out of scope

* **Cloud-synced folders through a scripting bridge.** On macOS, moving directories out of iCloud-synced
  locations via Finder AppleScript fails unpredictably, and `System Events` deletes bypass the Trash.
  declutter does not attempt either. If the shell cannot reach the folder, the probe says so and stops.
* **Package bundles.** `.app`, `.scriv`, `.photoslibrary` and similar are treated as single items.
* **Deleting anything.** Ever. That is the human's job, in the review folder, when they are ready.

## Lessons this encodes

Both rules 1 and 6 come from a real incident: an ad-hoc flatten script trusted an empty Finder listing,
moved nothing, then deleted three folders permanently. Thirty-two files were lost; twenty were never
recovered. A reusable executor with these invariants would have refused.
