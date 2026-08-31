# Unilim EDT -> Apple Calendar Sync 📅

Synchronisation automatique et intelligente de l'emploi du temps ADE Campus de l'Université de Limoges vers **Apple Calendar (iCloud)** pour macOS et iOS (iPhone/iPad/Apple Watch).

## ✨ Fonctionnalités

- 🔐 **Authentification CAS & A2F** : Gestion de la double authentification avec persistance de session.
- 🎯 **Filtrage précis par groupe** : Extraction automatique et ciblée selon votre filière et vos groupes de TD/TP (ex: BUT 2 GEA - GEMA1 TP2).
- 🎨 **Gestion par calendriers thématiques & couleurs** :
  - 🌸 **CM** (Rose) : Cours Magistraux & réunions
  - 🍏 **TD** (Vert) : Travaux Dirigés & SAE
  - 🔷 **TP** (Bleu) : Travaux Pratiques
- ☁️ **Synchronisation native iCloud** : Les cours apparaissent immédiatement sur iPhone, iPad et Apple Watch.
- ⏱️ **Tâche de fond macOS (`launchd`)** : Synchronisation autonome 2 fois par jour (06h30 le matin et 19h30 le soir).

---

## 🚀 Installation & Démarrage

### 1. Installer les dépendances
```bash
pip3 install -r requirements.txt
playwright install chromium
```

### 2. Configuration (`.env`)
Copiez le modèle et renseignez vos informations :
```bash
cp config.example.env .env
```
Éditez `.env` avec vos identifiants :
```env
UNILIM_USERNAME="votre_identifiant"
UNILIM_PASSWORD="votre_mot_de_passe"
TARGET_GROUP="GEMA1 TP2"
```

### 3. Première connexion (mémorisation de session A2F)
Lancez l'interface de connexion pour valider le code 2FA reçu par email :
```bash
python3 login.py
```
*(Une fenêtre s'ouvre, validez votre code A2F et la session est automatiquement enregistrée).*

### 4. Lancer la synchronisation manuelle
```bash
python3 sync_edt.py
```

### 5. Activer l'automatisation en arrière-plan (2x par jour)
```bash
./install_agent.sh
```

---

## 📂 Structure du projet

- `sync_edt.py` : Script principal d'extraction et de synchronisation des cours.
- `login.py` : Assistant graphique pour la connexion initiale et la sauvegarde de session.
- `install_agent.sh` : Script d'installation du daemon `launchd` macOS.
- `config.example.env` : Modèle de configuration des variables d'environnement.
- `requirements.txt` : Dépendances Python du projet.
