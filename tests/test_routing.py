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
