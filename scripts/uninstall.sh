#!/bin/bash
# Unload and remove the voice2note LaunchAgent. Notes already written are kept.
PLIST="$HOME/Library/LaunchAgents/com.voice2note.agent.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "voice2note LaunchAgent unloaded and removed."
