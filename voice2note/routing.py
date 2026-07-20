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
