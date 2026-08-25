"""Turn a transcript into structured analysis using the Claude Code CLI (`claude -p`).

Uses your existing Claude Code login — no API key needed. Non-interactive mode
(`-p`) prints the final response and exits; it also skips the workspace-trust
dialog and, run from a scratch cwd with no project permission grants, has no
way to execute tool calls even if it wanted to — the prompt is pure text
analysis, so none should be needed.
"""
import json
import subprocess
import tempfile

DEFAULT_MODEL = None  # let the CLI/account default decide unless overridden

PROMPT = """You are analyzing a personal voice memo. Read the transcript and respond \
with ONLY a JSON object (no prose, no code fences) using exactly these keys:
- "summary": a 2-4 sentence summary of what was said.
- "action_items": array of concrete to-dos or follow-ups mentioned (empty if none).
- "topics": array of 2-6 short topic labels (single words or short phrases).
- "notable_details": array of specific facts, names, numbers, or decisions worth keeping (empty if none).

Transcript:
\"\"\"
{transcript}
\"\"\"
"""


def build_prompt(transcript):
    return PROMPT.replace("{transcript}", transcript or "")


def parse_analysis(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    data = json.loads(text[start:end + 1])

    def as_list(key):
        return [str(x).strip() for x in data.get(key, []) if str(x).strip()]

    return {
        "summary": str(data.get("summary", "")).strip(),
        "action_items": as_list("action_items"),
        "topics": as_list("topics"),
        "notable_details": as_list("notable_details"),
    }


def build_claude_cmd(prompt, claude_bin="claude", model=None):
    cmd = [claude_bin]
    if model:
        cmd += ["--model", model]
    cmd += ["-p", prompt]
    return cmd


def analyze(transcript, claude_bin="claude", model=None, runner=subprocess.run):
    model = model or DEFAULT_MODEL
    cmd = build_claude_cmd(build_prompt(transcript), claude_bin, model)
    # stdin=DEVNULL is essential: without a TTY (detached / launchd), claude -p
    # would otherwise block forever waiting for stdin to close.
    # cwd=a fresh temp dir, not the vault: no project .claude/settings.json
    # there means no permission rule can pre-approve a tool call, so even if
    # the model tried to act on something (it shouldn't — the prompt is pure
    # text analysis) it would just be silently denied, not executed.
    proc = runner(cmd, capture_output=True, text=True, errors="replace", timeout=300,
                  stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed (exit {proc.returncode}): {(proc.stderr or '')[:300]}")
    content = proc.stdout
    if not content.strip():
        raise RuntimeError("claude returned an empty response")
    return parse_analysis(content)
