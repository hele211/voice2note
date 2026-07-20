# voice2note/vault_writer.py
"""Bridge to the CrickNote CLI for vault writes, plus direct-fs helpers for the
create-once adopt check. Never silently falls back to a direct write."""
import json
import re
import subprocess
from pathlib import Path


def build_write_cmd(cricknote_bin, rel_path, content):
    args = json.dumps({"path": rel_path, "content": content})
    return [cricknote_bin, "tool", "vault_write", args]


def write_note(cricknote_bin, rel_path, content, runner=subprocess.run):
    cmd = build_write_cmd(cricknote_bin, rel_path, content)
    proc = runner(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cricknote vault_write failed (exit {proc.returncode}): {(proc.stderr or '')[:300]}")
    return proc.stdout


def note_exists(vault, rel_path):
    return (Path(vault) / rel_path).exists()


# Matches a top-level "key: value" frontmatter line (precompiled; scanned per line).
_FM_LINE = re.compile(r'^([a-zA-Z_]+):\s*(.*)$')
_DQ_SIMPLE = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}


def _unescape_dq(body):
    """Reverse yamllite.dq escaping for a double-quoted scalar body (without the
    surrounding quotes): handles \\\\, \\", \\n, \\t, \\r, and \\xNN. Keeps this
    reader in sync with how notes.py writes values, so the adopt-check source_id
    comparison matches a value that contained a quote or backslash."""
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "x" and i + 3 < len(body):
                try:
                    out.append(chr(int(body[i + 2:i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            out.append(_DQ_SIMPLE.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scalar(raw):
    """Decode a frontmatter scalar: double-quoted (unescaped), single-quoted, or bare."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return _unescape_dq(raw[1:-1])
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def read_frontmatter(vault, rel_path):
    """Minimal frontmatter reader: returns scalar string fields from the leading
    --- block. Enough for the adopt check (source_id, analysis, recording_type).
    Returns {} if the note is missing or has no frontmatter block."""
    p = Path(vault) / rel_path
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = _FM_LINE.match(line)
        if m:
            out[m.group(1)] = _scalar(m.group(2))
    return out
