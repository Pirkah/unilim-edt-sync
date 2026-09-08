#!/bin/bash
# Script exécutable par double-clic pour mettre à jour l'emploi du temps
cd "$(dirname "$0")"
clear
echo "============================================================"
echo "🚀 SYNCHRONISATION DE L'EMPLOI DU TEMPS UNILIM"
echo "============================================================"
echo ""

python3 sync_edt.py

if [ $? -eq 0 ]; then
    osascript -e 'display notification "Les cours ont été synchronisés sur iCloud." with title "Unilim EDT Sync" subtitle "Mise à jour réussie !"' 2>/dev/null || true
    echo ""
    echo "============================================================"
    echo "✅ Synchronisation terminée avec succès !"
    echo "============================================================"
else
    echo ""
    echo "============================================================"
    echo "❌ Une erreur est survenue. Vérifiez vos identifiants ou votre connexion."
    echo "============================================================"
fi

echo ""
echo "Cette fenêtre va se fermer automatiquement dans 3 secondes..."
sleep 3
