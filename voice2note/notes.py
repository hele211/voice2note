"""Render and write Obsidian notes from a memo + its analysis."""
import fcntl
import hashlib
import html
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


def slugify(text, maxlen=50):
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "memo"


def tagify(topic):
    return "#" + slugify(topic, maxlen=40)


def memo_filename(recorded_at, title):
    return f"{recorded_at.strftime('%Y-%m-%d-%H%M')}-{slugify(title)}.md"


def diary_entry_token(memo_id):
    """Return a compact, stable, filename-safe identity for one source memo."""
    return hashlib.sha256(str(memo_id).encode("utf-8")).hexdigest()[:16]


def diary_entry_marker(memo_id):
    """Return the machine-readable, top-level marker used for diary deduplication."""
    return f"<!-- voice2note:{diary_entry_token(memo_id)} -->"


def diary_entry_block_id(memo_id):
    """Return the stable Obsidian block ID used to address a diary capture."""
    return f"^voice2note-{diary_entry_token(memo_id)}"


def _literal_markdown(text):
    """Escape text so quoted transcript content stays literal when Obsidian renders it."""
    text = html.escape(str(text), quote=False)
    for character in r"\`*_{}[]()#+-.!|~":
        text = text.replace(character, "\\" + character)
    return text


def _quoted_literal_lines(text):
    """Render every source line as a literal Markdown blockquote line."""
    lines = str(text if text is not None else "").splitlines()
    return ["> " + _literal_markdown(line) for line in lines] or ["> "]


def _one_line(text, default=""):
    """Keep source metadata to one quoted line even if a malformed title has newlines."""
    value = " ".join(str(text if text is not None else "").splitlines()).strip()
    return value or default


def render_diary_capture(memo, transcript):
    """Render a raw diary entry; transcript text is never analyzed or routed here.

    The unquoted marker and trailing block ID are deliberately the only top-level
    machine syntax. Source metadata and all transcript lines are quoted and escaped,
    so dictation cannot introduce headings, HTML markers, or additional entries.
    """
    title = _one_line(getattr(memo, "title", ""), "Voice Memo")
    recorded_at = memo.recorded_at
    recorded = recorded_at.isoformat(timespec="seconds")
    source_path = _one_line(getattr(memo, "path", ""), "(source path unavailable)")
    lines = [
        diary_entry_marker(memo.id),
        f"> **{recorded_at.strftime('%H:%M')} — Voice Memo**",
        "> **Source title:** " + _literal_markdown(title),
        "> **Memo ID:** " + _literal_markdown(memo.id),
        "> **Recorded:** " + _literal_markdown(recorded),
        "> **Source audio:** Original Voice Memos path (not archived): "
        + _literal_markdown(source_path),
        ">",
        "> **Transcript:**",
    ]
    lines.extend(_quoted_literal_lines(transcript))
    lines.append(diary_entry_block_id(memo.id))
    return "\n".join(lines)


def _daily_note_text(date_str):
    pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    return f"---\ndate: {date_str}\ntags:\n  - daily-note\n---\n# Daily Note: {pretty}\n"


def _atomic_write_text(path, text):
    """Replace a text file atomically after flushing its contents to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _daily_note_lock(path):
    """Serialize diary read-modify-write operations across local voice2note runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.voice2note.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _has_diary_entry(text, memo_id):
    """Match only our own unquoted marker, never marker-shaped dictation."""
    marker = re.escape(diary_entry_marker(memo_id))
    return re.search(rf"(?m)^{marker}[ \t]*$", text) is not None


def _insert_diary_entry(text, entry):
    """Place an entry immediately below its dedicated heading, never another section."""
    heading = "## Voice Memo Inbox"
    match = re.search(r"(?m)^## Voice Memo Inbox[ \t]*$", text)
    if match is None:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + "\n" + heading + "\n\n" + entry + "\n"
    # Newest-first insertion directly below the explicit inbox heading avoids
    # accidentally appending under a nested or unrelated heading later in the note.
    return text[:match.end()] + "\n\n" + entry + "\n" + text[match.end():]


def append_diary_capture(memo, transcript, daily_dir):
    """Idempotently append one raw transcript to its recording-date daily diary.

    This is intentionally separate from ``append_to_daily``: diary-first captures
    have no summary, tasks, topics, experiment routing, or Codex dependency.
    """
    date_str = memo.recorded_at.strftime("%Y-%m-%d")
    path = Path(daily_dir) / f"{date_str}.md"
    with _daily_note_lock(path):
        text = path.read_text(encoding="utf-8") if path.exists() else _daily_note_text(date_str)
        if _has_diary_entry(text, memo.id):
            return path
        _atomic_write_text(path, _insert_diary_entry(text, render_diary_capture(memo, transcript)))
    return path


def render_memo_note(memo, analysis, transcript):
    date = memo.recorded_at.strftime("%Y-%m-%d")
    time = memo.recorded_at.strftime("%H:%M")
    safe_title = (memo.title or "Voice Memo").replace('"', "'")
    fm_tags = ["voice-memo"] + [slugify(t, 40) for t in analysis["topics"]]
    topic_line = " ".join(tagify(t) for t in analysis["topics"]) or "—"

    out = ["---", f"date: {date}", f'time: "{time}"', "source: voice-memo",
           f'title: "{safe_title}"', "tags:"]
    out += [f"  - {t}" for t in fm_tags]
    out += ["---", f"# {memo.title}", "", "## Summary", analysis["summary"] or "—",
            "", "## Action Items"]
    if analysis["action_items"]:
        out += [f"- [ ] {item} 📅 {date}" for item in analysis["action_items"]]
    else:
        out.append("- (none)")
    out += ["", "## Topics", topic_line, "", "## Notable Details"]
    if analysis["notable_details"]:
        out += [f"- {d}" for d in analysis["notable_details"]]
    else:
        out.append("- (none)")
    out += ["", "## Transcript", "> [!quote]- Full transcript"]
    out += [f"> {line}" for line in (transcript or "").splitlines() or [""]]
    out.append("")
    return "\n".join(out)


def render_daily_block(memo, analysis, note_basename):
    date = memo.recorded_at.strftime("%Y-%m-%d")
    time = memo.recorded_at.strftime("%H:%M")
    summary = analysis["summary"] or "voice memo"
    lines = [f"- **{time} — {memo.title}** ([[{note_basename}|full note]]) — {summary}"]
    lines += [f"  - [ ] {item} 📅 {date}" for item in analysis["action_items"]]
    return "\n".join(lines)


def write_memo_note(memo, analysis, transcript, memo_dir):
    memo_dir = Path(memo_dir)
    memo_dir.mkdir(parents=True, exist_ok=True)
    path = memo_dir / memo_filename(memo.recorded_at, memo.title)
    path.write_text(render_memo_note(memo, analysis, transcript), encoding="utf-8")
    return path


def ensure_daily_note(daily_dir, date_str):
    daily_dir = Path(daily_dir)
    path = daily_dir / f"{date_str}.md"
    if not path.exists():
        daily_dir.mkdir(parents=True, exist_ok=True)
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
        path.write_text(
            f"---\ndate: {date_str}\ntags:\n  - daily-note\n---\n# Daily Note: {pretty}\n",
            encoding="utf-8",
        )
    return path


def append_to_daily(memo, analysis, note_basename, daily_dir):
    date_str = memo.recorded_at.strftime("%Y-%m-%d")
    path = ensure_daily_note(daily_dir, date_str)
    text = path.read_text(encoding="utf-8")
    if "## Voice Memos" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n## Voice Memos\n"
    if not text.endswith("\n"):
        text += "\n"
    text += render_daily_block(memo, analysis, note_basename) + "\n"
    path.write_text(text, encoding="utf-8")
    return path
