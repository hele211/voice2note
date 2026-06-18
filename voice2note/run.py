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
from voice2note.notes import memo_note_relpath, render_memo_note
from voice2note.routing import effective_type, route_for
from voice2note.vault_writer import write_note, note_exists, read_frontmatter
from voice2note.lock import SingleInstanceLock, AlreadyRunning

log = logging.getLogger("voice2note")


def setup_logging():
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH), logging.StreamHandler()],
    )


def vault_check_ok(cfg):
    """Return True if vault config is consistent. Only validates the cricknote
    vault match when USE_CRICKNOTE is true; standalone needs no cricknote config."""
    if not cfg.USE_CRICKNOTE:
        return True
    cfg.assert_vault_match(str(cfg.VAULT), cfg.cricknote_vault_path())
    return True


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
    if not vault_check_ok(config):
        return False
    return True


def write_memo(cfg, rel, content):
    if cfg.USE_CRICKNOTE:
        write_note(cfg.CRICKNOTE_BIN, rel, content)  # raises → retried next run
    else:
        path = cfg.VAULT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def process_memo(memo, state, cfg):
    if state.is_seen(memo.id):
        return
    rel = memo_note_relpath(cfg.MEMO_RELDIR, memo.recorded_at, memo.title, memo.id)

    # Create-once: adopt an existing note (after verifying source_id), never overwrite.
    if note_exists(cfg.VAULT, rel):
        fm = read_frontmatter(cfg.VAULT, rel)
        if fm.get("source_id") != memo.id:
            raise RuntimeError(
                f"{rel} exists with source_id {fm.get('source_id')!r}, expected {memo.id!r}")
        state.record(memo.id, rel, fm.get("analysis", "complete"),
                     fm.get("recording_type", "record"))
        state.save()
        return

    if not materialize(memo.path, brctl_bin=config.BRCTL_BIN):
        log.warning("Could not download %s; will retry next run.", memo.id)
        return
    transcript = transcribe(memo.path, config.WHISPER_MODEL_PATH,
                            whisper_bin=config.WHISPER_CLI_BIN,
                            ffmpeg_bin=config.FFMPEG_BIN,
                            language=config.WHISPER_LANGUAGE)
    try:
        analysis = analyze(transcript, codex_bin=config.CODEX_BIN, model=config.CODEX_MODEL)
        rtype = effective_type(analysis["recording_type"], analysis["confidence"], cfg.CONFIDENCE_MIN)
        status, include_todos = route_for(rtype)
        content = render_memo_note(memo, analysis, transcript, recording_type=rtype,
                                   confidence=analysis["confidence"], status=status,
                                   analysis_status="complete", include_todos=include_todos)
        analysis_status = "complete"
    except Exception as exc:
        log.warning("Analysis failed for %s (%s); writing transcript-only draft.", memo.id, exc)
        empty = {"summary": "", "action_items": [], "topics": [], "notable_details": []}
        content = render_memo_note(memo, empty, transcript, recording_type="record",
                                   confidence=0.0, status="draft",
                                   analysis_status="pending", include_todos=False)
        rtype, analysis_status = "record", "pending"

    write_memo(cfg, rel, content)
    state.record(memo.id, rel, analysis_status, rtype)
    state.save(last_run=datetime.now().isoformat(timespec="seconds"))


def run(once=False):
    cfg = config
    if str(cfg.VAULT) in ("", ".", "/"):
        log.error("VOICE2NOTE_VAULT is not set. See README.")
        return
    if cfg.USE_CRICKNOTE:
        config.assert_vault_match(str(cfg.VAULT), config.cricknote_vault_path())
    try:
        with SingleInstanceLock(config.LOCK_PATH):
            _run_locked(once)
    except AlreadyRunning:
        log.info("Another voice2note run is active; exiting.")


def _run_locked(once):
    state = State(config.STATE_PATH)
    try:
        memos = find_new_memos(config.RECORDINGS_DIR, config.DB_PATH, state)
    except PermissionError:
        log.error("Full Disk Access not granted. See README step 1.")
        return
    except FileNotFoundError:
        log.error("Recordings folder not found: %s", config.RECORDINGS_DIR)
        return
    if once:
        memos = memos[-1:]
    if not memos:
        log.info("No new memos.")
        return
    log.info("%d new memo(s) to process.", len(memos))
    for memo in memos:
        try:
            process_memo(memo, state, config)
        except Exception:
            log.exception("Failed on %s; leaving for retry.", memo.id)
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
