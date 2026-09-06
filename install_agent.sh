#!/bin/bash
# Script d'installation du LaunchAgent macOS (exécution 2 fois par jour : 06h30 et 19h30)
# Résout l'erreur TCC "Operation not permitted" en déployant le runtime dans ~/.unilim_edt_sync

PLIST_NAME="com.julien.unilim.edtsync.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME/.unilim_edt_sync"
PYTHON_EXEC="$(which python3)"

echo "=== Installation du LaunchAgent pour la synchro EDT (2x par jour) ==="
echo "Dossier source : $PROJECT_DIR"
echo "Dossier d'exécution daemon : $TARGET_DIR"
echo "Interpréteur Python : $PYTHON_EXEC"

# 1. Créer le dossier cible hors du Bureau pour éviter les restrictions TCC de macOS
mkdir -p "$TARGET_DIR"
mkdir -p "$TARGET_DIR/logs"
mkdir -p "$LAUNCH_AGENTS_DIR"

# 2. Synchroniser les fichiers nécessaires vers le dossier d'exécution
cp "$PROJECT_DIR/sync_edt.py" "$TARGET_DIR/"
cp "$PROJECT_DIR/.env" "$TARGET_DIR/" 2>/dev/null || true
cp "$PROJECT_DIR/auth_state.json" "$TARGET_DIR/" 2>/dev/null || true

# 3. Créer un script wrapper bash pour une exécution propre
cat <<EOF > "$TARGET_DIR/run_sync.sh"
#!/bin/bash
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/Library/Python/3.9/bin:$HOME/Library/Python/3.10/bin:$HOME/Library/Python/3.11/bin:$HOME/Library/Python/3.12/bin:\$PATH"
cd "$TARGET_DIR"
$PYTHON_EXEC sync_edt.py >> "$TARGET_DIR/logs/sync_stdout.log" 2>> "$TARGET_DIR/logs/sync_stderr.log"

# Recopier la session mise à jour vers le projet du Bureau si besoin
cp "$TARGET_DIR/auth_state.json" "$PROJECT_DIR/auth_state.json" 2>/dev/null || true
EOF
chmod +x "$TARGET_DIR/run_sync.sh"

# 4. Génération du fichier plist pour launchd
cat <<EOF > "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.julien.unilim.edtsync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$TARGET_DIR/run_sync.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$TARGET_DIR</string>
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
    <string>$TARGET_DIR/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$TARGET_DIR/logs/launchd_stderr.log</string>
</dict>
</plist>
EOF

# 5. Charger le LaunchAgent
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "✅ LaunchAgent installé et activé avec succès !"
echo "La synchronisation se lancera automatiquement chaque matin (06h30) et chaque soir (19h30)."
