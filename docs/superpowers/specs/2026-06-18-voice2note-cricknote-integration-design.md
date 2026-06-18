# voice2note → CrickNote Integration: classify recordings and route by type

**Date:** 2026-06-18
**Status:** Proposed design (Revision 3), pending implementation plan
**Repos:** `voice2note` (engine changes) · `crickNote` (skills + agent-doc templates)

> **Implementation status: not started.** This is a design document. No source in
> `voice2note/` or `crickNote/` has been modified. The code touchpoints this
> design will change during implementation: `voice2note/notes.py` (stop emitting
> dated `- [ ]` checkboxes, line ~35), `voice2note/run.py` (drop the daily-note
> block, new create-only flow, lines ~62-63), `voice2note/state.py` (v2 state +
> atomic save), and two new files `voice2note/routing.py` and
> `voice2note/vault_writer.py`. The CrickNote side adds skill files and edits
> agent-doc templates only — no engine code.

## Revision history

- **r3 (2026-06-18)** — second review round. **Dropped hash-guarded
  re-analysis** (its re-check→write window is a real TOCTOU that the CLI's
  snapshot-less `vault_write` cannot guard, and a compare-and-swap tool would be
  engine code): voice2note is now strictly **write-once**, and transcript-only
  notes are summarized by the triage agent. Added a **pre-write existence check**
  (adopt-not-rewrite) and **atomic `state.json`** for the crash-before-save
  window. Idea routing gets a deterministic path + marker. `USE_CRICKNOTE` is an
  explicit boolean (no auto-detect). Hashes are ≥16 hex (collision-resistant, not
  "collision-free"). Testing split: unittest/Vitest for code, **manual acceptance
  tests** for skill orchestration. See §13.
- **r2** — hardened against data-loss modes (write-once, resumable routing,
  provisional classification, mandatory reindex, etc.).
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
- **No CrickNote engine code** — no new tools, DB columns, migrations, pragmas, or
  a compare-and-swap write tool. The CrickNote side is skill files plus two
  agent-doc template edits.
- No knowledge-base mapping in the voice path; run `cricknote-kb-update` on a
  routed record later if wanted.
- No automatic task creation for conversation/talk.
- No automatic re-analysis of transcript-only notes by voice2note (§5, §7).
- No speaker diarization in v1 (§5).

## 3. Context (verified against code)

**voice2note** — `launchd` (~2h) → find new memos (`CloudRecordings.db`) → copy
audio out of the TCC-protected folder → ffmpeg → 16 kHz wav → `whisper-cli`
(local, `-otxt -nt -np`, **plain text, no diarization** — `transcribe.py:23`) →
`codex exec` → JSON → write note(s). `Memo.id` is the `.m4a` filename — a stable
per-recording id (`memos.py:14,63`). `state.json` today is a `processed_ids` set
written **non-atomically** (`state.py:26`); any exception leaves a memo for retry.
`notes.py:35` emits dated `- [ ]` checkboxes; `run.py:62-63` writes the memo note
and a daily-note block — both change in this design.

**CrickNote** — lab-notebook engine over the vault; an agent calls
`cricknote tool <name> '<json>'`. Verified facts that shape this design:

- Vault `/Users/le211/Nutstore Files/0 Obsidian/crickNote` (space in path,
  Nutstore-synced). `~/.cricknote/config.json` holds `vaultPath`; the CLI
  resolves the vault from it regardless of the caller's CWD.
- **Every note under `Memory/` is `noteType: diary`** (`parser.ts:118`), requiring
  frontmatter `date` + `type` and validating `status` ∈ {draft, in-progress,
  complete} (warnings only).
- `vault_write` creates missing parent folders (`safe-writer.ts:306`) and
  **overwrites** existing files (`vault.ts:170`). Through the CLI it uses a
  **throwaway ConflictDetector with no read snapshot**, so it **cannot detect a
  concurrent edit** — it overwrites unconditionally (`tool-dispatch.ts:43`). This
  is why §7 never overwrites an existing note.
- `vault_list` reads SQLite `note_metadata`, filters on **fixed columns only**
  (`date, experiment_type, project, status, project_id, series`), and returns **at
  most 50 rows** (`vault.ts:96`). A `folder` with `/` matches `path LIKE 'f/%'`.
- The CLI applies edits and incrementally indexes each write — **but an index
  failure is logged and still reported as success** (`apply-edit.ts:84`). The file
  on disk is the source of truth; the index is derived.
- `vault_append` **errors if the target file does not exist** (`vault.ts:123`).
- `task_list`/`task_complete` scan only `Memory/Daily/` (`tasks.ts:26`);
  `get_today_diary`/`get_week_plan` read only the single dated file. Notes under
  `Memory/voiceMemo/` do not pollute task/diary logic.
- DB is WAL (`database.ts:16`).
- `cricknote setup` **overwrites** the vault's `CLAUDE.md` *and* `AGENTS.md` from
  `templates/agent-docs/`, and copies the repo `skills/` dir into the vault
  (`install-agent-assets.ts:10-26`). Vault files must be edited via repo
  templates/skills, not by hand.

## 4. Architecture: a two-stage pipeline

```
STAGE 1 — unattended (voice2note, ~2h), strictly create-once
  capture → transcribe → classify (provisional) → render one note
    → IF the deterministic note path already exists: adopt into state, do NOT write
    → ELSE write to Memory/voiceMemo/ via `cricknote tool vault_write`
         conversation / talk → status: complete            (finalized)
         record / uncertain  → status: draft                (triage queue)
         analysis failed     → transcript-only, status: draft, analysis: pending

         ── seam: notes in Memory/voiceMemo/, keyed by source_id ──

STAGE 2 — human-in-the-loop (you + CrickNote agent, on review)
  cricknote-voice-inbox:
    cricknote reindex                                   (MANDATORY first)
    vault_list {folder:"Memory/voiceMemo", status:"draft" | "in-progress"}
    → per record: read; if analysis: pending, summarize it first; then you pick
      one OR MORE of:
         • append to related experiment  (vault_search → vault_append + marker)
         • new idea note in Ideas/        (deterministic path + marker)
         • tasks from to-dos              (task_add + marker, deduped)
       …or reclassify, or dismiss.
    → progress recorded in frontmatter as each route completes;
      status: draft → in-progress → complete (disposition: routed | dismissed)
  cricknote-daily-review: surfaces "N voice records pending triage (50+ if capped)"
```

**voice2note never overwrites an existing note.** The only write is a *create* at
a deterministic, source-id-derived path; if that path exists, it is adopted into
state and left untouched. This eliminates overwrite-after-triage entirely, with no
dependency on conflict detection.

## 5. Classification (provisional)

Done in voice2note's `codex exec` call (the only LLM change). Whisper output has
**no speaker labels**, so type inference is imperfect — therefore:

- The **only behavior-changing distinction is record vs. not-record.**
  conversation and talk are handled identically (summary, no tasks,
  `status: complete`), so imprecise conv-vs-talk labeling is cosmetic.
- **Ambiguity rule:** confidence `< VOICE2NOTE_CONFIDENCE_MIN` (default 0.5), or a
  missing/invalid type, → **record** (queued). Nothing is silently shelved.
- Classification is **provisional**: the inbox skill can **reclassify** or
  **dismiss**.
- **Analysis failure** (codex down) writes a **transcript-only** note
  (`analysis: pending`, queued). voice2note never re-analyzes it (the re-check→
  write TOCTOU is uncloseable without a CAS tool, §3). Instead the **triage agent
  summarizes it** when you review — a human is present, so an overwrite is a
  deliberate, visible edit, not a blind background one.
- Future option (not v1): whisper.cpp `tinydiarize` for crude speaker turns.

## 6. The data contract (the seam)

Note path: `Memory/voiceMemo/<YYYY-MM-DD-HHMM>-<slug>-<h16>.md`, where `h16` =
first **16** hex of `sha256(source_id)`. The hash makes the path **deterministic
and collision-resistant** (a 64-bit tag; two memos in the same minute with the
same title no longer collide) and makes "does this memo already have a note?" a
single-path check.

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
tags: [voice-memo, <topics…>] # each tag YAML-escaped; example shown unquoted for readability
---
```

- conversation / talk → `status: complete` on write (never queued).
- record / uncertain / analysis-failed → `status: draft`.
- **Pending queue = `vault_list {folder:"Memory/voiceMemo", status:"draft"}`**
  (plus `status:"in-progress"` to resume a crashed triage). One call, no schema
  change, no validation warnings.

Body: `## Summary`, optional `## Possible to-dos` (plain bullets — **never** dated
`- [ ]` checkboxes), `## Topics`, `## Notable Details`, `## Transcript`
(collapsible). conversation/talk omit the to-dos section.

## 7. Stage 1 — voice2note changes (Python, stdlib only)

**State model (`state.json`, v2), keyed by `source_id`:**

```
memos[source_id] = { note_rel, analysis: "complete" | "pending", recording_type, updated }
```
No hashes (write-once needs none). Old `state.json` (a `processed_ids` set)
migrates: each id → `{ analysis: "complete" }` (already handled; never revisited).
**`save()` becomes atomic** (write a temp file, `os.replace` over the target) so a
crash mid-save can't corrupt state.

**Create-once flow, per memo each run:**

1. Compute the deterministic note path from `source_id` (§6).
2. `source_id` already in `state.memos` → already handled → skip.
3. Else the note **file exists on disk** (a crash wrote it before state was saved)
   → read its frontmatter, record it into `state.memos`, **do not rewrite**.
4. Else transcribe + analyze:
   - success → render full note → `cricknote tool vault_write` (create) →
     record state (`analysis: complete`).
   - analysis failure → render transcript-only note (`analysis: pending`,
     `status: draft`, `recording_type: record`) → write → record (`analysis:
     pending`). The memo is now visible and queued; voice2note never revisits it.
   - transcription failure → write nothing, record nothing → safe retry next run.
5. `state.save()` (atomic) after each memo, narrowing the unsaved window to one.

voice2note assumes a single instance (launchd's interval serializes runs); a
PID/lock file is optional hardening.

**Files:**

- `analyze.py` — prompt + `parse_analysis` also return `recording_type` and
  `confidence`; apply the ambiguity rule; coerce `confidence` to a clamped float
  in [0,1] with a safe default (→ record) on garbage.
- `routing.py` (new, pure) — `recording_type → (status, include_todos)`. Single
  source of routing policy; unit-tested in isolation.
- `notes.py` — emit §6 frontmatter via a **stdlib YAML double-quoted-scalar
  escaper** (`title`, each `tag`; escape `\`, `"`, control chars, collapse
  newlines); render to-dos as plain bullets; **remove** dated checkboxes
  (line ~35) and the daily-note block.
- `vault_writer.py` (new) — build `cricknote tool vault_write '<json>'` with a
  **vault-relative** path, JSON via `json.dumps`, `subprocess.run([...],
  shell=False)`. A non-zero exit / error **raises** → the memo is retried next
  run; **never** silently falls back to a direct file write. Also exposes a
  read-existence/read-frontmatter helper (direct fs, since voice2note has vault
  access) for steps 2-3.
- `config.py` —
  - `VOICE2NOTE_USE_CRICKNOTE` — **explicit `true`/`false`, no auto-detect**;
    default `false` (standalone direct write, today's behavior). When `true` and
    the CLI is missing/unrunnable → **hard fail** at startup (no fallback).
  - `VOICE2NOTE_CRICKNOTE_BIN`, `VOICE2NOTE_CONFIDENCE_MIN`.
  - `VOICE2NOTE_MEMO_RELDIR` (default `Memory/voiceMemo`; **reject absolute paths
    and `..`; must normalize within the vault**).
  - **Validate vault equality:** canonicalize (`realpath`) `VOICE2NOTE_VAULT` and
    `~/.cricknote/config.json`'s `vaultPath`; on mismatch, fail clearly (startup
    and `--check`).
- `run.py` — drive the create-once flow; drop `append_to_daily`.

## 8. Stage 2 — CrickNote changes (skills + templates, no engine code)

- **New `cricknote-voice-inbox` skill** (in repo `skills/`, installed by setup):
  1. `cricknote reindex` — **mandatory**, so the queue reflects disk even if an
     incremental index failed.
  2. `vault_list '{"folder":"Memory/voiceMemo","status":"draft"}'` (and
     `"in-progress"` to resume). If exactly 50 rows return, tell the user the list
     is capped (show "50+").
  3. Per record: `vault_read`. **If `analysis: pending`** (transcript-only),
     summarize it with the user first and `vault_write` the summary back (sets
     `analysis: complete`). Then propose **one or more** destinations and **wait
     for confirmation**:
     - **experiment** → `vault_search`; `vault_append` a timestamped block ending
       with `<!-- v2n:<source_id> -->`. Re-read and skip if the marker is present.
     - **idea** → create `Ideas/<slug>-<h16>.md` (deterministic, `unknown` note
       type, no required frontmatter) carrying `source_id`; **check existence
       first** and skip if present.
     - **tasks** → `task_add` each accepted to-do with a trailing `[v2n:<h16>]`
       marker; dedupe by searching first (as `cricknote-reminders` does).
     - **reclassify** → update `recording_type` (to conv/talk → `status:
       complete`; stays record → remains `draft`).
     - **dismiss** → `status: complete`, `disposition: dismissed`, no routing.
  4. **Resumable progress:** set `status: in-progress` when routing starts; append
     each finished target to `routed_to`; only after all chosen routes succeed set
     `status: complete`, `disposition: routed`, with backlinks. A crash leaves
     `in-progress` + partial `routed_to`; re-running resumes and the markers
     prevent duplicate appends/notes/tasks.
- **`cricknote-daily-review`** — add a step counting the pending queue and
  surfacing it ("50+" when capped).
- **Agent-doc templates** — edit repo `templates/agent-docs/CLAUDE.md` **and**
  `AGENTS.md`: note `Memory/voiceMemo/` is voice2note-owned, `Ideas/` is the
  idea-note destination, and `cricknote-voice-inbox` is the triage workflow.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Overwrite of a triaged note on retry | voice2note is write-once; a *create* only happens when the deterministic path is absent (existence check, §7); existing notes are never rewritten |
| Crash after write, before `state.save` | Pre-write existence check adopts the on-disk note into state without rewriting; `state.save` is atomic (temp + `os.replace`) |
| Concurrent edit during background re-analysis (TOCTOU) | Eliminated: voice2note does **not** re-analyze; transcript-only notes are summarized by the triage agent with a human present |
| Duplicate experiment append / idea note / tasks on retry | Deterministic idea path; per-route markers (`<!-- v2n:id -->`, `[v2n:h16]`) checked before acting; resumable `status`/`routed_to` progress (§8) |
| Imperfect type from speaker-less transcript | Only record-vs-not-record matters; bias-to-record; provisional + reclassify/dismiss |
| Silent incremental-index failure hides a draft | File on disk is truth; **mandatory `reindex`** before listing |
| `vault_list` 50-row cap undercounts | Show "50+" when capped; design assumes regular triage |
| Auto direct-write bypasses indexing/audit | `USE_CRICKNOTE` is explicit; `true` + missing CLI fails; CLI errors → retry, never silent fallback |
| Wrong vault (config drift) | Canonical-path equality check at startup/`--check`; fail safely |
| SQLITE_BUSY (launchd vs. open agent) | WAL serializes writers; voice2note retries next run. `busy_timeout` is an optional *separate* crickNote PR, out of scope (keeps "no engine code") |
| Malformed YAML drops frontmatter | stdlib double-quoted-scalar escaper for title/tags; clamped-float confidence; tests for hostile inputs |
| Nutstore sync mid-write | Atomic tmp+rename; vault path never on a command line |

## 10. Configuration (new voice2note env)

| Variable | Default | Meaning |
|---|---|---|
| `VOICE2NOTE_USE_CRICKNOTE` | `false` | Explicit `true`/`false`. `true` routes writes through `cricknote tool` (missing CLI → hard fail); `false` = standalone direct write |
| `VOICE2NOTE_CRICKNOTE_BIN` | `which cricknote` | Absolute path to the CLI (set in the LaunchAgent for launchd PATH) |
| `VOICE2NOTE_MEMO_RELDIR` | `Memory/voiceMemo` | Vault-relative folder; absolute/`..` rejected |
| `VOICE2NOTE_CONFIDENCE_MIN` | `0.5` | Below this → force `recording_type: record` |

`VOICE2NOTE_VAULT` must canonically equal `~/.cricknote/config.json`'s
`vaultPath` (validated; hard failure on mismatch).

## 11. Testing

- **voice2note (unittest):**
  - `parse_analysis`: extracts/defaults `recording_type`; `confidence` coercion
    (string/out-of-range/missing) → clamped float; ambiguity rule → record.
  - `routing.py`: status/todos per type.
  - YAML escaper: titles with `"`, `:`, `\`, newlines, emoji; tag lists →
    re-parse to original values.
  - **Create-once idempotency:** path-exists → adopt into state, **no** write
    (assert `vault_write` not called); filename determinism + collision (same
    minute+title, different `source_id`).
  - **Crash window:** note on disk but `source_id` absent from state → adopt, no
    rewrite.
  - **Atomic save:** interrupted save leaves the prior `state.json` intact
    (temp + `os.replace`).
  - `vault_writer`: correct argv (subprocess mocked); CLI error **raises** (no
    direct-write); standalone mode writes directly.
  - `config`: vault-equality mismatch fails; `MEMO_RELDIR` rejects absolute/`..`;
    `USE_CRICKNOTE=true` + missing CLI fails.
  - `notes.py`: emits no `- [ ]` lines; no daily block.
- **CrickNote:** no new engine code, so the existing **Vitest** suite is
  regression-only — run it to confirm the baseline (it was interrupted in review,
  so the baseline is currently unconfirmed). The `cricknote-voice-inbox` skill is
  **Markdown orchestration that Vitest cannot exercise**; its behaviors
  (multi-route, markers, resume from `in-progress`, dismiss, reclassify,
  summarize-then-route for `analysis: pending`) are validated by **manual
  acceptance tests**: scripted scenarios run through Claude Code and Codex against
  a temp vault, with a written checklist (queue listing, idempotent re-run, no
  duplicate append/task, status/disposition transitions).

## 12. Phases

1. **voice2note:** classification + ambiguity rule; §6 contract + YAML escaper;
   `routing.py`; `state.json` v2 + atomic save + create-once existence check;
   `vault_writer.py` (no silent fallback; explicit `USE_CRICKNOTE`); config
   validation; drop checkboxes + daily block. unittest throughout.
2. **CrickNote:** `cricknote-voice-inbox` skill (mandatory reindex, multi-route,
   deterministic idea path, idempotency markers, resumable progress,
   dismiss/reclassify, summarize-then-route) + daily-review hook +
   `CLAUDE.md`/`AGENTS.md` template edits. Confirm the Vitest regression baseline;
   run the manual acceptance tests against the real vault with both agents.
3. **Hardening/docs:** LaunchAgent PATH/bin; READMEs in both repos; optional
   PID lock; (optional, separate) crickNote `busy_timeout` PR if contention is
   observed.

## 13. Open questions

- None blocking. KB mapping stays out of the voice path by decision (§2).
- A `Memory/Daily/` one-line linked summary is deferred (would break the
  create-once property; `vault_append` also requires the daily note to exist).
- Diarization (`tinydiarize`) deferred (§5).
