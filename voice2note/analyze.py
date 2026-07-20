"""Turn a transcript into structured analysis using the Codex CLI (`codex exec`).

Uses the existing Codex/ChatGPT login (~/.codex/auth.json) — no API key needed.
`--ignore-user-config` avoids the user's config.toml (which may carry an invalid
`service_tier` for ChatGPT-account auth); the model and reasoning effort are passed
explicitly. Low reasoning keeps each analysis fast (~25s) — memo analysis is simple.
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime

from voice2note.routing import VALID_TYPES

DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING = "low"

PROMPT = """You are analyzing a personal voice memo. Read the transcript and respond \
with ONLY a JSON object (no prose, no code fences) using exactly these keys:
- "summary": a 2-4 sentence summary of what was said.
- "action_items": array of concrete to-dos or follow-ups mentioned (empty if none).
- "topics": array of 2-6 short topic labels (single words or short phrases).
- "notable_details": array of specific facts, names, numbers, or decisions worth keeping (empty if none).
- "recording_type": one of "conversation" (a dialogue with other people), "talk" (a presentation you attended), or "record" (you dictating experiment notes, thoughts, or a new idea).
- "confidence": a number from 0 to 1 for how sure you are of "recording_type".

Transcript:
\"\"\"
{transcript}
\"\"\"
"""

APPLE_ACTION_PROMPT = """

This recording contains the spoken command "CrickNote please". Add exactly one
additional key:
- "apple_action": an object with "kind", "title", "remind_at", "start_at",
  "end_at", and "notes".

Choose "kind":
- "reminder" for a task, follow-up, or thing to do. Set "remind_at" to an ISO
  date and time only when the speaker stated a time; otherwise use null.
- "calendar" only for an appointment, meeting, or event with a clear date AND
  time. Use ISO date-times for "start_at" and (when stated) "end_at". If no end
  time was stated, use null; the app will make it one hour long.
- "none" if there is no clear request to create either item. Set every other
  field to null in that case.

Never invent a date, time, title, or duration. If a date is stated without a
time, use a reminder rather than a calendar event. The control phrase itself is
not part of the memo's subject.

Current local date and time: {current_time}
"""


def coerce_confidence(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, f))


def build_prompt(transcript, apple_automation_requested=False, current_time=None):
    prompt = PROMPT.replace("{transcript}", transcript or "")
    if apple_automation_requested:
        now = current_time or datetime.now().astimezone().isoformat(timespec="minutes")
        prompt += APPLE_ACTION_PROMPT.replace("{current_time}", str(now))
    return prompt


def parse_analysis(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    data = json.loads(text[start:end + 1])

    def as_list(key):
        return [str(x).strip() for x in data.get(key, []) if str(x).strip()]

    rtype = str(data.get("recording_type", "")).strip().lower()
    if rtype not in VALID_TYPES:
        rtype = "record"

    return {
        "summary": str(data.get("summary", "")).strip(),
        "action_items": as_list("action_items"),
        "topics": as_list("topics"),
        "notable_details": as_list("notable_details"),
        "recording_type": rtype,
        "confidence": coerce_confidence(data.get("confidence")),
        "apple_action": parse_apple_action(data.get("apple_action")),
    }


def parse_apple_action(value):
    """Return a small, predictable action object from model output.

    The operating-system integration validates date-times again before creating
    anything. This parser deliberately treats malformed or incomplete model
    output as "none", rather than guessing what the speaker intended.
    """
    empty = {
        "kind": "none", "title": None, "remind_at": None,
        "start_at": None, "end_at": None, "notes": None,
    }
    if not isinstance(value, dict):
        return empty
    kind = str(value.get("kind", "none")).strip().lower()
    if kind not in ("none", "reminder", "calendar"):
        return empty

    def optional_text(key, max_length=2000):
        item = value.get(key)
        if item is None:
            return None
        text = str(item).strip()
        return text[:max_length] if text else None

    title = optional_text("title", 300)
    if kind != "none" and not title:
        return empty
    return {
        "kind": kind,
        "title": title,
        "remind_at": optional_text("remind_at", 80),
        "start_at": optional_text("start_at", 80),
        "end_at": optional_text("end_at", 80),
        "notes": optional_text("notes", 4000),
    }


def build_codex_cmd(prompt, out_path, codex_bin="codex", model=DEFAULT_MODEL,
                    reasoning=DEFAULT_REASONING, cwd=None):
    return [
        codex_bin, "exec",
        "--ignore-user-config",
        "-m", model,
        "-c", f"model_reasoning_effort={reasoning}",
        "--skip-git-repo-check",
        "--ephemeral",
        "-s", "read-only",
        "-C", cwd or tempfile.gettempdir(),
        "-o", out_path,
        prompt,
    ]


def analyze(transcript, codex_bin="codex", model=None, runner=subprocess.run,
            apple_automation_requested=False, current_time=None):
    model = model or DEFAULT_MODEL
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        prompt = build_prompt(transcript, apple_automation_requested, current_time)
        cmd = build_codex_cmd(prompt, out_path, codex_bin, model)
        # stdin=DEVNULL is essential: `codex exec` reads piped stdin if present, so
        # without a TTY (detached / launchd) it would block forever waiting for EOF.
        proc = runner(cmd, capture_output=True, text=True, errors="replace", timeout=300,
                      stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f"codex failed (exit {proc.returncode}): {(proc.stderr or '')[:300]}")
        with open(out_path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
    if not content.strip():
        raise RuntimeError("codex returned an empty response")
    return parse_analysis(content)
