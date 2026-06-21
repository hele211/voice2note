# Phase 3 — voice2note ↔ CrickNote hardening and documentation plan

> **Status: Draft for review. Do not implement until the user approves this plan.**
>
> For implementation, execute the checked tasks in order. Keep changes small and
> verify each task before moving on.
>
> **Revisions (2026-06-20, review round 2):** folded in five reviewer notes, all
> verified against the code — (1) FDA precondition called out for the real-vault
> gate; (2) the §6.3 read-only manifest now scopes to `Memory/voiceMemo/` to avoid
> Nutstore sync-daemon noise; (3) §6.3 isolates config with a real empty file
> instead of `/dev/null` (which is not `is_file()`); (4) §5.2 whisper stub writes
> `<-of>.txt`; (5) `rg`→`grep` in verification snippets. Structure and scope
> unchanged.

**Goal:** Make the already-built voice2note↔CrickNote integration installable,
understandable, and demonstrably safe: wire the LaunchAgent explicitly, discover
the CrickNote CLI during installation, refresh configuration examples and both
READMEs, prove the write path in an isolated temporary vault, and run a read-only
configuration check against the real vault with
`VOICE2NOTE_USE_CRICKNOTE=true`.

**Architecture:** Phase 1 already supplies the integration engine in
`voice2note/config.py`, `voice2note/run.py`, and `voice2note/vault_writer.py`.
Phase 2 already supplies the human triage workflow in the CrickNote repo. Phase 3
does not change either engine. It exposes the existing configuration through the
generated plist, documents the existing behavior, and adds an executable smoke
test around the public command-line seam.

**Repositories:**

- voice2note source: `/Users/le211/voice2note`
- CrickNote source: `/Users/le211/crickNote`
- configured real vault: `/Users/le211/Nutstore Files/0 Obsidian/crickNote`

**Current evidence (2026-06-20):**

- voice2note is on `feat/cricknote-voice-integration`; its 80 unit tests pass.
- `/Users/le211/.npm-global/bin/cricknote` is the currently discovered CLI.
- `~/.cricknote/config.json` points at the real vault above.
- CrickNote Phase 2 is present in `/Users/le211/crickNote` through commit
  `2c9421b`, including `cricknote-voice-inbox` and its acceptance record.
- `voice2note.lock` is an existing untracked runtime file. Never add or remove it
  as part of this phase.

---

## Locked decisions

1. **Installer-time discovery, runtime-time explicitness.** `install.sh` may
   auto-detect `cricknote`, but it must write an explicit `true` or `false` into
   the plist. `config.py` remains explicit and unchanged.
2. **Standalone remains safe.** If auto-discovery finds no CLI, installation
   continues with `VOICE2NOTE_USE_CRICKNOTE=false` and prints a warning. If the
   user explicitly requests `true` but the binary is unavailable, installation
   fails instead of silently falling back.
3. **Real vault is read-only during Phase 3 verification.** Run `--check` against
   it. Never run `--once` against the real vault for this phase.
4. **The write smoke uses a temporary vault.** It runs the real voice2note entry
   point and the real installed CrickNote CLI. Only ffmpeg, Whisper, and Codex
   are replaced with deterministic local stubs so the smoke is fast and does not
   use audio, network access, or model credits.
5. **No `run.sh` behavior change.** It already adds the standard npm/local binary
   directories to `PATH`, exports `PYTHONPATH`, and delegates to `config.py`.
6. **No CrickNote engine changes.** In particular, no SQLite configuration,
   migration, pragma, or `busy_timeout` work belongs in this phase.

---

## Files in scope

| Repository | File | Action |
|---|---|---|
| voice2note | `com.voice2note.agent.plist.template` | Modify |
| voice2note | `scripts/install.sh` | Modify |
| voice2note | `tests/test_install.py` | Create |
| voice2note | `config.example.env` | Modify |
| voice2note | `README.md` | Modify |
| voice2note | `scripts/smoke-cricknote-integration.sh` | Create |
| voice2note | `docs/superpowers/plans/2026-06-20-voice2note-cricknote-phase3.md` | Plan only |
| CrickNote | `README.md` | Modify |

Files explicitly **not** in scope include `voice2note/config.py`,
`voice2note/run.py`, every file under `/Users/le211/crickNote/src/`, and all
database/migration files.

---

### Task 0: Establish clean execution branches and baselines

**Files:** None.

- [ ] In `/Users/le211/voice2note`, create the Phase 3 branch from the current
  `feat/cricknote-voice-integration` tip. Do not stage `voice2note.lock`.
- [ ] Run:

  ```bash
  PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t . -v
  ```

  Expected before changes: `Ran 80 tests` and `OK`.

- [ ] In `/Users/le211/crickNote`, create a small documentation branch from the
  current Phase 2 tip. Do not rewrite or squash the eight existing Phase 2
  commits on local `main`.
- [ ] Run the CrickNote baseline:

  ```bash
  npm run build
  npm test
  ```

- [ ] Stop before editing if either baseline is red for a reason unrelated to
  this phase. Record the failure instead of hiding it.

**Acceptance criteria:** Both repositories' starting commits and test results are
recorded; no implementation file has changed; `voice2note.lock` remains untracked.

---

### Task 1: Wire the plist and make `install.sh` discover CrickNote safely

**Files:**

- Modify: `com.voice2note.agent.plist.template`
- Modify: `scripts/install.sh`
- Create: `tests/test_install.py`

#### 1.1 Write installer tests first

Use Python's standard-library `unittest`, `tempfile`, `subprocess`, and
`plistlib`. Each test must give the installer a temporary `HOME` and a stub
`launchctl`, so tests never load or unload the user's real LaunchAgent.

Cover these cases:

- [ ] A fake executable `cricknote` on `PATH` produces a plist containing:
  `VOICE2NOTE_USE_CRICKNOTE=true`, an absolute
  `VOICE2NOTE_CRICKNOTE_BIN`, and
  `VOICE2NOTE_MEMO_RELDIR=Memory/voiceMemo`.
- [ ] The directory containing the detected binary is present in the generated
  plist `PATH`.
- [ ] No discoverable binary produces `VOICE2NOTE_USE_CRICKNOTE=false`, exits
  successfully, and prints a standalone-mode warning.
- [ ] Explicit `VOICE2NOTE_USE_CRICKNOTE=true` with no runnable binary exits
  nonzero and does not load a LaunchAgent.
- [ ] `--no-cricknote` wins even when a binary is discoverable.
- [ ] Values explicitly supplied in the process environment win over values in
  the selected config file; values in that file win over auto/default values.
- [ ] Running the installer twice overwrites the generated plist cleanly and
  leaves one valid plist, proving idempotent reinstall behavior.

#### 1.2 Add the plist environment keys

Under `EnvironmentVariables`, retain `PATH`, `PYTHONPATH`, and
`VOICE2NOTE_VAULT`, then add exactly:

- `VOICE2NOTE_USE_CRICKNOTE` → `__USE_CRICKNOTE__`
- `VOICE2NOTE_CRICKNOTE_BIN` → `__CRICKNOTE_BIN__`
- `VOICE2NOTE_MEMO_RELDIR` → `__MEMO_RELDIR__`

Do not add `busy_timeout` or any database variable.

#### 1.3 Implement installer resolution rules

Keep the existing vault argument working. Add `--no-cricknote` as an explicit
escape hatch. Read supported values from
`${VOICE2NOTE_CONFIG:-$PROJECT_DIR/voice2note.env}` without sourcing or executing
the file. This mirrors `config.py` and lets tests supply an isolated config file.

Use this precedence:

1. `--no-cricknote` forces standalone mode.
2. A value supplied in the installer process environment wins.
3. Otherwise, use the corresponding value from the selected config file when
   present.
4. Otherwise, auto-detect `cricknote` with `command -v`.

Concrete behavior:

- [ ] Accept the same common boolean spellings as `config.py` for explicit true
  values (`1`, `true`, `yes`, `on`), accept `0`, `false`, `no`, and `off` as
  explicit false values, and reject other non-empty values with a clear error.
- [ ] Default `VOICE2NOTE_MEMO_RELDIR` to `Memory/voiceMemo`.
- [ ] Resolve a supplied command name through `command -v`; retain an absolute,
  executable path in `VOICE2NOTE_CRICKNOTE_BIN`.
- [ ] When discovery succeeds and use was not explicitly disabled, set use to
  `true` and prepend the binary's directory to the plist `PATH` if it is absent.
- [ ] When automatic discovery fails, set use to `false`, keep installation
  successful, set the unused plist binary value to `cricknote`, and print how to
  install/configure CrickNote later.
- [ ] When use is explicitly `true` but the selected binary cannot be resolved
  to an executable, print an error and exit before writing/loading the plist.
- [ ] Replace all three new placeholders when generating the plist.
- [ ] Print the final mode, binary path (when enabled), memo folder, and plist
  `PATH` alongside the existing vault/Python/interval summary.

#### 1.4 Verify Task 1

Run:

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_install -v
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t . -v
```

Inspect a generated test plist with `plistlib`; no unresolved `__...__`
placeholder may remain.

**Acceptance criteria:** All installer tests pass; tests do not touch the real
`~/Library/LaunchAgents`; missing auto-detection stays standalone; explicit
misconfiguration fails closed.

---

### Task 2: Refresh `config.example.env`

**File:** Modify `config.example.env`.

- [ ] Remove the obsolete `VOICE2NOTE_MEMO_DIR` and
  `VOICE2NOTE_DAILY_DIR` examples. Those settings no longer exist in
  `config.py`.
- [ ] Add commented examples and beginner-friendly explanations for:

  ```dotenv
  # VOICE2NOTE_USE_CRICKNOTE=true
  # VOICE2NOTE_CRICKNOTE_BIN=/Users/you/.npm-global/bin/cricknote
  # VOICE2NOTE_MEMO_RELDIR=Memory/voiceMemo
  # VOICE2NOTE_CONFIDENCE_MIN=0.5
  ```

- [ ] Explain that `install.sh` auto-detects the CLI for the LaunchAgent, while
  manual `./run.sh` runs use the values loaded by `config.py`.
- [ ] Explain that enabling integration requires `VOICE2NOTE_VAULT` to resolve
  to the same path as `~/.cricknote/config.json`'s `vaultPath`.
- [ ] Keep `VOICE2NOTE_VAULT` as the only required setting for standalone mode.

Verification:

```bash
! grep -qE 'VOICE2NOTE_(MEMO_DIR|DAILY_DIR)' config.example.env
grep -qE 'VOICE2NOTE_(USE_CRICKNOTE|CRICKNOTE_BIN|MEMO_RELDIR|CONFIDENCE_MIN)' config.example.env
```

**Acceptance criteria:** The obsolete names are absent and all four current
Phase 1 settings are represented with their actual defaults.

---

### Task 3: Correct and expand the voice2note README

**File:** Modify `/Users/le211/voice2note/README.md`.

- [ ] Replace the stale `00_Journal/VoiceMemos` and daily-note description with
  the current single-note contract under `Memory/voiceMemo/`.
- [ ] State that conversation/talk notes are created as `complete`; record,
  uncertain, and analysis-failed notes are created as `draft` for triage.
- [ ] Update the workflow diagram: deterministic create-once note → optional
  `cricknote tool vault_write` → human `cricknote-voice-inbox` triage. Remove the
  daily-note append step.
- [ ] Add CrickNote as optional for standalone mode and required when
  `VOICE2NOTE_USE_CRICKNOTE=true`.
- [ ] In installation instructions, explain installer auto-discovery, the
  generated plist values, and the `--no-cricknote` escape hatch.
- [ ] Add an **Integration with CrickNote** section explaining:
  - the same-vault requirement;
  - the `Memory/voiceMemo/` handoff folder;
  - strict no-fallback behavior when integration is enabled;
  - how to ask an agent in the vault to run `cricknote-voice-inbox`;
  - that routing remains human-confirmed.
- [ ] Replace the configuration table's removed variables with
  `VOICE2NOTE_USE_CRICKNOTE`, `VOICE2NOTE_CRICKNOTE_BIN`,
  `VOICE2NOTE_MEMO_RELDIR`, and `VOICE2NOTE_CONFIDENCE_MIN` using the defaults
  from `config.py:96-99`.
- [ ] Add troubleshooting entries for a missing/unrunnable CrickNote binary and
  a vault mismatch.
- [ ] Keep the Full Disk Access explanation and standalone workflow accurate.

Verification:

```bash
! grep -qE '00_Journal/VoiceMemos|VOICE2NOTE_MEMO_DIR|VOICE2NOTE_DAILY_DIR|daily-note summary' README.md
grep -qE 'Memory/voiceMemo|VOICE2NOTE_USE_CRICKNOTE|cricknote-voice-inbox' README.md
```

**Acceptance criteria:** A beginner can follow either standalone or integrated
installation without knowing which values are implicit, and every documented
environment variable exists in `config.py`.

---

### Task 4: Add the voice inbox workflow to the CrickNote README

**File:** Modify `/Users/le211/crickNote/README.md` only.

- [ ] Add a short **Voice inbox** section after basic usage.
- [ ] Explain that voice2note creates capture notes under
  `Memory/voiceMemo/` and that `cricknote-voice-inbox` handles draft triage.
- [ ] Explain that `npm run setup` installs the skill into the configured vault.
- [ ] Give one beginner-facing action: open Claude Code or Codex in the vault and
  ask, “Triage my voice memos.”
- [ ] State that the workflow reindexes first and asks for confirmation before
  routing into experiments, ideas, or tasks, or dismissing/reclassifying.
- [ ] Link to the voice2note repository for capture-side setup.

Do not edit `src/`, storage code, migrations, or skill behavior in this task.

Verification:

```bash
grep -qE 'Voice inbox|Memory/voiceMemo|cricknote-voice-inbox|Triage my voice memos' README.md
git diff --name-only
```

Expected in the CrickNote repository: only `README.md` is changed by Phase 3.

**Acceptance criteria:** The CrickNote README tells a new user where voice notes
come from, how to invoke triage, and where to find capture setup.

---

### Task 5: Add an isolated end-to-end integration smoke

**File:** Create `scripts/smoke-cricknote-integration.sh`.

The smoke must be safe to run repeatedly and must never read or write the real
vault. Use `mktemp -d` plus a cleanup trap. Capture the absolute real
`cricknote` binary path before redirecting `HOME`.

#### 5.1 Build an isolated environment

- [ ] Create a temporary `HOME`, CrickNote data directory, vault, recordings
  directory, state file, log, and lock.
- [ ] Write the temporary CrickNote `config.json` with the temporary vault path.
- [ ] Export both `HOME` and `CRICKNOTE_DATA_DIR` so voice2note and the CrickNote
  CLI resolve the same isolated config.
- [ ] Export:

  ```text
  VOICE2NOTE_USE_CRICKNOTE=true
  VOICE2NOTE_CRICKNOTE_BIN=<absolute discovered CLI>
  VOICE2NOTE_MEMO_RELDIR=Memory/voiceMemo
  VOICE2NOTE_VAULT=<temporary vault>
  ```

  Also redirect `VOICE2NOTE_RECORDINGS`, `VOICE2NOTE_STATE`, `VOICE2NOTE_LOG`,
  and `VOICE2NOTE_LOCK` into the temporary root.

#### 5.2 Stub only the expensive upstream tools

- [ ] Seed one non-empty fake `.m4a` memo.
- [ ] Provide a fake ffmpeg executable that creates its requested WAV output.
- [ ] Provide a fake Whisper executable that writes a deterministic transcript
  to `<-of value>.txt`. The real command is built as `-otxt -of <prefix>`
  (`voice2note/transcribe.py:23-29`), so the transcript lands at `<prefix>.txt`,
  **not** at the bare `-of` path — the stub must add the `.txt` suffix.
- [ ] Provide a fake Codex executable that writes valid analysis JSON to the
  requested `-o` path with `recording_type: "record"` and a confidence above
  `0.5`.

Do **not** stub the CrickNote CLI.

#### 5.3 Run and assert the seam

- [ ] Run the real entry point:

  ```bash
  /usr/bin/python3 -m voice2note.run --once
  ```

- [ ] Assert exactly one Markdown note exists under
  `Memory/voiceMemo/`, its filename ends in the correct 16-hex source hash, and
  its frontmatter contains the expected `source_id`, `recording_type: record`,
  `analysis: complete`, and `status: draft`.
- [ ] Assert `state.json` records the memo.
- [ ] Run the real CLI's `cricknote reindex`, then call
  `vault_list` for `folder=Memory/voiceMemo,status=draft`; parse the JSON response
  and assert it returns the created path.
- [ ] Run voice2note `--once` again and assert the vault still contains exactly
  one memo note, proving the smoke is idempotent.
- [ ] Print a single clear `PASS` line and remove the temporary directory on
  success or failure.

**Acceptance criteria:** The smoke passes with
`VOICE2NOTE_USE_CRICKNOTE=true`, exercises the real voice2note process and real
CrickNote CLI, proves the draft reaches CrickNote's indexed inbox, and leaves the
real vault unchanged.

---

### Task 6: Final verification, including the real-vault read-only gate

#### 6.1 Automated checks

In `/Users/le211/voice2note`:

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t . -v
./scripts/smoke-cricknote-integration.sh
bash -n scripts/install.sh scripts/smoke-cricknote-integration.sh
```

In `/Users/le211/crickNote`:

```bash
npm run build
npm test
```

Run stale-document checks against the two user-facing READMEs and
`config.example.env`. Those files must not contain `VOICE2NOTE_MEMO_DIR`,
`VOICE2NOTE_DAILY_DIR`, or the old `00_Journal/VoiceMemos` output path. (The
historical spec and this plan may name them when explaining their removal.)

#### 6.2 Inspect a generated LaunchAgent

- [ ] Run the installer test harness with a known fake CrickNote path.
- [ ] Parse the plist and confirm its `EnvironmentVariables` contain all three
  integration keys with no unresolved placeholders.
- [ ] Confirm the binary directory is on the plist `PATH`.
- [ ] Confirm the test harness, not the real `launchctl`, handled loading.

#### 6.3 Run the real-vault check without writing to the vault

**Precondition (environment, not integration):** `--check` exits `0` only when
Full Disk Access is granted to `/usr/bin/python3`; otherwise `check_access` prints
`DENIED` and exits `1` (`voice2note/run.py:58-59`). If this gate fails, confirm FDA
**before** suspecting the integration wiring.

Use the vault path already configured by CrickNote and isolate the log in a
temporary file. Create a before/after manifest so the read-only claim is checked,
not assumed. Snapshot **only `Memory/voiceMemo/`** — the single subtree voice2note
could ever write — because a full-vault scan of a Nutstore-synced vault reports
sync-daemon mtime/size churn that is noise, not voice2note activity:

```bash
CRICKNOTE_BIN="$(command -v cricknote)"
REAL_VAULT="$(/usr/bin/python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".cricknote/config.json").read_text())["vaultPath"])')"
CHECK_LOG="$(mktemp)"
EMPTY_CFG="$(mktemp)"   # a real, EMPTY file — fully isolates from any project voice2note.env
                       # (VOICE2NOTE_CONFIG=/dev/null would NOT: /dev/null is not is_file(),
                       #  so config.py would fall through to PROJECT_DIR/voice2note.env)
BEFORE="$(mktemp)"
AFTER="$(mktemp)"
MEMO_DIR="$REAL_VAULT/Memory/voiceMemo"
find "$MEMO_DIR" -type f -exec stat -f '%N|%z|%m' {} \; 2>/dev/null | LC_ALL=C sort > "$BEFORE"
VOICE2NOTE_CONFIG="$EMPTY_CFG" \
VOICE2NOTE_USE_CRICKNOTE=true \
VOICE2NOTE_CRICKNOTE_BIN="$CRICKNOTE_BIN" \
VOICE2NOTE_MEMO_RELDIR=Memory/voiceMemo \
VOICE2NOTE_VAULT="$REAL_VAULT" \
VOICE2NOTE_LOG="$CHECK_LOG" \
./run.sh --check
find "$MEMO_DIR" -type f -exec stat -f '%N|%z|%m' {} \; 2>/dev/null | LC_ALL=C sort > "$AFTER"
diff -u "$BEFORE" "$AFTER" && echo "READ-ONLY-OK: Memory/voiceMemo unchanged"
rm -f "$CHECK_LOG" "$EMPTY_CFG" "$BEFORE" "$AFTER"
```

Required evidence:

- [ ] Command exits `0` (FDA precondition above satisfied).
- [ ] Output identifies the real vault.
- [ ] Output says the Voice Memos folder is readable.
- [ ] The `Memory/voiceMemo/` before/after `diff` is empty (`READ-ONLY-OK` printed);
  no memo-queue file changed during the check.
- [ ] Do not substitute `--once`; this gate is intentionally read-only.

#### 6.4 Scope audit

Review both diffs and prove:

- [ ] No `/Users/le211/crickNote/src/` file changed.
- [ ] No SQLite or migration file changed.
- [ ] `busy_timeout` appears only in this plan's out-of-scope statements, not in
  implementation or user documentation.
- [ ] `voice2note/config.py` and `voice2note/run.py` remain unchanged.
- [ ] The real-vault check used `VOICE2NOTE_USE_CRICKNOTE=true`.

---

## Definition of done

Phase 3 is complete only when all of the following evidence exists:

| Requirement | Proof |
|---|---|
| Plist integration variables | Parsed generated plist contains the three exact keys |
| CrickNote discovery | Installer tests cover found, missing, explicit true failure, and opt-out |
| Config example refresh | Current variables present; removed variables absent |
| voice2note README | Current folder, routing, install, config, and troubleshooting documented |
| CrickNote README | Voice inbox section and beginner invocation documented |
| Isolated write path | Temp-vault smoke passes through real CrickNote CLI and indexed draft queue |
| Real configuration | `./run.sh --check` exits 0 against the real vault with integration enabled |
| Real vault safety | Before/after evidence shows no vault file changed |
| Scope | No engine/database change; `busy_timeout` remains out of scope |

---

## Review gate

No implementation begins from this plan until the user chooses one of:

- **Approved** — execute Tasks 0–6 as written.
- **Revise** — update this document, then request review again.
- **Stop** — leave both repositories unchanged except for this plan file.
