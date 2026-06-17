#!/bin/bash
# Convenience wrapper for manual / dev runs, e.g.:  ./run.sh --check   ./run.sh --once
#
# NOTE: for reading the protected Voice Memos folder, the *frontmost app you launch
# this from* (e.g. Terminal) must have Full Disk Access. The scheduled LaunchAgent
# does NOT need that. To trigger a real run on demand, prefer:
#     launchctl start com.voice2note.agent
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$DIR:$PYTHONPATH"
exec /usr/bin/python3 -m voice2note.run "$@"
