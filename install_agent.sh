#!/bin/bash
# Script d'installation du LaunchAgent macOS (exécution 2 fois par jour : 06h30 et 19h30)

PLIST_NAME="com.julien.unilim.edtsync.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXEC="$(which python3)"

echo "=== Installation du LaunchAgent pour la synchro EDT (2x par jour) ==="
echo "Dossier du projet : $PROJECT_DIR"
echo "Interpréteur Python : $PYTHON_EXEC"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

# Génération du fichier plist avec déclenchement matin (06h30) et soir (19h30)
cat <<EOF > "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.julien.unilim.edtsync</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_EXEC</string>
        <string>$PROJECT_DIR/sync_edt.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>6</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/sync_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/sync_stderr.log</string>
</dict>
</plist>
EOF

# Charger le LaunchAgent
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "✅ LaunchAgent installé et activé avec succès !"
echo "La synchronisation se lancera automatiquement chaque matin (06h30) et chaque soir (19h30)."
