import json
import unittest
from types import SimpleNamespace

from voice2note.apple_automation import (
    AppleAutomationError,
    CALENDAR_SCRIPT,
    REMINDERS_SCRIPT,
    create_apple_item,
    has_cricknote_request,
    prepare_action,
)


class TestTrigger(unittest.TestCase):
    def test_accepts_spoken_variants(self):
        self.assertTrue(has_cricknote_request("CrickNote please, call Mum."))
        self.assertTrue(has_cricknote_request("crick note please call Mum"))
        self.assertTrue(has_cricknote_request("Cricket Note, please: call Mum"))

    def test_requires_deliberate_phrase(self):
        self.assertFalse(has_cricknote_request("Please call Mum."))
        self.assertFalse(has_cricknote_request("CrickNote call Mum."))


class TestPrepareAction(unittest.TestCase):
    def test_reminder_without_time_is_valid(self):
        kind, payload = prepare_action(
            {"kind": "reminder", "title": "Call Mum", "notes": "Tomorrow"}, "memo.m4a")
        self.assertEqual(kind, "reminder")
        self.assertIsNone(payload["remind_at"])
        self.assertIn("memo.m4a", payload["notes"])

    def test_calendar_adds_one_hour_when_end_missing(self):
        kind, payload = prepare_action(
            {"kind": "calendar", "title": "Team meeting",
             "start_at": "2026-07-21T10:00", "end_at": None}, "memo.m4a")
        self.assertEqual(kind, "calendar")
        self.assertIn("T10:00", payload["start_at"])
        self.assertIn("T11:00", payload["end_at"])

    def test_calendar_rejects_date_without_time(self):
        with self.assertRaises(AppleAutomationError):
            prepare_action({"kind": "calendar", "title": "Team meeting",
                            "start_at": "2026-07-21"}, "memo.m4a")


class TestCreateAppleItem(unittest.TestCase):
    def _runner(self, item_id):
        def runner(command, **kwargs):
            self.command = command
            return SimpleNamespace(returncode=0, stdout=json.dumps({"id": item_id}), stderr="")
        return runner

    def test_creates_reminder_with_json_payload(self):
        runner = self._runner("reminder-id")
        result = create_apple_item(
            {"kind": "reminder", "title": 'Call "Mum"',
             "remind_at": "2026-07-21T09:30", "notes": "Use the \"new\" number."},
            "memo.m4a", reminders_list="Personal", runner=runner)
        self.assertEqual(result, {"kind": "reminder", "id": "reminder-id", "title": 'Call "Mum"'})
        self.assertIn(REMINDERS_SCRIPT, self.command)
        payload = json.loads(self.command[-1])
        self.assertEqual(payload["list"], "Personal")
        self.assertIn('Call "Mum"', payload["title"])

    def test_creates_calendar_event(self):
        runner = self._runner("calendar-id")
        result = create_apple_item(
            {"kind": "calendar", "title": "Team meeting",
             "start_at": "2026-07-21T10:00", "end_at": "2026-07-21T11:30"},
            "memo.m4a", calendar_name="Work", runner=runner)
        self.assertEqual(result["kind"], "calendar")
        self.assertEqual(result["id"], "calendar-id")
        self.assertIn(CALENDAR_SCRIPT, self.command)
        self.assertEqual(json.loads(self.command[-1])["calendar"], "Work")

    def test_empty_model_decision_creates_nothing(self):
        self.assertIsNone(create_apple_item({"kind": "none"}, "memo.m4a"))
