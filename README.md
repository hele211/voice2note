# voice2note

Turn your macOS **Voice Memos** into structured **Obsidian notes**, automatically.

voice2note watches your Voice Memos, transcribes new ones **locally** with
[whisper.cpp](https://github.com/ggerganov/whisper.cpp), then uses the
[Codex CLI](https://github.com/openai/codex) to write a clean analysis into your
vault — a summary, action items, topics, and notable details — every couple of
hours, with **no API key** (it uses your existing Codex/ChatGPT login).

## What you get, per memo

- A full note in your vault (e.g. `00_Journal/VoiceMemos/`): summary, action items
  as dated checkboxes, topic tags, notable details, and the complete transcript.
- A one-line linked summary + tasks appended under `## Voice Memos` in that day's
  daily note.

The above is the established **memo-first** behavior and remains the default. See
[Diary-first capture](#diary-first-capture-safe-opt-in) for an opt-in raw-capture
mode that does not call Codex or create per-memo notes during intake.

## How it works

```
launchd (every ~2h)  →  python -m voice2note.run
   find new memos (CloudRecordings.db)         [Full Disk Access]
   → copy audio out of the protected folder    [Python has FDA; ffmpeg doesn't]
   → ffmpeg → 16 kHz wav → whisper-cli          [local transcription]
   → codex exec (analysis → JSON)               [your Codex login, no API key]
   → write per-memo note + daily-note summary   [into your Obsidian vault]
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
| `VOICE2NOTE_MEMO_DIR` | `<vault>/00_Journal/VoiceMemos` | Per-memo notes folder |
| `VOICE2NOTE_DAILY_DIR` | `<vault>/00_Journal/Daily` | Daily-notes folder |
| `VOICE2NOTE_CAPTURE_MODE` | `memo-first` | `memo-first` (legacy analysis/per-memo-note flow) or `diary-first` (raw daily-diary capture; no Codex) |
| `VOICE2NOTE_MODEL` | `./models/ggml-small.bin` | whisper.cpp model file |
| `VOICE2NOTE_LANGUAGE` | `auto` | Transcription language (`auto`, `en`, `zh`, …) |
| `VOICE2NOTE_CODEX_MODEL` | `gpt-5.5` | Codex model for analysis |

Schedule frequency: `VOICE2NOTE_INTERVAL=<seconds> ./scripts/install.sh` (default 7200).

## Diary-first capture (safe opt-in)

Use this mode when a Voice Memo should first become a **verbatim, timestamped diary
capture**. It transcribes locally, writes the complete transcript to the daily note
for the memo's **recording date** (not its import date), and only then marks the memo
processed. It does **not** call Codex, create per-memo action items, make experiment
or project routing decisions, or change source audio.

Apple Watch recordings use the same path once iCloud has synced them into Voice Memos
on this Mac; voice2note reads the local Voice Memos/iCloud recording store on the Mac,
not the Watch directly.

For an existing installation, edit the already-used `voice2note.env`; **do not**
reinstall, delete notes, or reset `state.json`:

```bash
# Keep your own actual daily-note location explicit. Do not assume a crickNote
# Memory/Daily location unless this is the directory in your vault.
VOICE2NOTE_DAILY_DIR=/Users/you/path/to/ObsidianVault/Memory/Daily
VOICE2NOTE_CAPTURE_MODE=diary-first
```

`voice2note.env` is read by each existing scheduled invocation, so the next run uses
the mode without reinstalling the LaunchAgent. If your daily notes instead live in
the default `<vault>/00_Journal/Daily`, set only `VOICE2NOTE_CAPTURE_MODE=diary-first`.
The current implementation does not archive audio into the vault: each capture records
the truthful original Voice Memos path, and source audio is never altered. Existing
processed memo IDs remain processed when you opt in; diary-first does not reinterpret
or automatically backfill historic recordings.

Each daily note receives (or reuses) exactly one dedicated `## Voice Memo Inbox`
section. An entry has a stable, top-level deduplication marker and Obsidian block ID:

```markdown
<!-- voice2note:<first 16 lowercase hex chars of sha256(memo.id)> -->
> **14:32 — Voice Memo**
> **Source title:** …
> **Memo ID:** …
> **Recorded:** 2026-06-15T14:32:00
> **Source audio:** Original Voice Memos path (not archived): …
>
> **Transcript:**
> verbatim transcript text
^voice2note-<same 16 lowercase hex chars>
```

The marker and block ID are generated only from the source memo ID and are on their
own unquoted lines. All source metadata and transcript lines are literal Markdown
quotes, so dictation containing code fences, headings, or HTML comments cannot create
or suppress an entry. Repeated runs, including a retry after a diary write succeeded
but state persistence did not, recognize that marker and do not duplicate the capture.
Diary writes are locally locked and atomically replaced; existing daily-note content is
preserved and intake entries are inserted only under this dedicated heading.

`launchd` does not run a Mac while it is asleep. That is safe: on the next successful
voice2note run, every still-unprocessed Voice Memo is discovered and caught up using
its original recording timestamp.

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

## Development

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t .
```

No third-party Python packages — standard library only. External tools
(`whisper-cli`, `ffmpeg`, `codex`) are called as subprocesses.

## License

[MIT](LICENSE)
