#!/bin/bash
# Creates Speech Coach.app in /Applications — double-click to start a session.
# Run once: bash create_app.sh

cat > /tmp/speech_coach.applescript << 'EOF'
on run
    tell application "Terminal"
        activate
        do script "source ~/reachy_mini_env/bin/activate && cd ~/reachy-projects/speech-coach && python capture_audio.py && python analyze.py && python feedback.py"
    end tell
end run
EOF

rm -rf "/Applications/Speech Coach.app"
osacompile -o "/Applications/Speech Coach.app" /tmp/speech_coach.applescript
echo "✓ Speech Coach.app created in /Applications — double-click to start a session."
