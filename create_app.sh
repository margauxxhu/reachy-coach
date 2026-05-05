#!/bin/bash
# Creates Speech Coach.app in /Applications — double-click to launch the UI.
# Run once: bash create_app.sh

cat > /tmp/speech_coach.applescript << 'EOF'
on run
    do shell script "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /Users/minttymag/reachy-projects/speech-coach/coach_ui.py &"
end run
EOF

rm -rf "/Applications/Speech Coach.app"
osacompile -o "/Applications/Speech Coach.app" /tmp/speech_coach.applescript
echo "✓ Speech Coach.app created in /Applications — double-click to launch."
