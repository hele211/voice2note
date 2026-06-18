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


def coerce_confidence(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, f))


def build_prompt(transcript):
    return PROMPT.replace("{transcript}", transcript or "")


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


def analyze(transcript, codex_bin="codex", model=None, runner=subprocess.run):
    model = model or DEFAULT_MODEL
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = build_codex_cmd(build_prompt(transcript), out_path, codex_bin, model)
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
