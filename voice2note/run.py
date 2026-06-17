"""Orchestrator: find new memos, transcribe, analyze, write notes, track state."""
import argparse
import logging
import os
import sys
from datetime import datetime

from voice2note import config
from voice2note.state import State
from voice2note.memos import find_new_memos, materialize
from voice2note.transcribe import transcribe
from voice2note.analyze import analyze
from voice2note.notes import write_memo_note, append_to_daily, memo_filename

log = logging.getLogger("voice2note")


def setup_logging():
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH), logging.StreamHandler()],
    )


def check_access():
    print(f"Vault:      {config.VAULT}")
    print(f"Model:      {config.WHISPER_MODEL_PATH}")
    try:
        names = os.listdir(config.RECORDINGS_DIR)
    except PermissionError:
        print("DENIED: Full Disk Access is not granted to this Python. See README step 1.")
        return False
    except FileNotFoundError:
        print(f"NOT FOUND: {config.RECORDINGS_DIR}")
        return False
    n = len([x for x in names if x.lower().endswith(".m4a")])
    print(f"OK: Recordings folder readable ({n} .m4a files found).")
    return True


def process_memo(memo, state):
    log.info("Processing %s (%s)", memo.title, memo.id)
    if not materialize(memo.path, brctl_bin=config.BRCTL_BIN):
        log.warning("Could not download %s from iCloud; will retry next run.", memo.id)
        return
    transcript = transcribe(memo.path, config.WHISPER_MODEL_PATH,
                            whisper_bin=config.WHISPER_CLI_BIN,
                            ffmpeg_bin=config.FFMPEG_BIN,
                            language=config.WHISPER_LANGUAGE)
    note_basename = memo_filename(memo.recorded_at, memo.title)[:-3]  # drop ".md"
    try:
        analysis = analyze(transcript, codex_bin=config.CODEX_BIN, model=config.CODEX_MODEL)
    except Exception as exc:
        log.warning("Analysis failed for %s (%s); writing transcript-only note, will retry.",
                    memo.id, exc)
        fallback = {"summary": "(Analysis pending — transcript only.)",
                    "action_items": [], "topics": [], "notable_details": []}
        write_memo_note(memo, fallback, transcript, config.MEMO_DIR)
        return  # not marked processed -> retried next run
    write_memo_note(memo, analysis, transcript, config.MEMO_DIR)
    append_to_daily(memo, analysis, note_basename, config.DAILY_DIR)
    state.mark_processed(memo.id)
    state.save(last_run=datetime.now().isoformat(timespec="seconds"))
    log.info("Done: %s", memo.id)


def run(once=False):
    if str(config.VAULT) in ("", ".", "/"):
        log.error("VOICE2NOTE_VAULT is not set — set it in voice2note.env or the LaunchAgent. See README.")
        return
    state = State(config.STATE_PATH)
    try:
        memos = find_new_memos(config.RECORDINGS_DIR, config.DB_PATH, state)
    except PermissionError:
        log.error("Full Disk Access not granted — cannot read Voice Memos. See README step 1.")
        return
    except FileNotFoundError:
        log.error("Recordings folder not found: %s", config.RECORDINGS_DIR)
        return
    if once:
        memos = memos[-1:]  # newest unprocessed only, for a quick test
    if not memos:
        log.info("No new memos.")
        return
    log.info("%d new memo(s) to process.", len(memos))
    for memo in memos:
        try:
            process_memo(memo, state)
        except Exception:
            log.exception("Failed on %s; leaving unprocessed for retry.", memo.id)
    state.save(last_run=datetime.now().isoformat(timespec="seconds"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze new Voice Memos into Obsidian.")
    parser.add_argument("--once", action="store_true",
                        help="Process only the newest unprocessed memo (for testing).")
    parser.add_argument("--check", action="store_true",
                        help="Check Full Disk Access and exit.")
    args = parser.parse_args(argv)
    setup_logging()
    if args.check:
        sys.exit(0 if check_access() else 1)
    run(once=args.once)


if __name__ == "__main__":
    main()
