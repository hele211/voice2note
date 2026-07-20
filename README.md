# voice2note

Turn your macOS **Voice Memos** into structured **Obsidian notes**, automatically.

voice2note watches your Voice Memos, transcribes new ones **locally** with
[whisper.cpp](https://github.com/ggerganov/whisper.cpp), then uses the
[Codex CLI](https://github.com/openai/codex) to write a clean analysis into your
vault — a summary, action items, topics, and notable details — every couple of
hours, with **no API key** (it uses your existing Codex/ChatGPT login).

## What you get, per memo

- **One Markdown note** per recording in `Memory/voiceMemo/` (configurable via
  `VOICE2NOTE_MEMO_RELDIR`).
- Filename: `<YYYY-MM-DD-HHMM>-<title-slug>-<16-hex-source-hash>.md`.
- Notes are **created once and never overwritten** (create-once / idempotent). If a
  note file already exists for a memo, voice2note verifies its `source_id` and adopts
  it; on a mismatch it raises rather than silently clobbering.
- **`status: complete`** — set for `conversation` and `talk` recordings (finalized,
  no to-dos generated).
- **`status: draft`** — set for `record` recordings, ambiguous classifications, any
  classification whose confidence is below `VOICE2NOTE_CONFIDENCE_MIN` (default 0.5),
  and any memo where analysis fails entirely (written as a transcript-only draft with
  `analysis: pending`). Draft notes wait in `Memory/voiceMemo/` for human triage via
  the `cricknote-voice-inbox` skill (see Integration with CrickNote below).

## How it works

```
launchd (every ~2h)  →  python -m voice2note.run
   find new memos (CloudRecordings.db)              [Full Disk Access]
   → copy audio out of the protected folder         [Python has FDA; ffmpeg doesn't]
   → ffmpeg → 16 kHz wav → whisper-cli              [local transcription]
   → codex exec (analysis → JSON)                   [your Codex login, no API key]
   → classify type + confidence                     [complete vs. draft status]
   → if you said “CrickNote please”: create a macOS Reminder or Calendar event
   → write single note (create-once, idempotent)
       standalone: direct file write into vault
       cricknote:  cricknote tool vault_write        [when USE_CRICKNOTE=true]
   → human triage: ask an agent to run
       cricknote-voice-inbox                         [routing is always human-confirmed]
   → record processed id (no duplicates)
```

Everything is local except the analysis step, which sends the **transcript text**
(not audio) to your configured Codex model.

## Requirements

- **macOS** (uses Voice Memos + `launchd`)
- **Python 3** (the system `/usr/bin/python3` is fine — standard library only)
- **whisper.cpp**: `brew install whisper-cpp`
- **ffmpeg**: `brew install ffmpeg`
- **Codex CLI**, logged in: `npm install -g @openai/codex` then `codex login`
- **CrickNote CLI** (optional for standalone; required when `VOICE2NOTE_USE_CRICKNOTE=true`):
  install from the [CrickNote project](https://github.com/hele211/cricknote) and ensure
  `cricknote` is on your `PATH`.

## Install

```bash
git clone https://github.com/hele211/voice2note.git
cd voice2note

# 1. Download a transcription model (~488 MB for "small")
./scripts/download-model.sh small

# 2. Point it at your vault
cp config.example.env voice2note.env
$EDITOR voice2note.env          # set VOICE2NOTE_VAULT=...

# 3. Sanity-check config + tools (no Voice Memos access yet — that's next)
PYTHONPATH=. /usr/bin/python3 -m voice2note.run --check

# 4. Install + start the background agent (every 2h, runs once immediately)
./scripts/install.sh
```

The installer (`scripts/install.sh`) auto-discovers the `cricknote` CLI and writes
explicit values into the generated LaunchAgent plist:

- It compares `VOICE2NOTE_VAULT` against `~/.cricknote/config.json` `vaultPath`
  (by realpath). If they match **and** the CLI is runnable, it installs with
  `VOICE2NOTE_USE_CRICKNOTE=true` and records `VOICE2NOTE_CRICKNOTE_BIN` and
  `VOICE2NOTE_MEMO_RELDIR` in the plist.
- If the vaults do **not** match, or the CLI is missing, it installs in standalone
  mode (`VOICE2NOTE_USE_CRICKNOTE=false`) and prints a warning.
- Pass `--no-cricknote` to force standalone even when a CrickNote CLI is discoverable.
- If you explicitly set `VOICE2NOTE_USE_CRICKNOTE=true` in your env but the CLI is
  not runnable or the vaults do not match, the installer **fails** — there is no
  silent downgrade.

### Grant Full Disk Access (required, one-time)

macOS protects the Voice Memos folder. The agent runs **Python directly** so the
grant applies to it:

1. **System Settings → Privacy & Security → Full Disk Access**
2. Click **+**, press **⌘⇧G**, paste `/usr/bin/python3`, open it, toggle it **on**.

Re-check with `PYTHONPATH=. /usr/bin/python3 -m voice2note.run --check` — once it
prints `OK: Recordings folder readable`, you're set. (Run it via `launchctl start
com.voice2note.agent` to see the agent itself pick it up.)

## Usage

```bash
launchctl start com.voice2note.agent      # process new memos right now
tail -f logs/run.log                       # watch progress
./scripts/uninstall.sh                     # stop & remove the schedule
```

## Configuration

Set in `voice2note.env` (or as environment variables). Only the vault is required.

| Variable | Default | Meaning |
|---|---|---|
| `VOICE2NOTE_VAULT` | _(required)_ | Path to your Obsidian vault |
| `VOICE2NOTE_MEMO_RELDIR` | `Memory/voiceMemo` | Per-memo notes folder, relative to vault |
| `VOICE2NOTE_MODEL` | `./models/ggml-small.bin` | whisper.cpp model file |
| `VOICE2NOTE_LANGUAGE` | `auto` | Transcription language (`auto`, `en`, `zh`, …) |
| `VOICE2NOTE_CODEX_MODEL` | `gpt-5.5` | Codex model for analysis |
| `VOICE2NOTE_CONFIDENCE_MIN` | `0.5` | Minimum classification confidence; below this the note is downgraded to `draft` |
| `VOICE2NOTE_USE_CRICKNOTE` | `false` | Route note writes through the CrickNote CLI instead of a direct file write |
| `VOICE2NOTE_CRICKNOTE_BIN` | _(auto-discovered)_ | Absolute path to the `cricknote` binary; defaults to `shutil.which("cricknote")` |
| `VOICE2NOTE_APPLE_AUTOMATION` | `false` | Enable explicitly spoken Apple Reminders/Calendar commands |
| `VOICE2NOTE_APPLE_REMINDERS_LIST` | default list | Optional exact Apple Reminders list name |
| `VOICE2NOTE_APPLE_CALENDAR` | first writable calendar | Optional exact Apple Calendar name |

Schedule frequency: `VOICE2NOTE_INTERVAL=<seconds> ./scripts/install.sh` (default 7200).

## Integration with CrickNote

CrickNote is an optional vault-management layer. When enabled, voice2note writes
notes through the CrickNote CLI rather than directly to the filesystem; in every
other way the notes are identical — same file, same frontmatter, same location under
`Memory/voiceMemo/`.

**Same-vault requirement.** `VOICE2NOTE_VAULT` must point to the same vault as
`~/.cricknote/config.json` `vaultPath` (compared by realpath). voice2note checks this
at startup and raises `SystemExit` if they differ.

**Strict no-fallback when integration is enabled.** If `VOICE2NOTE_USE_CRICKNOTE=true`
and the `cricknote` binary is not runnable, startup fails immediately. A per-memo
write failure also raises, so the memo is retried on the next run and never silently
dropped.

**Human triage via `cricknote-voice-inbox`.** Draft notes accumulate in
`Memory/voiceMemo/`. To triage them, open a Claude Code (or Codex) session inside
your Obsidian vault and ask the agent to run the `cricknote-voice-inbox` skill. The
skill reindexes the vault, shows you each draft, and asks for confirmation before
routing it to experiments, ideas, or tasks — or dismissing / reclassifying it.
**Routing is always human-confirmed; voice2note never routes automatically.**

**Enabling manually.** Add these lines to `voice2note.env`:

```
VOICE2NOTE_USE_CRICKNOTE=true
VOICE2NOTE_CRICKNOTE_BIN=/usr/local/bin/cricknote   # or wherever your binary lives
```

Then re-run `--check` to confirm the vault match and binary path are correct before
starting the agent.

## Apple Reminders and Calendar commands

Voice2Note can create items in the built-in **Apple Reminders** and **Apple
Calendar** apps. This is separate from CrickNote's Obsidian task list and is
off by default. To enable it, add this to `voice2note.env`:

```bash
VOICE2NOTE_APPLE_AUTOMATION=true
# Optional: choose specific destinations instead of the defaults.
# VOICE2NOTE_APPLE_REMINDERS_LIST=Reminders
# VOICE2NOTE_APPLE_CALENDAR=Calendar
```

Then speak the deliberate trigger **“CrickNote please”** in a Voice Memo. The
phrase is case-insensitive; “Crick Note please” and the common transcription
mistake “Cricket Note please” work too. Examples:

- “CrickNote please, remind me to email Sarah tomorrow at 9.” → a Reminder.
- “CrickNote please, meeting with Sarah this Friday at 2 pm for one hour.” → a
  Calendar event.

The analysis uses the meaning of the memo: tasks and follow-ups become
Reminders; appointments and meetings with a clear date and time become Calendar
events. It will not invent a time. A task without a stated time is still added
to Reminders, but without a timed notification. A date without a time is also a
Reminder, rather than an all-day Calendar event.

The first command causes macOS to ask for permission to control Reminders or
Calendar. Allow it. Each memo's created Apple item ID is saved before Voice2Note
marks the memo finished, so if the vault write is retried it will not create a
duplicate Apple item. The corresponding voice-memo note also shows the item
created under **Apple action**.

## Troubleshooting

- **`--check` says DENIED even after granting access.** The grant must be on the
  exact binary the agent runs (`/usr/bin/python3`). Running through a shell wrapper
  breaks it — that's why the LaunchAgent invokes Python directly. For manual
  `./run.sh` from Terminal, *Terminal* also needs Full Disk Access.
- **`whisper-cli ... Operation not permitted`.** ffmpeg/whisper can't open the
  protected file even when Python can; voice2note copies the audio to a temp file
  first, so this shouldn't happen — make sure you're on the latest version.
- **Codex hangs or errors.** voice2note runs `codex exec --ignore-user-config -m
  <model>` with `stdin` detached. `--ignore-user-config` avoids an invalid
  `service_tier` in some `~/.codex/config.toml` files; set `VOICE2NOTE_CODEX_MODEL`
  to a model your account supports.
- **`cricknote CLI is not runnable` at startup.** `VOICE2NOTE_USE_CRICKNOTE=true` but
  the binary cannot be found or executed. Either install the CrickNote CLI and ensure
  it is on your `PATH`, set `VOICE2NOTE_CRICKNOTE_BIN` to its absolute path, or set
  `VOICE2NOTE_USE_CRICKNOTE=false` to revert to standalone mode.
- **`VOICE2NOTE_VAULT does not match ~/.cricknote/config.json vaultPath`.** Both
  tools must point at the same vault directory (compared by realpath, so symlinks are
  resolved). Update `VOICE2NOTE_VAULT` in `voice2note.env` or reconfigure CrickNote
  so both agree, then re-run `--check`.

## Development

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t .
```

No third-party Python packages — standard library only. External tools
(`whisper-cli`, `ffmpeg`, `codex`) are called as subprocesses.

## License

[MIT](LICENSE)
