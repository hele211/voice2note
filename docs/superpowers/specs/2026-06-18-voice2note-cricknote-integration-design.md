# voice2note → CrickNote Integration: classify recordings and route by type

**Date:** 2026-06-18
**Status:** Proposed design, pending implementation plan
**Repos:** `voice2note` (engine changes) · `crickNote` (two skill additions)

## 1. Goal

Make voice2note classify each recording into one of three kinds and route it
accordingly into a CrickNote-managed Obsidian vault:

- **conversation** (dialogue with others) → summary note, no tasks.
- **talk** (a presentation you attended) → summary note, no tasks.
- **record** (you dictating experiment notes, thoughts, or a new idea) → summary
  note **queued for human triage**; later routed — with your confirmation — into
  a related experiment, a new idea note, or tasks.

voice2note stays an autonomous capture/transcribe/classify pipeline. CrickNote's
agent (Claude Code / Codex, run from the vault) does the context-aware routing
that needs the vault and a human in the loop. The two communicate only through
notes in the vault — no direct API between them.

## 2. Non-Goals

- No port of voice2note to TypeScript. It remains a standalone Python pipeline;
  the handoff is the CrickNote CLI (`cricknote tool …`).
- No new CrickNote engine code (no new tools, DB columns, or migrations). The
  CrickNote side is **two skill files**.
- No knowledge-base mapping in the voice path. A routed record can later be fed
  to the existing `cricknote-kb-update` skill when a deliberate KB mapping is
  wanted; it is not part of triage.
- No automatic task creation for conversation/talk.
- No two-device / vault-sync conflict resolution beyond what Obsidian + Nutstore
  already do.

## 3. Context (verified)

**voice2note** — `launchd` every ~2h → find new Voice Memos
(`CloudRecordings.db`) → copy audio out of the protected folder → ffmpeg → 16 kHz
wav → `whisper-cli` (local) → `codex exec` returns JSON (`summary`,
`action_items`, `topics`, `notable_details`) → writes a per-memo note + a daily
block directly with Python. `state.json` records processed memo IDs; any
exception leaves a memo unprocessed for retry next run.

**CrickNote** — a lab-notebook engine over the same Obsidian vault. You run an
agent in the vault; it calls `cricknote tool <name> '<json>'` for all serialized
writes. Verified facts that shape this design:

- Vault: `/Users/le211/Nutstore Files/0 Obsidian/crickNote` (space in path,
  Nutstore-synced). `~/.cricknote/config.json` holds `vaultPath`; the CLI
  resolves the vault from it, independent of the caller's working directory.
- `Memory/` holds `Daily/`, `Weekly/`, `Monthly/`. **Every note under `Memory/`
  is classified `noteType: diary`** (`src/ingestion/parser.ts:118`), which
  requires frontmatter `date` and `type`, and validates `status` against
  `{draft, in-progress, complete}` (warnings only — non-fatal).
- `vault_write` creates missing parent folders — `SafeWriter.atomicWrite` does
  `fs.mkdirSync(dir,{recursive:true})` then tmp-write + rename
  (`src/editing/safe-writer.ts:306`).
- `vault_list` reads the SQLite `note_metadata` table and filters on **fixed
  columns only**: `date, experiment_type, project, status, project_id, series`
  (`src/agent/tools/vault.ts:89`). There is **no** `triage`/`recording_type`
  column. A `folder` value containing `/` matches by `path LIKE 'folder/%'`.
- The CLI dispatcher applies pending edits by default and **incrementally
  indexes every file it writes** (`src/cli/apply-edit.ts:85`), so a note written
  through `cricknote tool` is immediately searchable.
- `task_list` / `task_complete` scan **only** `Memory/Daily/`
  (`src/agent/tools/tasks.ts:26`); `get_today_diary` / `get_week_plan` read only
  the single `Memory/Daily/<date>.md` / `Memory/Weekly/<week>.md` file
  (`src/agent/tools/context.ts`). Notes under `Memory/voiceMemo/` therefore do
  not pollute task or diary logic.
- DB opens in **WAL** mode (`src/storage/database.ts:16`).
- `vault_append` errors if the target file does not exist
  (`src/agent/tools/vault.ts:123`).

## 4. Architecture: a two-stage pipeline

```
STAGE 1 — unattended (voice2note, ~every 2h)
  capture → transcribe (whisper.cpp) → classify type (codex exec → JSON)
    → render one note (summary + transcript)
    → write to Memory/voiceMemo/ via `cricknote tool vault_write`
         conversation / talk → status: complete   (finalized, terminal)
         record              → status: draft       (enters the triage queue)

         ── the seam: frontmatter in Memory/voiceMemo/ ──

STAGE 2 — human-in-the-loop (you + CrickNote agent, on review)
  cricknote-voice-inbox skill:
    vault_list {folder:"Memory/voiceMemo", status:"draft"}  (the pending queue)
    → for each record: read it, agent proposes ONE destination, you confirm:
         • append to a related experiment   (vault_search → vault_append)
         • new idea note in Ideas/          (vault_write)
         • tasks from to-dos                (task_add, optional Reminders)
    → flip the note to status: complete + add a backlink to where it went
  cricknote-daily-review: surfaces "N voice records pending triage"
```

**Why this split:** classification needs only the transcript, so it runs
unattended in voice2note's existing `codex exec` call. Routing needs vault
context (which experiment? which concept?) and a confirmation step, which only
the in-vault agent has. Stage 1 never guesses a destination.

**Stage 1 is strictly create-only.** It only ever *creates* new notes in
`Memory/voiceMemo/`. It never appends to or overwrites an existing note. This
keeps it safely inside CrickNote's "freeform notes may be written directly" rule
and means an unattended daemon can never corrupt serialized notes.

## 5. Classification

Done inside voice2note's `codex exec` analysis call (the only LLM change).

- **conversation** — multiple speakers / back-and-forth dialogue.
- **talk** — single presenter; you are audience.
- **record** — you dictating: experiment notes, thoughts, a new idea.
- **Ambiguity rule:** if the model's confidence is below threshold (default 0.5)
  or the returned type is missing/invalid, classify as **record**. A misfiled
  record (silently summarized, never triaged) is the expensive error; a
  conversation that lands in the queue is a one-second dismissal. Bias to triage.

## 6. The data contract (the seam)

Every voice note is written to `Memory/voiceMemo/<YYYY-MM-DD-HHMM>-<slug>.md`
with this frontmatter. The fields are chosen to satisfy `Memory/` (diary)
validation with **zero warnings** and to make the triage queue a real, indexed,
one-call query:

```yaml
---
date: 2026-06-18          # required for Memory/ notes
type: voice-memo          # required for Memory/ notes; not "daily-diary", so diary logic ignores it
recording_type: record    # conversation | talk | record  (descriptive)
status: draft             # draft = pending triage · complete = finalized/triaged
classify_confidence: 0.62 # for auditing the ambiguity rule
source: voice-memo
title: "<memo title>"
recorded: 2026-06-18T14:32
tags: [voice-memo, <topics…>]
---
```

- conversation / talk → written `status: complete` (never in the queue).
- record → written `status: draft`.
- **Pending queue = `vault_list {folder:"Memory/voiceMemo", status:"draft"}`** —
  one call, no extra reads, no schema change, no validation warnings.

Note body (rendered by voice2note, reusing today's structure):
`## Summary`, optionally `## Possible to-dos` (plain bullets — **never** dated
`- [ ]` checkboxes, so nothing leaks into the task system), `## Topics`,
`## Notable Details`, and `## Transcript` (collapsible callout). For
conversation/talk the to-dos section is omitted or rendered as plain
"Mentioned" bullets; tasks are deliberately not registered.

## 7. Stage 1 — voice2note changes (Python)

- **`voice2note/analyze.py`** — extend the prompt + `parse_analysis` to also
  return `recording_type` ∈ {conversation, talk, record} and `confidence`
  (0–1). Apply the ambiguity rule (default to `record`). No other analysis
  change.
- **`voice2note/routing.py`** (new, small, pure) — map `recording_type` →
  `(status, include_todos)`: conversation/talk → `complete`, no todos; record →
  `draft`, todos included. Single source of truth for routing policy; unit-tested
  in isolation.
- **`voice2note/notes.py`** — add the §6 frontmatter; render to-dos as plain
  bullets (never checkboxes); drop the dated-checkbox action items and the
  daily-note block. Replace the direct `path.write_text` with a writer that
  shells out to `cricknote tool vault_write '{"path","content"}'` using a
  **vault-relative** path (`Memory/voiceMemo/<file>.md`). The CLI resolves the
  vault and auto-applies + indexes. The note (multi-line, with quotes) is passed
  as a single argv element built with `json.dumps` via `subprocess.run([...],
  shell=False)` — never string-interpolated into a shell command. Typical memo
  JSON is far under macOS `ARG_MAX`; pathological transcripts are the only
  size concern and can fall back to the direct write.
- **`voice2note/config.py`** — add `VOICE2NOTE_USE_CRICKNOTE` (default on when a
  cricknote bin is found), `VOICE2NOTE_CRICKNOTE_BIN` (absolute path), and
  `VOICE2NOTE_MEMO_RELDIR` (default `Memory/voiceMemo`). `VOICE2NOTE_VAULT` must
  point at the same vault as `~/.cricknote/config.json`. When
  `VOICE2NOTE_USE_CRICKNOTE` is off, fall back to today's direct file write so
  voice2note still works standalone.
- **`voice2note/run.py`** — `process_memo` drops `append_to_daily`; writes the
  single note via the new writer. The analysis-failed fallback writes a
  transcript-only note as `recording_type: record`, `status: draft` so it
  surfaces for attention. Retry semantics unchanged.

## 8. Stage 2 — CrickNote changes (skills only)

Sourced in the `crickNote` repo `skills/`, installed into the vault by
`cricknote setup` (copied into `.claude/skills/` and `.agents/skills/`).

- **New `cricknote-voice-inbox` skill:**
  1. (optional) `cricknote reindex` to absorb hand-edits.
  2. `cricknote tool vault_list '{"folder":"Memory/voiceMemo","status":"draft"}'`
     — the pending queue.
  3. For each record: `vault_read` it; the agent proposes **one** destination and
     **waits for confirmation** (the existing KB confirm-gate pattern):
     - **experiment** → `vault_search` for the related experiment, then
       `vault_append` a timestamped entry to it.
     - **idea** → `vault_write` a new freeform note in `Ideas/` (top-level;
       classified `unknown`, so no required frontmatter).
     - **tasks** → `task_add` for each accepted to-do (optional Reminders push
       via `cricknote-reminders`).
  4. Flip the voice note to `status: complete` (read → replace the `status:`
     line → `vault_write`) and add a backlink (e.g. `Routed to [[IL003]]`) so the
     archive records where the content went. This removes it from the queue.
- **`cricknote-daily-review` hook:** add one step — count
  `vault_list {folder:"Memory/voiceMemo", status:"draft"}` and surface
  "N voice records pending triage."
- **Vault `CLAUDE.md`:** one line noting `Memory/voiceMemo/` is a voice2note-owned
  freeform folder and `Ideas/` is the idea-note destination.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `SQLITE_BUSY` when the launchd write races an open agent session | WAL already serializes writers; voice2note retries the memo next run on any error. Hardening: add a `busy_timeout` pragma and one retry in voice2note's CLI-call wrapper. |
| launchd minimal PATH can't find `cricknote`/`node` | `VOICE2NOTE_CRICKNOTE_BIN` absolute path; set PATH in the LaunchAgent plist. Same pattern voice2note already uses for whisper/ffmpeg/codex. |
| Misclassification hides a record | Ambiguity rule biases low-confidence to `record`; conversation/talk are still listed in `Memory/voiceMemo/` so a wrong call is correctable by hand. |
| Hand-edits in Obsidian leave the index stale | Session-start `cricknote reindex` (already the daily-review convention). |
| Nutstore sync mid-write | Atomic tmp + rename; vault path never passed on a command line (CLI reads its own config), so the space in the path is irrelevant to shelling out. |
| Diary validation warnings on voice notes | Frontmatter includes `date` + `type` and a valid `status`, so no warnings. |

## 10. Configuration (new voice2note env)

| Variable | Default | Meaning |
|---|---|---|
| `VOICE2NOTE_USE_CRICKNOTE` | on if bin found | Route writes through `cricknote tool` vs. direct file write |
| `VOICE2NOTE_CRICKNOTE_BIN` | `which cricknote` | Absolute path to the CrickNote CLI |
| `VOICE2NOTE_MEMO_RELDIR` | `Memory/voiceMemo` | Vault-relative folder for voice notes |
| `VOICE2NOTE_CONFIDENCE_MIN` | `0.5` | Below this, force `recording_type: record` |

`VOICE2NOTE_VAULT` must equal the `vaultPath` in `~/.cricknote/config.json`.

## 11. Testing

- **voice2note (unittest):** `parse_analysis` extracts/defaults
  `recording_type` + `confidence`; ambiguity rule forces `record`; `routing.py`
  status/todos per type; `notes.py` renders the §6 frontmatter and never emits
  `- [ ]` lines; the CLI-writer builds the correct `cricknote tool vault_write`
  argv (subprocess mocked) and falls back to direct write when disabled.
- **CrickNote (vitest + temp vault):** a note written into `Memory/voiceMemo/`
  with `status:draft` is returned by the queue query and not by `task_list`;
  routing appends to an experiment / writes an `Ideas/` note / adds a task; the
  status flip removes it from the queue. Skills validated from the vault dir with
  both Claude Code and Codex.

## 12. Phases

1. **voice2note:** classification + ambiguity rule; §6 frontmatter; `routing.py`;
   create-only `cricknote tool vault_write` path with standalone fallback; drop
   daily block. Tests.
2. **CrickNote:** `cricknote-voice-inbox` skill + daily-review hook + CLAUDE.md
   line; validate against the real vault.
3. **Hardening:** `busy_timeout` + CLI-call retry; LaunchAgent PATH/bin; README
   updates in both repos.

## 13. Open questions

- None blocking. KB mapping stays out of the voice path by decision (§2); use
  `cricknote-kb-update` on a routed record later if wanted.
- A future enhancement could add a one-line linked summary into
  `Memory/Daily/<date>.md`, but it is deferred to keep Stage 1 strictly
  create-only (and because `vault_append` requires the daily note to already
  exist).
