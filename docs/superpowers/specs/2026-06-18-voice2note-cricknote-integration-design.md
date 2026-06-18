# voice2note → CrickNote Integration: classify recordings and route by type

**Date:** 2026-06-18
**Status:** Proposed design (Revision 2), pending implementation plan
**Repos:** `voice2note` (engine changes) · `crickNote` (skills + agent-doc templates)

## Revision history

- **r2 (2026-06-18)** — hardened against data-loss/duplication failure modes
  found in review: write-once with a hash guard (overwrite-after-triage),
  resumable idempotent routing (duplicate appends/tasks), provisional
  classification (no speaker labels), mandatory reindex (silent index failure),
  dismiss/reclassify actions, multi-destination routing, explicit state model,
  config validation, stdlib YAML escaping, and removal of the `busy_timeout`
  engine change that contradicted the "no engine code" non-goal. See §13.
- **r1** — initial two-stage design.

## 1. Goal

Make voice2note classify each recording and route it into a CrickNote-managed
Obsidian vault:

- **conversation** (dialogue with others) → summary note, no tasks.
- **talk** (a presentation you attended) → summary note, no tasks.
- **record** (you dictating experiment notes, thoughts, or a new idea) → summary
  note **queued for human triage**, then routed — with your confirmation — into a
  related experiment, a new idea note, and/or tasks.

voice2note stays an autonomous capture/transcribe/classify pipeline. CrickNote's
agent (run from the vault) does the context-aware routing that needs the vault
and a human in the loop. The two communicate only through notes in the vault.

## 2. Non-Goals

- No port of voice2note to TypeScript. The handoff is the CrickNote CLI.
- **No CrickNote engine code** — no new tools, DB columns, migrations, or pragmas.
  The CrickNote side is skill files plus two agent-doc template edits. (This is
  why `busy_timeout`, considered in r1, is out of scope — see §9.)
- No knowledge-base mapping in the voice path; run `cricknote-kb-update` on a
  routed record later if wanted.
- No automatic task creation for conversation/talk.
- No speaker diarization in v1 (see §5).

## 3. Context (verified against code)

**voice2note** — `launchd` (~2h) → find new memos (`CloudRecordings.db`) → copy
audio out of the TCC-protected folder → ffmpeg → 16 kHz wav → `whisper-cli`
(local, `-otxt -nt -np`, **plain text, no diarization** — `transcribe.py:23`) →
`codex exec` → JSON → write note(s). `Memo.id` is the `.m4a` filename — a stable
per-recording id (`memos.py:14,63`). `state.json` records processed ids; any
exception leaves a memo for retry.

**CrickNote** — lab-notebook engine over the vault; an agent calls
`cricknote tool <name> '<json>'`. Verified facts that shape this design:

- Vault `/Users/le211/Nutstore Files/0 Obsidian/crickNote` (space in path,
  Nutstore-synced). `~/.cricknote/config.json` holds `vaultPath`; the CLI
  resolves the vault from it regardless of the caller's CWD.
- **Every note under `Memory/` is `noteType: diary`** (`parser.ts:118`), requiring
  frontmatter `date` + `type` and validating `status` ∈ {draft, in-progress,
  complete} (warnings only).
- `vault_write` creates missing parent folders (`safe-writer.ts:306`,
  `mkdirSync(recursive)` then tmp-write+rename) and **overwrites** existing files
  (`vault.ts:170`).
- `vault_list` reads the SQLite `note_metadata` table, filters on **fixed columns
  only** (`date, experiment_type, project, status, project_id, series`), and
  returns **at most 50 rows** (`vault.ts:96`). A `folder` containing `/` matches
  `path LIKE 'folder/%'`.
- The CLI applies pending edits and incrementally indexes each write — **but an
  index failure is logged and still reported as a successful write**
  (`apply-edit.ts:84`). The file on disk is therefore the source of truth; the
  index is derived and can lag.
- `vault_append` **errors if the target file does not exist** (`vault.ts:123`).
- `task_list`/`task_complete` scan only `Memory/Daily/` (`tasks.ts:26`);
  `get_today_diary`/`get_week_plan` read only the single dated file
  (`context.ts`). Notes under `Memory/voiceMemo/` do not pollute task/diary logic.
- DB is WAL (`database.ts:16`).
- `cricknote setup` **overwrites** the vault's `CLAUDE.md` *and* `AGENTS.md` from
  `templates/agent-docs/`, and copies the repo `skills/` dir into the vault's
  `.claude/skills/` + `.agents/skills/` (`install-agent-assets.ts:10-26`). Vault
  files must therefore be edited via the repo templates/skills, not by hand.

## 4. Architecture: a two-stage pipeline

```
STAGE 1 — unattended (voice2note, ~2h)
  capture → transcribe → classify (provisional) → render one note
    → write to Memory/voiceMemo/ via `cricknote tool vault_write`
         conversation / talk → status: complete            (finalized)
         record / uncertain  → status: draft                (triage queue)
         analysis failed     → transcript-only, status: draft, analysis: pending

         ── seam: notes in Memory/voiceMemo/, keyed by source_id ──

STAGE 2 — human-in-the-loop (you + CrickNote agent, on review)
  cricknote-voice-inbox:
    cricknote reindex                                   (MANDATORY first)
    vault_list {folder:"Memory/voiceMemo", status:"draft" | "in-progress"}
    → per record: read; you pick one OR MORE of:
         • append to related experiment  (vault_search → vault_append + marker)
         • new idea note in Ideas/        (vault_write)
         • tasks from to-dos              (task_add + marker, deduped)
       …or reclassify, or dismiss.
    → progress recorded in frontmatter as each route completes;
      status: draft → in-progress → complete (disposition: routed | dismissed)
  cricknote-daily-review: surfaces "N voice records pending triage (50+ if capped)"
```

**Stage 1 is create-only and write-once** (§7). It only creates notes in
`Memory/voiceMemo/`, never touches an existing note's content beyond its own
pristine output (hash-guarded), and never writes serialized notes.

## 5. Classification (provisional)

Done in voice2note's `codex exec` call (the only LLM change). Whisper output has
**no speaker labels**, so type inference from content is imperfect — therefore:

- The **only behavior-changing distinction is record vs. not-record.**
  conversation and talk are handled identically (summary, no tasks,
  `status: complete`), so imprecise conv-vs-talk labeling is cosmetic.
- **Ambiguity rule:** confidence `< VOICE2NOTE_CONFIDENCE_MIN` (default 0.5), or a
  missing/invalid type, → **record** (queued). Nothing is silently shelved.
- Classification is **provisional**: the inbox skill can **reclassify** or
  **dismiss**. A record wrongly queued is a one-action dismiss (§8).
- Future option (not v1): whisper.cpp `tinydiarize` (`-tdrz`, `*-tdrz` model)
  for crude speaker-turn markers to improve the conv/talk split.

## 6. The data contract (the seam)

Note path: `Memory/voiceMemo/<YYYY-MM-DD-HHMM>-<slug>-<h8>.md`, where `h8` =
first 8 hex of `sha256(source_id)`. The hash makes the filename **deterministic
and collision-free** (two memos in the same minute with the same title no longer
collide), and makes "does this memo already have a note?" a single-path check.

```yaml
---
date: 2026-06-18              # required for Memory/ (diary) notes
type: voice-memo              # required; NOT "daily-diary", so diary logic ignores it
source_id: "ABCD-1234.m4a"    # stable Memo.id; the idempotency key
recording_type: record        # conversation | talk | record  (provisional)
classify_confidence: 0.62     # clamped float; audits the ambiguity rule
analysis: complete            # complete | pending  (pending = transcript-only)
status: draft                 # draft = pending triage · in-progress = routing · complete = done
disposition:                  # (only when complete) routed | dismissed
routed_to: []                 # backlinks recorded as routing progresses
source: voice-memo
title: "<memo title>"         # YAML-escaped (§7)
recorded: 2026-06-18T14:32
tags: [voice-memo, <topics…>] # each tag YAML-escaped
---
```

- conversation / talk → `status: complete` on write (never queued).
- record / uncertain / analysis-failed → `status: draft`.
- **Pending queue = `vault_list {folder:"Memory/voiceMemo", status:"draft"}`**
  (plus `status:"in-progress"` to resume a crashed triage). One call, no schema
  change, no validation warnings (`date`+`type` present, `status` valid).

Body: `## Summary`, optional `## Possible to-dos` (plain bullets — **never** dated
`- [ ]` checkboxes, so nothing leaks into `task_list`), `## Topics`,
`## Notable Details`, `## Transcript` (collapsible). conversation/talk omit the
to-dos section.

## 7. Stage 1 — voice2note changes (Python, stdlib only)

**State model (`state.json`, v2), keyed by `source_id`:**

```
memos[source_id] = {
  note_rel, written_hash,            # sha256 of the exact content v2n last wrote
  analysis: "complete" | "pending" | "abandoned",  # abandoned = you took over or deleted it
  recording_type, updated
}
```
Old `state.json` (set of processed names) migrates to `analysis: complete`, no
hash (so never re-analyzed). A `source_id` present in `memos` is "seen".

**Write-once with hash guard (the core safety property):**

- **New memo:** transcribe → analyze.
  - success → render full note; `cricknote tool vault_write`; store `written_hash`;
    `analysis: complete`.
  - failure → render transcript-only note (`analysis: pending`, `status: draft`,
    `recording_type: record`); write; store `written_hash`; `analysis: pending`.
    The memo is now visible and queued.
- **Re-analysis pass** (memos with `analysis: pending`): read the note from disk.
  - file missing → user deleted it → set `analysis: abandoned`; never resurrect.
  - on-disk hash ≠ `written_hash` → you/the agent edited or triaged it → set
    `analysis: abandoned`; never overwrite.
  - on-disk hash == `written_hash` → still pristine → re-run analysis; on success
    rewrite (preserving `source_id`; conv/talk → `status: complete`, record →
    keep `draft`), update `written_hash`, `analysis: complete`. On failure leave
    pending.
- Transcription failure writes nothing (memo stays unseen) → safe retry.

**Files:**

- `analyze.py` — prompt + `parse_analysis` also return `recording_type` and
  `confidence`; apply the ambiguity rule; coerce `confidence` to a clamped float
  in [0,1] with a safe default (→ record) on garbage.
- `routing.py` (new, pure) — `recording_type → (status, include_todos)`. Single
  source of routing policy; unit-tested in isolation.
- `notes.py` — emit the §6 frontmatter via a **stdlib YAML double-quoted-scalar
  escaper** (`title`, each `tag`; escape `\`, `"`, control chars, collapse
  newlines); render to-dos as plain bullets; drop dated checkboxes and the
  daily-note block.
- `vault_writer.py` (new) — build `cricknote tool vault_write '<json>'` with a
  **vault-relative** path, JSON via `json.dumps`, `subprocess.run([...],
  shell=False)`. A non-zero exit / error is a **failed write** → raise so the
  memo is retried next run; **never silently fall back to a direct file write.**
  Direct file write happens only when `VOICE2NOTE_USE_CRICKNOTE` is explicitly
  off (standalone mode).
- `config.py` — `VOICE2NOTE_USE_CRICKNOTE`, `VOICE2NOTE_CRICKNOTE_BIN`,
  `VOICE2NOTE_MEMO_RELDIR` (default `Memory/voiceMemo`; **reject absolute paths
  and `..`; must normalize within the vault**), `VOICE2NOTE_CONFIDENCE_MIN`.
  **Validate vault equality:** canonicalize (`realpath`) `VOICE2NOTE_VAULT` and
  `~/.cricknote/config.json`'s `vaultPath`; on mismatch, fail with a clear error
  (in startup and `--check`).
- `run.py` — drive new-vs-pending passes; drop `append_to_daily`.

## 8. Stage 2 — CrickNote changes (skills + templates, no engine code)

- **New `cricknote-voice-inbox` skill** (in repo `skills/`, installed by setup):
  1. `cricknote reindex` — **mandatory**, so the queue reflects disk even if an
     incremental index failed.
  2. `vault_list '{"folder":"Memory/voiceMemo","status":"draft"}'` (and
     `"in-progress"` to resume). If exactly 50 returned, tell the user the list is
     capped.
  3. Per record: `vault_read`; the agent proposes **one or more** destinations and
     **waits for confirmation**:
     - **experiment** → `vault_search`; `vault_append` a timestamped block ending
       with an idempotency marker `<!-- v2n:<source_id> -->`. Re-check via
       `vault_read` and skip if the marker is already present.
     - **idea** → `vault_write` a new note in top-level `Ideas/` (classified
       `unknown`; no required frontmatter).
     - **tasks** → `task_add` each accepted to-do with a trailing `[v2n:<h8>]`
       marker; dedupe by searching first (as `cricknote-reminders` does).
     - **reclassify** → update `recording_type` (to conv/talk → `status:
       complete`; stays record → remains `draft`).
     - **dismiss** → `status: complete`, `disposition: dismissed`, no routing.
  4. **Resumable progress:** set `status: in-progress` when routing starts; append
     each finished target to `routed_to`; only after all chosen routes succeed set
     `status: complete`, `disposition: routed`, with backlinks. A crash leaves
     `in-progress` + partial `routed_to`; re-running resumes and markers prevent
     duplicates.
- **`cricknote-daily-review`** — add a step counting the pending queue (after the
  mandatory reindex it already does) and surfacing it ("50+" when capped).
- **Agent-doc templates** — edit repo `templates/agent-docs/CLAUDE.md` **and**
  `AGENTS.md`: note `Memory/voiceMemo/` is voice2note-owned, `Ideas/` is the
  idea-note destination, and `cricknote-voice-inbox` is the triage workflow.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Overwrite of a triaged note on retry | Write-once + `written_hash` guard (§7); deterministic `source_id`-hashed filename; voice2note never overwrites content it didn't last write |
| Duplicate experiment append / tasks on retry | Per-route idempotency markers (`<!-- v2n:id -->`, `[v2n:h8]`) checked before acting; resumable `status`/`routed_to` progress (§8) |
| Imperfect type from speaker-less transcript | Only record-vs-not-record matters; bias-to-record; provisional + reclassify/dismiss in triage |
| Silent incremental-index failure hides a draft | File on disk is truth; **mandatory `reindex`** before listing; voice2note keys "written" on the file, not on indexing |
| `vault_list` 50-row cap undercounts | Show "50+" when capped; design assumes regular triage keeps the queue small |
| Auto direct-write bypasses indexing/audit | Direct write only in explicit standalone mode; CLI errors → retry, never silent fallback |
| Wrong vault (config drift) | Canonical-path equality check at startup/`--check`; fail safely |
| SQLITE_BUSY (launchd vs. open agent) | WAL serializes writers; voice2note retries next run. `busy_timeout` is an optional *separate* crickNote PR, not in scope (keeps "no engine code") |
| Malformed YAML drops frontmatter (→ misclassified/unqueued) | stdlib double-quoted-scalar escaper for title/tags; clamped-float confidence; tests for hostile inputs |
| Nutstore sync mid-write | Atomic tmp+rename; vault path never on a command line (CLI reads its own config) |

## 10. Configuration (new voice2note env)

| Variable | Default | Meaning |
|---|---|---|
| `VOICE2NOTE_USE_CRICKNOTE` | on if bin found | Route writes through `cricknote tool` vs. standalone direct write |
| `VOICE2NOTE_CRICKNOTE_BIN` | `which cricknote` | Absolute path to the CrickNote CLI (set in the LaunchAgent for launchd PATH) |
| `VOICE2NOTE_MEMO_RELDIR` | `Memory/voiceMemo` | Vault-relative folder; absolute/`..` rejected |
| `VOICE2NOTE_CONFIDENCE_MIN` | `0.5` | Below this → force `recording_type: record` |

`VOICE2NOTE_VAULT` must canonically equal `~/.cricknote/config.json`'s
`vaultPath` (validated; hard failure on mismatch).

## 11. Testing (TDD; existing 26 tests updated where behavior changes)

- **voice2note (unittest):**
  - `parse_analysis` extracts/defaults `recording_type`; `confidence` coercion
    (string, out-of-range, missing) → clamped float; ambiguity rule → record.
  - `routing.py` status/todos per type.
  - YAML escaper: titles with `"`, `:`, `\`, newlines, emoji; tag lists → output
    re-parses to the original values.
  - **Write-once/hash guard:** new→write; pending+pristine→re-analyze+update;
    pending+modified→skip (no overwrite); missing file→no resurrect; filename
    determinism + collision (same minute+title, different `source_id`).
  - `vault_writer` builds correct argv (subprocess mocked); CLI error raises (no
    direct-write); standalone mode writes directly.
  - config: vault-equality mismatch fails; `MEMO_RELDIR` rejects absolute/`..`.
  - `notes.py` emits no `- [ ]` lines; no daily block.
- **CrickNote (vitest + temp vault):** a `status:draft` note in `Memory/voiceMemo/`
  is returned by the queue query and **not** by `task_list`; multi-destination
  routing appends-with-marker / writes an `Ideas/` note / adds a deduped task;
  re-running a partially-routed note does not duplicate; status/disposition
  transitions; dismiss and reclassify leave the queue correctly. Skills validated
  from the vault dir with Claude Code and Codex.

## 12. Phases

1. **voice2note:** classification + ambiguity rule; §6 contract + YAML escaper;
   `routing.py`; `state.json` v2 + write-once/hash-guard + re-analysis pass;
   create-only `vault_writer` (no silent fallback); config validation; drop daily
   block. Tests.
2. **CrickNote:** `cricknote-voice-inbox` skill (mandatory reindex, multi-route,
   idempotency markers, resumable progress, dismiss/reclassify) + daily-review
   hook + `CLAUDE.md`/`AGENTS.md` template edits. Validate against the real vault.
3. **Hardening/docs:** LaunchAgent PATH/bin; README updates in both repos;
   (optional, separate) crickNote `busy_timeout` PR if contention is observed.

## 13. Open questions

- None blocking. KB mapping stays out of the voice path by decision (§2).
- A `Memory/Daily/` one-line linked summary is deferred (would break Stage 1's
  create-only property; `vault_append` also requires the daily note to exist).
- Diarization (`tinydiarize`) deferred to a future iteration (§5).
