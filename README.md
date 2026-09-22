# Unilim EDT -> Apple Calendar Sync 📅

Synchronisation automatique, intelligente et haute précision de l'emploi du temps de l'**Université de Limoges (IUT GEA)** vers **Apple Calendar (iCloud)** pour macOS, iOS (iPhone/iPad) et Apple Watch.

---

## ✨ Fonctionnalités & Nouveautés

### 🌐 Double Source Hybride & Priorité aux Fichiers Hebdomadaires
- **Community IUT (Moodle GEA)** : Détection et téléchargement automatique des plannings publiés par dossiers hebdomadaires (`Semaine 39`, `S40`, `S41`...).
- **ADE Campus (`planning.unilim.fr`)** : Consultation complémentaire en tâche de fond et fallback automatique.
- 🛡️ **Anti-doublons & Résolution de conflits** : Priorité absolue accordée aux fichiers hebdomadaires de Community IUT. Si un cours est présent dans les fichiers sur un créneau horaire, tout cours obsolète d'ADE Campus à la même heure est automatiquement ignoré.

### 📚 Résolution Automatique des Intitulés de Matières (`signatures.unilim.fr`)
- Traduction instantanée des codes bruts (`R3.06`, `R3.GEMA.13`, `SAE3.01`, etc.) en véritables intitulés officiels issus du portail de notes :
  - `R3.06` ➔ **`R3.06 Contrôle de gestion`**
  - `R3.04` ➔ **`R3.04 Fiscalité`**
  - `R3.GEMA.14` ➔ **`R3.GEMA.14 Business Model`**
  - `SAE3.01` ➔ **`SAE3.01 Création d'organisation`**
- 🛡️ **Sécurité Salles / Matières** : Distinction stricte entre les noms de salles (`R04`, `R01`, `103`, `Amphi B`...) et les codes matières (`R3.04`, `R3.01`), garantissant qu'une salle ne soit jamais prise pour un cours.

### 👨‍🏫 Affichage Visible de l'Enseignant dans le Titre
- Le nom du professeur est désormais intégré directement dans le titre de l'événement pour une visibilité immédiate au premier coup d'œil (widgets iPhone, Apple Watch, vue mensuelle/hebdomadaire) :
  - *Exemple :* `R3.06 Contrôle de gestion (TD) - DUPONT Jean`

### 🎨 Gestion par 4 Calendriers Thématiques & Couleurs iCloud
Aiguillage automatique des cours dans 4 calendriers iCloud dédiés :
- 🌸 **`CM`** : Cours Magistraux & réunions de promotion.
- 🍏 **`TD`** : Travaux Dirigés & séances de SAE.
- 🔷 **`TP`** : Travaux Pratiques en effectif réduit.
- 🟡 **`Controles`** : **Évaluations, Contrôles, DS et Examens** (détection automatique des séances sur fond jaune sur ADE Campus et des mots-clés dans les fichiers/PDF).

### 🔔 Notifications Natives Mac & Push iPhone (100% Apple)
- 💻 **Mac** : Bannière sonore de notification en haut à droite à chaque mise à jour.
- 📱 **iPhone / Apple Watch** : Push instantané sur l'écran verrouillé via une liste dédiée **`Unilim EDT`** dans l'application Rappels iCloud (avec nettoyage automatique des anciennes notifications).

### ⏱️ Automatisation TCC-Safe & Raccourcis
- 🔄 **Daemon macOS (`launchd`)** : Exécution autonome 2 fois par jour (**06h30** le matin et **19h30** le soir) dans un environnement dédié (`~/.unilim_edt_sync`) conforme aux permissions de sécurité macOS.
- 🖱️ **Lanceur 1-Clic sur le Bureau** : Fichier exécutable `Mettre à jour EDT.command` pour synchroniser à la demande d'un simple double-clic.
- ⌨️ **Commande Terminal** : Raccourci global `sync-edt` disponible dans le terminal.
- 💾 **Conservation de l'historique** : Plage glissante sur 3 semaines (~21 jours d'avance) tout en **préservant définitivement tous les cours passés**.

---

## 🚀 Installation & Configuration

### 1. Cloner et installer les dépendances
```bash
git clone https://github.com/Pirkah/unilim-edt-sync.git
cd unilim-edt-sync
pip3 install -r requirements.txt
playwright install chromium
```

### 2. Configuration des identifiants (`.env`)
Copiez le modèle de configuration :
```bash
cp config.example.env .env
```
Renseignez vos identifiants dans le fichier `.env` :
```env
UNILIM_USERNAME="votre_identifiant"
UNILIM_PASSWORD="votre_mot_de_passe"
TARGET_GROUP="GEMA1 TP2"
```

### 3. Première connexion (Sauvegarde de session A2F)
Lancez l'assistant graphique pour valider le code A2F reçu par mail :
```bash
python3 login.py
```
*(Une fenêtre s'ouvre, validez votre connexion et les cookies de session sont enregistrés).*

### 4. Lancer la synchronisation manuelle
```bash
python3 sync_edt.py
# ou
./Mettre_a_jour_EDT.command
```

### 5. Activer l'automatisation 2x par jour en arrière-plan
```bash
./install_agent.sh
```

---

## 📂 Structure du projet

- `sync_edt.py` : Moteur principal (scraping hybride Community IUT + ADE, résolution de matières, fusion intelligente, injection iCloud et notifications).
- `signatures_courses.json` : Référentiel des correspondances codes matières ➔ intitulés officiels.
- `login.py` : Assistant graphique de connexion CAS et mémorisation de session A2F.
- `install_agent.sh` : Script de déploiement et d'activation du daemon `launchd` macOS.
- `Mettre_a_jour_EDT.command` : Raccourci exécutable par double-clic sur le Bureau.
- `requirements.txt` : Dépendances Python (`playwright`, `icalendar`, `pypdf`, etc.).
- `config.example.env` : Modèle sécurisé de variables d'environnement.
- `.gitignore` : Protection stricte contre l'envoi de secrets ou de données personnelles sur GitHub.
