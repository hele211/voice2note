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


_FM_LINE = re.compile(r'^([a-zA-Z_]+):\s*(.*)$')


def read_frontmatter(vault, rel_path):
    """Minimal frontmatter reader: returns scalar string fields from the leading
    --- block. Enough for the adopt check (source_id, analysis, recording_type)."""
    text = (Path(vault) / rel_path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = _FM_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out
