"""Create explicitly requested items in the macOS Reminders and Calendar apps.

This module is intentionally small and only talks to Apple applications through
the system ``osascript`` program.  It has no network dependency and receives all
user-supplied text as JSON command-line data, never as executable script text.
"""
import json
import re
import subprocess
from datetime import datetime, timedelta


# Whisper commonly inserts a space in "CrickNote".  Accept that and the likely
# "Cricket Note" mis-transcription, but keep "please" as the deliberate trigger.
CRICKNOTE_REQUEST = re.compile(r"\b(?:crick|cricket)\s*note\s*,?\s*please\b", re.IGNORECASE)


REMINDERS_SCRIPT = r'''function run(argv) {
    const data = JSON.parse(argv[0]);
    const app = Application("Reminders");
    const list = data.list ? app.lists.byName(data.list) : app.defaultList();
    if (!list.exists()) {
        throw new Error("Reminders list not found: " + data.list);
    }
    const item = app.Reminder({name: data.title, body: data.notes || ""});
    list.reminders.push(item);
    if (data.remind_at) {
        item.remindMeDate = new Date(data.remind_at);
    }
    return JSON.stringify({id: item.id()});
}'''


CALENDAR_SCRIPT = r'''function run(argv) {
    const data = JSON.parse(argv[0]);
    const app = Application("Calendar");
    let calendar;
    if (data.calendar) {
        calendar = app.calendars.byName(data.calendar);
    } else {
        const writable = app.calendars.whose({writable: true})();
        if (!writable.length) {
            throw new Error("No writable Calendar was found.");
        }
        calendar = writable[0];
    }
    if (!calendar.exists()) {
        throw new Error("Calendar not found: " + data.calendar);
    }
    const item = app.Event({
        summary: data.title,
        startDate: new Date(data.start_at),
        endDate: new Date(data.end_at),
        description: data.notes || ""
    });
    calendar.events.push(item);
    return JSON.stringify({id: item.uid()});
}'''


class AppleAutomationError(RuntimeError):
    """The user-requested item could not be created in a macOS app."""


def has_cricknote_request(transcript):
    """Whether the transcript contains the explicit Apple-action trigger."""
    return bool(CRICKNOTE_REQUEST.search(transcript or ""))


def _as_local_iso(value, field, allow_none=True):
    """Validate an ISO date-time and return one with the local UTC offset."""
    if value is None or not str(value).strip():
        if allow_none:
            return None
        raise AppleAutomationError(f"Apple action is missing {field}.")
    text = str(value).strip()
    # A date alone has no notification/event time.  It is acceptable for a
    # reminder with no alert, but never enough to create a Calendar event.
    if "T" not in text and " " not in text:
        if allow_none:
            return None
        raise AppleAutomationError(f"Calendar action needs a date and time for {field}.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppleAutomationError(f"Apple action has an invalid {field}: {text!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="minutes")


def _memo_notes(notes, source_id):
    prefix = f"Created by Voice2Note from Voice Memo {source_id}."
    return prefix if not notes else f"{prefix}\n\n{notes}"


def prepare_action(action, source_id):
    """Validate a parsed model action and make a payload for AppleScript."""
    if not isinstance(action, dict):
        return None
    kind = str(action.get("kind", "none")).lower()
    if kind == "none":
        return None
    title = str(action.get("title") or "").strip()
    if kind not in ("reminder", "calendar") or not title:
        raise AppleAutomationError("Apple action is missing a valid type or title.")

    payload = {
        "title": title[:300],
        "notes": _memo_notes(str(action.get("notes") or "").strip(), source_id),
    }
    if kind == "reminder":
        payload["remind_at"] = _as_local_iso(action.get("remind_at"), "remind_at")
    else:
        start = _as_local_iso(action.get("start_at"), "start_at", allow_none=False)
        end = _as_local_iso(action.get("end_at"), "end_at")
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end) if end else start_dt + timedelta(hours=1)
        if end_dt <= start_dt:
            raise AppleAutomationError("Calendar action ends before it starts.")
        payload["start_at"] = start_dt.isoformat(timespec="minutes")
        payload["end_at"] = end_dt.isoformat(timespec="minutes")
    return kind, payload


def _run_script(script, payload, osascript_bin="/usr/bin/osascript", runner=subprocess.run):
    """Run static JXA and return its JSON response; user text stays in ``payload``."""
    command = [osascript_bin, "-l", "JavaScript", "-e", script, "--", json.dumps(payload)]
    try:
        proc = runner(command, capture_output=True, text=True, errors="replace", timeout=30)
    except OSError as exc:
        raise AppleAutomationError(f"Could not run osascript: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown error").strip()
        raise AppleAutomationError(f"macOS Apple action failed: {detail[:500]}")
    try:
        response = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise AppleAutomationError("macOS Apple action returned an invalid response.") from exc
    item_id = str(response.get("id") or "").strip() if isinstance(response, dict) else ""
    if not item_id:
        raise AppleAutomationError("macOS Apple action did not return an item ID.")
    return item_id


def create_apple_item(action, source_id, *, reminders_list=None, calendar_name=None,
                      osascript_bin="/usr/bin/osascript", runner=subprocess.run):
    """Create the requested Apple item and return durable, human-readable metadata."""
    prepared = prepare_action(action, source_id)
    if prepared is None:
        return None
    kind, payload = prepared
    if kind == "reminder":
        payload["list"] = reminders_list or None
        item_id = _run_script(REMINDERS_SCRIPT, payload, osascript_bin, runner)
    else:
        payload["calendar"] = calendar_name or None
        item_id = _run_script(CALENDAR_SCRIPT, payload, osascript_bin, runner)
    return {"kind": kind, "id": item_id, "title": payload["title"]}
