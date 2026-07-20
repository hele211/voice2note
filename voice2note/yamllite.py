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
