# voice2note → CrickNote Phase 1 (voice2note engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make voice2note classify each Voice Memo (conversation | talk | record), write exactly one summary+transcript note into the vault's `Memory/voiceMemo/` folder (via the CrickNote CLI when enabled, else standalone), and queue `record`-type memos for later triage — all crash-safe and write-once.

**Architecture:** Pure-policy modules (`routing.py`, `yamllite.py`) and a v2 `state.json` underpin a create-once flow in `run.py`: under a mandatory single-instance lock, each memo's note is created at a deterministic `source_id`-derived path; an existing path is adopted (after verifying `source_id`) rather than overwritten. Writes go through `cricknote tool vault_write` (or direct file write in standalone mode). No CrickNote engine code is touched in this phase.

**Tech Stack:** Python 3 standard library only (no third-party packages). Tests use `unittest`. External tools (`whisper-cli`, `ffmpeg`, `codex`, `cricknote`) are invoked as subprocesses and mocked in tests.

**Scope:** This plan is Phase 1 (the `voice2note` repo) from the r4 spec (`docs/superpowers/specs/2026-06-18-voice2note-cricknote-integration-design.md`). Phase 2 (the `cricknote-voice-inbox` skill + agent-doc templates, validated by manual acceptance tests) and Phase 3 (LaunchAgent/docs) get their own plans.

**Conventions:**
- Run all tests: `PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t . -v`
- Run one module: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_routing -v`
- Run one test: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_routing.TestRouteFor.test_record -v`

---

### Task 1: Routing policy (`routing.py`)

Pure functions mapping a recording type to its note disposition, and applying the bias-to-`record` ambiguity rule. No dependencies.

**Files:**
- Create: `voice2note/routing.py`
- Test: `tests/test_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routing.py
import unittest
from voice2note.routing import route_for, effective_type, VALID_TYPES


class TestRouteFor(unittest.TestCase):
    def test_record(self):
        self.assertEqual(route_for("record"), ("draft", True))

    def test_conversation(self):
        self.assertEqual(route_for("conversation"), ("complete", False))

    def test_talk(self):
        self.assertEqual(route_for("talk"), ("complete", False))

    def test_unknown_defaults_to_record_disposition(self):
        self.assertEqual(route_for("weird"), ("draft", True))


class TestEffectiveType(unittest.TestCase):
    def test_keeps_confident_type(self):
        self.assertEqual(effective_type("talk", 0.9, 0.5), "talk")

    def test_low_confidence_forces_record(self):
        self.assertEqual(effective_type("talk", 0.4, 0.5), "record")

    def test_invalid_type_forces_record(self):
        self.assertEqual(effective_type("podcast", 0.99, 0.5), "record")

    def test_valid_types(self):
        self.assertEqual(VALID_TYPES, ("conversation", "talk", "record"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_routing -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice2note.routing'`

- [ ] **Step 3: Write minimal implementation**

```python
# voice2note/routing.py
"""Pure routing policy: recording_type → note disposition, plus the
bias-to-record ambiguity rule. No I/O, no dependencies."""

VALID_TYPES = ("conversation", "talk", "record")


def effective_type(recording_type, confidence, min_confidence):
    """Apply the ambiguity rule: an invalid type or sub-threshold confidence
    becomes 'record' (so it is queued for triage, never silently shelved)."""
    if recording_type not in VALID_TYPES:
        return "record"
    if confidence < min_confidence:
        return "record"
    return recording_type


def route_for(recording_type):
    """Return (status, include_todos) for a recording_type.
    conversation/talk → finalized, no tasks; everything else → draft + todos."""
    if recording_type in ("conversation", "talk"):
        return ("complete", False)
    return ("draft", True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_routing -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/routing.py tests/test_routing.py
git commit -m "feat(routing): recording-type disposition + ambiguity rule"
```

---

### Task 2: YAML scalar escaper (`yamllite.py`)

A minimal, stdlib-only emitter for YAML double-quoted scalars and flow sequences, so frontmatter `title`/`tags` can't break parsing.

**Files:**
- Create: `voice2note/yamllite.py`
- Test: `tests/test_yamllite.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yamllite.py
import unittest
from voice2note.yamllite import dq, seq


class TestDq(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(dq("hello"), '"hello"')

    def test_colon_is_safe_when_quoted(self):
        self.assertEqual(dq("a: b"), '"a: b"')

    def test_escapes_double_quote(self):
        self.assertEqual(dq('say "hi"'), '"say \\"hi\\""')

    def test_escapes_backslash(self):
        self.assertEqual(dq("a\\b"), '"a\\\\b"')

    def test_collapses_newline(self):
        self.assertEqual(dq("line1\nline2"), '"line1\\nline2"')

    def test_control_char_hex(self):
        self.assertEqual(dq("a\x01b"), '"a\\x01b"')

    def test_emoji_preserved(self):
        self.assertEqual(dq("🎙 memo"), '"🎙 memo"')

    def test_none(self):
        self.assertEqual(dq(None), '""')


class TestSeq(unittest.TestCase):
    def test_flow_sequence(self):
        self.assertEqual(seq(["voice-memo", "qpcr"]), '["voice-memo", "qpcr"]')

    def test_empty(self):
        self.assertEqual(seq([]), "[]")

    def test_quotes_each_item(self):
        self.assertEqual(seq(['a:b', 'c']), '["a:b", "c"]')


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_yamllite -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice2note.yamllite'`

- [ ] **Step 3: Write minimal implementation**

```python
# voice2note/yamllite.py
"""Minimal YAML emitter (stdlib only): double-quoted scalars and flow
sequences, enough to serialize frontmatter values safely. We never parse
YAML here — CrickNote's gray-matter does — we only need valid output."""

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def dq(value):
    """Return value as a YAML double-quoted scalar, fully escaped."""
    s = "" if value is None else str(value)
    out = []
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\x%02x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def seq(values):
    """Return a YAML flow sequence of double-quoted scalars."""
    return "[" + ", ".join(dq(v) for v in values) + "]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_yamllite -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/yamllite.py tests/test_yamllite.py
git commit -m "feat(yamllite): stdlib YAML double-quoted scalar escaper"
```

---

### Task 3: Classification parsing (`analyze.py`)

Extend the Codex prompt and `parse_analysis` to also return `recording_type` and a clamped `confidence`. Invalid types default to `record`; garbage confidence clamps to a safe default.

**Files:**
- Modify: `voice2note/analyze.py` (PROMPT, `parse_analysis`; add `coerce_confidence`)
- Test: `tests/test_analyze.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_analyze.py`:

```python
from voice2note.analyze import coerce_confidence


class TestRecordingType(unittest.TestCase):
    def _parse(self, **extra):
        import json
        from voice2note.analyze import parse_analysis
        payload = {"summary": "s", "action_items": [], "topics": [],
                   "notable_details": []}
        payload.update(extra)
        return parse_analysis(json.dumps(payload))

    def test_extracts_recording_type(self):
        self.assertEqual(self._parse(recording_type="talk")["recording_type"], "talk")

    def test_missing_type_defaults_record(self):
        self.assertEqual(self._parse()["recording_type"], "record")

    def test_invalid_type_defaults_record(self):
        self.assertEqual(self._parse(recording_type="podcast")["recording_type"], "record")

    def test_confidence_extracted(self):
        self.assertEqual(self._parse(confidence=0.8)["confidence"], 0.8)


class TestCoerceConfidence(unittest.TestCase):
    def test_numeric_string(self):
        self.assertEqual(coerce_confidence("0.8"), 0.8)

    def test_garbage_defaults_zero(self):
        self.assertEqual(coerce_confidence("high"), 0.0)

    def test_missing_defaults_zero(self):
        self.assertEqual(coerce_confidence(None), 0.0)

    def test_clamps_high(self):
        self.assertEqual(coerce_confidence(1.5), 1.0)

    def test_clamps_low(self):
        self.assertEqual(coerce_confidence(-2), 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_analyze -v`
Expected: FAIL with `ImportError: cannot import name 'coerce_confidence'`

- [ ] **Step 3: Write minimal implementation**

In `voice2note/analyze.py`, update the PROMPT to request the new keys (add these two bullet lines before the `Transcript:` line):

```python
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
```

Add `coerce_confidence` and extend `parse_analysis`'s return dict:

```python
from voice2note.routing import VALID_TYPES


def coerce_confidence(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, f))
```

In `parse_analysis`, after the existing `as_list` definitions, compute and add the fields:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_analyze -v`
Expected: PASS (existing tests + 9 new)

- [ ] **Step 5: Commit**

```bash
git add voice2note/analyze.py tests/test_analyze.py
git commit -m "feat(analyze): classify recording_type + confidence"
```

---

### Task 4: Deterministic path + note rendering (`notes.py`)

Add a `source_id`-derived deterministic note path and render the §6 frontmatter (via `yamllite`) and body — with no dated checkboxes. Remove the daily-note block helpers.

**Files:**
- Modify: `voice2note/notes.py` (add `source_hash`, `memo_note_relpath`, `render_memo_note`; remove `render_daily_block`, `ensure_daily_note`, `append_to_daily`, and the old `write_memo_note`/`render_memo_note` checkbox logic)
- Test: `tests/test_notes.py` (replace daily/checkbox tests)

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_notes.py` with:

```python
# tests/test_notes.py
import unittest
from datetime import datetime
from types import SimpleNamespace

from voice2note.notes import source_hash, memo_note_relpath, render_memo_note


def memo(title="Lysis ideas", mid="ABCD-1234.m4a"):
    return SimpleNamespace(id=mid, title=title,
                           recorded_at=datetime(2026, 6, 18, 14, 32))


ANALYSIS = {"summary": "Did the lysis.", "action_items": ["order ECL"],
            "topics": ["western-blot"], "notable_details": ["pH 7.4"],
            "recording_type": "record", "confidence": 0.9}


class TestPath(unittest.TestCase):
    def test_hash_is_16_hex_and_stable(self):
        h = source_hash("ABCD-1234.m4a")
        self.assertEqual(len(h), 16)
        self.assertEqual(h, source_hash("ABCD-1234.m4a"))

    def test_relpath_shape(self):
        p = memo_note_relpath("Memory/voiceMemo", memo().recorded_at,
                              "Lysis ideas", "ABCD-1234.m4a")
        self.assertTrue(p.startswith("Memory/voiceMemo/2026-06-18-1432-lysis-ideas-"))
        self.assertTrue(p.endswith(".md"))

    def test_same_minute_title_different_id_no_collision(self):
        a = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "X", "a.m4a")
        b = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "X", "b.m4a")
        self.assertNotEqual(a, b)


class TestRender(unittest.TestCase):
    def test_record_has_frontmatter_and_no_checkboxes(self):
        out = render_memo_note(memo(), ANALYSIS, "raw transcript",
                               recording_type="record", confidence=0.9,
                               status="draft", analysis_status="complete",
                               include_todos=True)
        self.assertIn("recording_type: record", out)
        self.assertIn("status: draft", out)
        self.assertIn("analysis: complete", out)
        self.assertIn('source_id: "ABCD-1234.m4a"', out)
        self.assertNotIn("- [ ]", out)
        self.assertIn("## Possible to-dos", out)
        self.assertIn("- order ECL", out)
        self.assertIn("raw transcript", out)

    def test_conversation_omits_todos(self):
        out = render_memo_note(memo(), ANALYSIS, "t",
                               recording_type="conversation", confidence=0.9,
                               status="complete", analysis_status="complete",
                               include_todos=False)
        self.assertNotIn("## Possible to-dos", out)

    def test_title_with_quote_is_escaped(self):
        out = render_memo_note(memo(title='He said "go"'), ANALYSIS, "t",
                               recording_type="record", confidence=0.9,
                               status="draft", analysis_status="complete",
                               include_todos=True)
        self.assertIn('title: "He said \\"go\\""', out)

    def test_transcript_only_pending(self):
        empty = {"summary": "", "action_items": [], "topics": [],
                 "notable_details": [], "recording_type": "record", "confidence": 0.0}
        out = render_memo_note(memo(), empty, "just the words",
                               recording_type="record", confidence=0.0,
                               status="draft", analysis_status="pending",
                               include_todos=True)
        self.assertIn("analysis: pending", out)
        self.assertIn("just the words", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_notes -v`
Expected: FAIL with `ImportError: cannot import name 'source_hash'`

- [ ] **Step 3: Write minimal implementation**

Rewrite `voice2note/notes.py` to:

```python
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
        f"recorded: {memo.recorded_at.isoformat(timespec='minutes')}",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_notes -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/notes.py tests/test_notes.py
git commit -m "feat(notes): deterministic path + frontmatter render, no checkboxes/daily block"
```

---

### Task 5: v2 state with atomic save (`state.py`)

Replace the `processed_ids` set with a `source_id → record` map (migrating old files), add `is_seen`/`record`, and make `save` atomic via `os.replace`.

**Files:**
- Modify: `voice2note/state.py`
- Test: `tests/test_state.py` (extend/replace)

- [ ] **Step 1: Write the failing test**

Replace `tests/test_state.py` with:

```python
# tests/test_state.py
import json
import os
import tempfile
import unittest
from pathlib import Path

from voice2note.state import State


class TestState(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "state.json"

    def test_record_and_is_seen(self):
        s = State(self.path)
        self.assertFalse(s.is_seen("a.m4a"))
        s.record("a.m4a", "Memory/voiceMemo/x.md", "complete", "record")
        self.assertTrue(s.is_seen("a.m4a"))

    def test_migrates_processed_ids(self):
        self.path.write_text(json.dumps({"processed_ids": ["a.m4a", "b.m4a"]}),
                             encoding="utf-8")
        s = State(self.path)
        self.assertTrue(s.is_seen("a.m4a"))
        self.assertEqual(s.memos["a.m4a"]["analysis"], "complete")

    def test_save_roundtrip(self):
        s = State(self.path)
        s.record("a.m4a", "Memory/voiceMemo/x.md", "pending", "record")
        s.save(last_run="2026-06-18T14:00:00")
        again = State(self.path)
        self.assertTrue(again.is_seen("a.m4a"))
        self.assertEqual(again.last_run, "2026-06-18T14:00:00")

    def test_save_is_atomic_on_failure(self):
        self.path.write_text(json.dumps({"memos": {"old.m4a": {"analysis": "complete"}}}),
                             encoding="utf-8")
        s = State(self.path)
        s.record("new.m4a", "Memory/voiceMemo/n.md", "complete", "record")
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated crash during replace")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                s.save()
        finally:
            os.replace = real_replace
        # Original file must be intact (not truncated/corrupted).
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("old.m4a", data["memos"])
        self.assertNotIn("new.m4a", data["memos"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_state -v`
Expected: FAIL (`AttributeError: 'State' object has no attribute 'is_seen'`)

- [ ] **Step 3: Write minimal implementation**

Rewrite `voice2note/state.py`:

```python
"""Tracks which memos have been handled (write-once), keyed by source_id.
Saved atomically so a crash mid-write can't corrupt the file."""
import json
import os
from datetime import datetime
from pathlib import Path


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.memos = {}
        self.last_run = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data.get("memos"), dict):
                self.memos = data["memos"]
            elif isinstance(data.get("processed_ids"), list):  # migrate v1
                self.memos = {mid: {"analysis": "complete"} for mid in data["processed_ids"]}
            self.last_run = data.get("last_run")

    def is_seen(self, source_id):
        return source_id in self.memos

    def record(self, source_id, note_rel, analysis, recording_type):
        self.memos[source_id] = {
            "note_rel": note_rel,
            "analysis": analysis,
            "recording_type": recording_type,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }

    def save(self, last_run=None):
        if last_run is not None:
            self.last_run = last_run
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps({"memos": self.memos, "last_run": self.last_run}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_state -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/state.py tests/test_state.py
git commit -m "feat(state): v2 source_id map, migration, atomic save"
```

---

### Task 6: Single-instance lock (`lock.py`)

A mandatory `fcntl.flock` lock so a manual run can't race a scheduled one.

**Files:**
- Create: `voice2note/lock.py`
- Test: `tests/test_lock.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lock.py
import tempfile
import unittest
from pathlib import Path

from voice2note.lock import SingleInstanceLock, AlreadyRunning


class TestLock(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "v2n.lock"

    def test_second_acquire_raises(self):
        first = SingleInstanceLock(self.path)
        first.acquire()
        try:
            with self.assertRaises(AlreadyRunning):
                SingleInstanceLock(self.path).acquire()
        finally:
            first.release()

    def test_release_allows_reacquire(self):
        a = SingleInstanceLock(self.path)
        a.acquire()
        a.release()
        b = SingleInstanceLock(self.path)
        b.acquire()  # should not raise
        b.release()

    def test_context_manager(self):
        with SingleInstanceLock(self.path):
            with self.assertRaises(AlreadyRunning):
                SingleInstanceLock(self.path).acquire()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_lock -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice2note.lock'`

- [ ] **Step 3: Write minimal implementation**

```python
# voice2note/lock.py
"""Mandatory single-instance lock (fcntl.flock). launchd only serializes its
own scheduled runs; a manual run could otherwise race it and double-write."""
import fcntl
from pathlib import Path


class AlreadyRunning(Exception):
    pass


class SingleInstanceLock:
    def __init__(self, path):
        self.path = Path(path)
        self._fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(self.path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            raise AlreadyRunning(f"another voice2note instance holds {self.path}")
        self._fd = fd
        return self

    def release(self):
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_lock -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/lock.py tests/test_lock.py
git commit -m "feat(lock): mandatory fcntl single-instance lock"
```

---

### Task 7: CLI write bridge (`vault_writer.py`)

Build/run the `cricknote tool vault_write` command (raising on failure, never falling back), and read an existing note's frontmatter for the adopt check.

**Files:**
- Create: `voice2note/vault_writer.py`
- Test: `tests/test_vault_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_writer.py
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from voice2note.vault_writer import (build_write_cmd, write_note, note_exists,
                                     read_frontmatter)


class TestBuildCmd(unittest.TestCase):
    def test_argv_and_json(self):
        cmd = build_write_cmd("cricknote", "Memory/voiceMemo/x.md", "body\nlines")
        self.assertEqual(cmd[:3], ["cricknote", "tool", "vault_write"])
        payload = json.loads(cmd[3])
        self.assertEqual(payload, {"path": "Memory/voiceMemo/x.md", "content": "body\nlines"})


class TestWriteNote(unittest.TestCase):
    def test_raises_on_nonzero(self):
        def runner(cmd, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with self.assertRaises(RuntimeError):
            write_note("cricknote", "Memory/voiceMemo/x.md", "c", runner=runner)

    def test_returns_stdout_on_success(self):
        def runner(cmd, **kw):
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        self.assertEqual(write_note("cricknote", "p", "c", runner=runner), "ok")


class TestFsHelpers(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())

    def test_note_exists(self):
        rel = "Memory/voiceMemo/x.md"
        self.assertFalse(note_exists(self.vault, rel))
        (self.vault / "Memory/voiceMemo").mkdir(parents=True)
        (self.vault / rel).write_text("---\nsource_id: \"a.m4a\"\n---\n", encoding="utf-8")
        self.assertTrue(note_exists(self.vault, rel))

    def test_read_frontmatter_source_id(self):
        rel = "Memory/voiceMemo/x.md"
        (self.vault / "Memory/voiceMemo").mkdir(parents=True)
        (self.vault / rel).write_text(
            "---\nsource_id: \"a.m4a\"\nanalysis: pending\nrecording_type: record\n---\nbody",
            encoding="utf-8")
        fm = read_frontmatter(self.vault, rel)
        self.assertEqual(fm["source_id"], "a.m4a")
        self.assertEqual(fm["analysis"], "pending")
        self.assertEqual(fm["recording_type"], "record")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_vault_writer -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice2note.vault_writer'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_vault_writer -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/vault_writer.py tests/test_vault_writer.py
git commit -m "feat(vault_writer): cricknote CLI write bridge + adopt-check fs helpers"
```

---

### Task 8: Config — env parsing, validation, vault equality (`config.py`)

Add testable helpers for the new env vars, `MEMO_RELDIR` validation, and the (gated) vault-equality check.

**Files:**
- Modify: `voice2note/config.py` (add helpers; wire module constants)
- Test: `tests/test_config.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
import tempfile
import unittest
from pathlib import Path

from voice2note.config import env_bool, validate_memo_reldir, assert_vault_match


class TestEnvBool(unittest.TestCase):
    def test_true_values(self):
        for v in ["1", "true", "TRUE", "yes", "on"]:
            os.environ["V2N_T"] = v
            self.assertTrue(env_bool("V2N_T", False))

    def test_false_default_when_unset(self):
        os.environ.pop("V2N_MISSING", None)
        self.assertFalse(env_bool("V2N_MISSING", False))


class TestRelDir(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate_memo_reldir("Memory/voiceMemo"), "Memory/voiceMemo")

    def test_rejects_absolute(self):
        with self.assertRaises(ValueError):
            validate_memo_reldir("/etc/passwd")

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            validate_memo_reldir("Memory/../../etc")


class TestVaultMatch(unittest.TestCase):
    def test_match_ok(self):
        d = tempfile.mkdtemp()
        assert_vault_match(d, d)  # no raise

    def test_mismatch_raises(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            assert_vault_match(a, b)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_config -v`
Expected: FAIL with `ImportError: cannot import name 'env_bool'`

- [ ] **Step 3: Write minimal implementation**

Add to `voice2note/config.py` (near the top, after imports; add `import json` and `from pathlib import PurePosixPath` if missing):

```python
def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def validate_memo_reldir(reldir):
    p = PurePosixPath(reldir)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"VOICE2NOTE_MEMO_RELDIR must be relative without '..': {reldir!r}")
    return str(p)


def cricknote_vault_path():
    """Read vaultPath from ~/.cricknote/config.json (raises if absent/malformed)."""
    cfg = Path.home() / ".cricknote" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    return data["vaultPath"]


def assert_vault_match(v2n_vault, cricknote_vault):
    if os.path.realpath(v2n_vault) != os.path.realpath(cricknote_vault):
        raise SystemExit(
            "VOICE2NOTE_VAULT does not match ~/.cricknote/config.json vaultPath:\n"
            f"  voice2note: {v2n_vault}\n  cricknote:  {cricknote_vault}\n"
            "Point both at the same vault, or set VOICE2NOTE_USE_CRICKNOTE=false.")
```

Then add the module-level constants (after the existing settings):

```python
USE_CRICKNOTE = env_bool("VOICE2NOTE_USE_CRICKNOTE", False)
CRICKNOTE_BIN = os.environ.get("VOICE2NOTE_CRICKNOTE_BIN") or shutil.which("cricknote") or "cricknote"
MEMO_RELDIR = validate_memo_reldir(os.environ.get("VOICE2NOTE_MEMO_RELDIR", "Memory/voiceMemo"))
CONFIDENCE_MIN = float(os.environ.get("VOICE2NOTE_CONFIDENCE_MIN", "0.5"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_config -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/config.py tests/test_config.py
git commit -m "feat(config): explicit USE_CRICKNOTE, reldir validation, gated vault-equality check"
```

---

### Task 9: Orchestrate the create-once flow (`run.py`)

Wire it together: acquire the lock, run the create-once flow per memo (skip seen, adopt-with-verify, else transcribe→analyze→write), atomic save per memo, gated vault check, drop the daily block.

**Files:**
- Modify: `voice2note/run.py`, `voice2note/memos.py`, `voice2note/config.py`
- Test: `tests/test_run.py` (replace with mock-driven flow tests), `tests/test_memos.py` (update to v2 state API)

- [ ] **Step 1: Write the failing test**

Replace `tests/test_run.py` with:

```python
# tests/test_run.py
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from voice2note import run as runmod
from voice2note.state import State
from voice2note.notes import memo_note_relpath


def make_cfg(vault, use_cricknote=False):
    return SimpleNamespace(
        VAULT=Path(vault), MEMO_RELDIR="Memory/voiceMemo",
        USE_CRICKNOTE=use_cricknote, CRICKNOTE_BIN="cricknote",
        CONFIDENCE_MIN=0.5)


def memo(mid="a.m4a", title="Idea"):
    return SimpleNamespace(id=mid, path=Path("/tmp/a.m4a"), title=title,
                           recorded_at=datetime(2026, 6, 18, 14, 32))


class TestProcessMemo(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        self.state = State(Path(tempfile.mkdtemp()) / "state.json")
        self.cfg = make_cfg(self.vault)
        # Stub the heavy steps.
        runmod.materialize = lambda *a, **k: True
        runmod.transcribe = lambda *a, **k: "the transcript"
        runmod.analyze = lambda *a, **k: {
            "summary": "s", "action_items": [], "topics": ["t"],
            "notable_details": [], "recording_type": "record", "confidence": 0.9}

    def test_creates_note_and_records_state(self):
        runmod.process_memo(memo(), self.state, self.cfg)
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        self.assertTrue((Path(self.vault) / rel).exists())
        self.assertTrue(self.state.is_seen("a.m4a"))

    def test_skips_when_seen(self):
        self.state.record("a.m4a", "x", "complete", "record")
        called = {"n": 0}
        runmod.transcribe = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "t"
        runmod.process_memo(memo(), self.state, self.cfg)
        self.assertEqual(called["n"], 0)

    def test_adopts_existing_matching_note_without_rewrite(self):
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        p = Path(self.vault) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nsource_id: "a.m4a"\nanalysis: complete\n'
                     'recording_type: record\n---\nORIGINAL', encoding="utf-8")
        runmod.transcribe = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run"))
        runmod.process_memo(memo(), self.state, self.cfg)
        self.assertEqual(p.read_text(encoding="utf-8").split("---")[-1].strip(), "ORIGINAL")
        self.assertTrue(self.state.is_seen("a.m4a"))

    def test_adopt_mismatch_raises(self):
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        p = Path(self.vault) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nsource_id: "OTHER.m4a"\n---\nx', encoding="utf-8")
        with self.assertRaises(RuntimeError):
            runmod.process_memo(memo(), self.state, self.cfg)

    def test_analysis_failure_writes_transcript_only_draft(self):
        runmod.analyze = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("codex down"))
        runmod.process_memo(memo(), self.state, self.cfg)
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        out = (Path(self.vault) / rel).read_text(encoding="utf-8")
        self.assertIn("analysis: pending", out)
        self.assertIn("status: draft", out)
        self.assertIn("the transcript", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_run -v`
Expected: FAIL (`process_memo` signature/behavior mismatch)

- [ ] **Step 3: Write minimal implementation**

In `voice2note/run.py`, replace the imports and `process_memo`, and write the note via a helper. Add imports:

```python
from voice2note.notes import memo_note_relpath, render_memo_note
from voice2note.routing import effective_type, route_for
from voice2note.vault_writer import write_note, note_exists, read_frontmatter
```

Add a write helper and rewrite `process_memo`:

```python
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
```

Update `run(once=False)` to: acquire the lock, do the gated vault check, and pass `config` as `cfg`. Replace the body of `run` with:

```python
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
```

Add imports at the top of `run.py`: `from voice2note.lock import SingleInstanceLock, AlreadyRunning`. Add `LOCK_PATH` to `config.py`: `LOCK_PATH = _path("VOICE2NOTE_LOCK", str(PROJECT_DIR / "voice2note.lock"))`. Note: `find_new_memos` uses `state.is_processed`; update `memos.py` to call `state.is_seen` — change `if state.is_processed(path.name):` to `if state.is_seen(path.name):`. Also **remove the now-invalid notes import** in `run.py` (`from voice2note.notes import write_memo_note, append_to_daily, memo_filename`) — those functions were deleted in Task 4. Finally, update `tests/test_memos.py:44`: the v2 `State` has no `mark_processed`; change `state.mark_processed("rec1.m4a")` to `state.record("rec1.m4a", "x", "complete", "record")` (the test still asserts only `rec2.m4a` is found).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_run -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add voice2note/run.py voice2note/config.py voice2note/memos.py tests/test_run.py tests/test_memos.py
git commit -m "feat(run): create-once flow under lock; adopt-with-verify; transcript-only fallback"
```

---

### Task 10: Full suite + `--check` vault gating

Confirm the whole suite is green and that `--check` validates the vault only when `USE_CRICKNOTE=true`.

**Files:**
- Modify: `voice2note/run.py` (`check_access` — add gated vault check)
- Test: `tests/test_run.py` (add one test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_run.py`:

```python
class TestCheckGating(unittest.TestCase):
    def test_standalone_check_does_not_require_cricknote_config(self):
        # USE_CRICKNOTE False → check_access must not raise even if no cricknote config.
        import voice2note.config as config
        orig = config.USE_CRICKNOTE
        config.USE_CRICKNOTE = False
        try:
            self.assertIn(runmod.vault_check_ok(config), (True, False))
        finally:
            config.USE_CRICKNOTE = orig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest tests.test_run.TestCheckGating -v`
Expected: FAIL (`AttributeError: module 'voice2note.run' has no attribute 'vault_check_ok'`)

- [ ] **Step 3: Write minimal implementation**

Add to `voice2note/run.py`:

```python
def vault_check_ok(cfg):
    """Return True if vault config is consistent. Only validates the cricknote
    vault match when USE_CRICKNOTE is true; standalone needs no cricknote config."""
    if not cfg.USE_CRICKNOTE:
        return True
    cfg.assert_vault_match(str(cfg.VAULT), cfg.cricknote_vault_path())
    return True
```

Call it from `check_access` after the existing access print (before returning True):

```python
    if not vault_check_ok(config):
        return False
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -t . -v`
Expected: PASS (all modules green)

- [ ] **Step 5: Commit**

```bash
git add voice2note/run.py tests/test_run.py
git commit -m "feat(run): gate vault-equality check behind USE_CRICKNOTE in --check"
```

---

## Self-review notes (author)

- **Spec coverage:** classification + ambiguity (Tasks 1, 3); YAML escaping (Task 2); deterministic path/no-checkboxes/no-daily-block (Task 4); v2 state + atomic save (Task 5); mandatory lock (Task 6); CLI write bridge + no-fallback + adopt fs helpers (Task 7); explicit USE_CRICKNOTE + reldir + gated vault equality (Tasks 8, 10); create-once flow with adopt-verify + transcript-only fallback (Task 9). Phases 2 (skill) and 3 (ops/docs) are out of scope by design.
- **Manual step (not unit-tested):** end-to-end against the real vault with `VOICE2NOTE_USE_CRICKNOTE=true` is an acceptance check, run after Task 9 (`launchctl start com.voice2note.agent` then inspect `Memory/voiceMemo/`).
- **Not in this plan:** the per-task routing marker `[v2n:<memo-h16>:<task-h8>]` lives in the Phase 2 skill, not voice2note.
