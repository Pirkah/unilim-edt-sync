# Unilim EDT -> Apple Calendar Sync 📅

Synchronisation automatique de l'emploi du temps ADE Campus de l'Université de Limoges vers l'application Calendrier d'Apple (macOS / iOS).

## ✨ Fonctionnalités

- 🔐 **Authentification CAS automatique** : Connexion au portail de l'Université de Limoges (`cas.unilim.fr`).
- ⚡ **Gestion autonome de l'A2F** : Récupération et validation du code 2FA par e-mail en temps réel via le serveur IMAP `imap.unilim.fr`.
- 📥 **Export ADE Campus** : Téléchargement et parsing du flux `.ics` à jour.
- 🍏 **Intégration Apple Calendar** : Création / mise à jour des cours directement dans un calendrier Apple dédié (synchronisé iCloud).
- ⏱️ **Tâche de fond macOS (`launchd`)** : Exécution automatique tous les 2 jours en arrière-plan.

## 🚀 Installation & Configuration

1. Cloner ou ouvrir le projet :
   ```bash
   cd "/Users/julien/Desktop/projet /recup EDT"
   ```

2. Installer les dépendances :
   ```bash
   pip3 install -r requirements.txt
   ```

3. Configurer les identifiants :
   ```bash
   cp config.example.env .env
   ```
   Renseignez vos identifiants dans le fichier `.env`.

4. Tester la synchronisation manuellement :
   ```bash
   python3 sync_edt.py
   ```

5. Activer la synchronisation automatique (tous les 2 jours) :
   ```bash
   ./install_agent.sh
   ```
