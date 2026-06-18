"""Render Obsidian notes for voice memos. Writes go through the caller
(run.py → vault_writer or direct), not from here."""
import hashlib
import re

from voice2note.yamllite import dq, seq


def slugify(text, maxlen=50):
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "memo"


def source_hash(source_id, n=16):
    return hashlib.sha256((source_id or "").encode("utf-8")).hexdigest()[:n]


def memo_note_relpath(reldir, recorded_at, title, source_id):
    stamp = recorded_at.strftime("%Y-%m-%d-%H%M")
    return f"{reldir.rstrip('/')}/{stamp}-{slugify(title)}-{source_hash(source_id)}.md"


def render_memo_note(memo, analysis, transcript, *, recording_type, confidence,
                     status, analysis_status, include_todos):
    date = memo.recorded_at.strftime("%Y-%m-%d")
    topics = analysis.get("topics", [])
    fm = [
        "---",
        f"date: {date}",
        "type: voice-memo",
        f"source_id: {dq(memo.id)}",
        f"recording_type: {recording_type}",
        f"classify_confidence: {confidence}",
        f"analysis: {analysis_status}",
        f"status: {status}",
        "disposition:",
        "routed_to: []",
        "source: voice-memo",
        f"title: {dq(memo.title)}",
        f'recorded: "{memo.recorded_at.isoformat(timespec="minutes")}"',
        f"tags: {seq(['voice-memo'] + list(topics))}",
        "---",
    ]
    body = [f"# {memo.title}", "", "## Summary", analysis.get("summary") or "—"]
    if include_todos and analysis.get("action_items"):
        body += ["", "## Possible to-dos"]
        body += [f"- {item}" for item in analysis["action_items"]]
    topic_line = " ".join("#" + slugify(t, 40) for t in topics) or "—"
    body += ["", "## Topics", topic_line, "", "## Notable Details"]
    details = analysis.get("notable_details") or []
    body += [f"- {d}" for d in details] if details else ["- (none)"]
    body += ["", "## Transcript", "> [!quote]- Full transcript"]
    body += [f"> {line}" for line in (transcript or "").splitlines() or [""]]
    body.append("")
    return "\n".join(fm + [""] + body)
