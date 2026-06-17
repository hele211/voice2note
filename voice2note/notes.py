"""Render and write Obsidian notes from a memo + its analysis."""
import re
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
