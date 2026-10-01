#!/usr/bin/env python3
"""
Unilim EDT Sync - Synchronisation automatique de l'emploi du temps vers Apple Calendar (iCloud)
Supporte :
1. Community IUT (Moodle - Section Emploi du temps & dossiers de semaines avec parsing hybride ICS & PDF)
2. ADE Campus (planning.unilim.fr)
3. Résolution automatique des codes matières (R3.06 -> Contrôle de gestion, etc.) via Signatures Unilim
4. Aiguillage automatique en 4 calendriers : CM, TD, TP, et Contrôles / Évaluations
5. Affichage clair du nom de l'enseignant dans le titre de l'événement
Auteur: Julien Nicolle
"""

import os
import re
import sys
import json
import urllib.request
import asyncio
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
import pytz
import pdfplumber
from icalendar import Calendar, Event, vText

# Charger la configuration
BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

CAS_USERNAME = os.getenv("CAS_USERNAME", os.getenv("UNILIM_USERNAME", "Nicolle12"))
CAS_PASSWORD = os.getenv("CAS_PASSWORD", os.getenv("UNILIM_PASSWORD", ""))
TARGET_GROUP = os.getenv("TARGET_GROUP", "GEMA1 TP2")
TZ = pytz.timezone("Europe/Paris")

# Dictionnaire de secours officiel BUT GEA (S3 & S4)
DEFAULT_COURSES_MAP = {
    "R3.01": "Environnement économique",
    "R3.02": "Environnement juridique",
    "R3.03": "Management d'activités",
    "R3.04": "Fiscalité",
    "R3.05": "Traitement numérique des données",
    "R3.06": "Contrôle de gestion",
    "R3.07": "Finance",
    "R3.08": "Expression et communication",
    "R3.09": "Anglais des affaires",
    "R3.10": "PPP",
    "R3.11": "Droit et entrepreneuriat",
    "R3.12": "Financement des activités",
    "R3.13": "Management opérationnel",
    "R3.14": "Business Model",
    "R3.15": "LV2 Espagnol",
    "SAE3.01": "Création d'organisation",
    "SAE3.02": "Business Model",
    "SAE 3.1": "Création d'organisation",
    "SAE 3.2": "Business Model",
    "R4.01": "Environnement économique international",
    "R4.02": "Environnement juridique",
    "R4.03": "Management d'activités",
    "R4.04": "Traitement numérique des données",
    "R4.05": "Expression et communication",
    "R4.06": "Anglais des affaires",
    "R4.07": "PPP",
    "R4.08": "Business plan",
    "R4.09": "Marketing opérationnel",
    "R4.10": "Management opérationnel approfondi",
    "R4.11": "LV2 Espagnol",
    "SAE 4.1": "Création ou développement d'organisation",
    "SAE 4.2": "Business Plan"
}


def load_courses_dictionary() -> dict:
    """Charge le dictionnaire des matières depuis le cache local ou le dictionnaire par défaut."""
    cache_file = BASE_DIR / "signatures_courses.json"
    mapping = dict(DEFAULT_COURSES_MAP)
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                mapping.update(data)
        except Exception:
            pass
    return mapping


COURSES_DICTIONARY = load_courses_dictionary()


def resolve_course_title(raw_code: str, course_type: str, teacher: str = "") -> str:
    """
    Associe le code matière (ex: R3.06, R3.GEMA.13, SAE3.01) à son nom officiel issu de signatures.unilim.fr
    et ajoute le nom de l'enseignant de manière claire et lisible.
    """
    clean_code = raw_code.strip()
    
    # 1. Si le titre contient déjà un nom explicite (ex: 'TC R3.04 Fiscalité (CM01)')
    clean_code = re.sub(r'\s*\([A-Z0-9]+\)\s*$', '', clean_code).strip()
    
    # 2. Extraire le code canonique (ex: R3.06, R3.GEMA.13 -> R3.13, SAE3.01 -> SAE3.01)
    m = re.search(r'(R[34]\.(?:GEMA\.|GCFF\.|GPRH\.)?(\d{2}))|(SAE\s*3\.?\d*)', clean_code, re.I)
    
    name = ""
    if m:
        if m.group(1):
            full_r, num = m.group(1), m.group(2)
            prefix = full_r[:2]
            norm_key = f"{prefix}.{num}"
            name = COURSES_DICTIONARY.get(norm_key, "")
        elif m.group(3):
            sae_str = m.group(3).upper().replace(" ", "")
            norm_key = "SAE3.01" if "3.1" in sae_str or "3.01" in sae_str else "SAE3.02"
            name = COURSES_DICTIONARY.get(norm_key, "")
            
    suffix = "Contrôle" if course_type == "EVAL" else f"({course_type})"
    
    # Construction du titre de base
    if name and name.lower() not in clean_code.lower():
        base_title = f"{clean_code} {name} {suffix}"
    else:
        base_title = f"{clean_code} {suffix}"
        
    # Ajouter le nom de l'enseignant de façon bien visible
    if teacher and teacher.strip() and teacher.strip().lower() not in base_title.lower():
        return f"{base_title} - {teacher.strip()}"
    return base_title


def get_icloud_calendars() -> dict:
    """Détecte dynamiquement les noms des calendriers iCloud cibles (CM, TD, TP, et Contrôles/Évaluation)."""
    cals = {
        "CM": "CM",
        "TD": "TD",
        "TP": "TP",
        "EVAL": "Controles"
    }
    try:
        scpt = 'tell application "Calendar" to get name of every calendar'
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            names = [n.strip() for n in res.stdout.split(",")]
            for possible in ["Controles", "Contrôles", "Evaluation", "Évaluation", "Evaluations", "Évaluations"]:
                if possible in names:
                    cals["EVAL"] = possible
                    break
    except Exception:
        pass
    return cals


def clean_target_range_events(start_dt: datetime, end_dt: datetime) -> None:
    """Nettoie la plage glissante sur les calendriers iCloud CM, TD, TP et Contrôles (préserve les anciens jours)."""
    subprocess.run(["open", "-a", "Calendar"])
    s_str = start_dt.strftime("%d/%m/%Y 00:00:00")
    e_str = (end_dt + timedelta(days=1)).strftime("%d/%m/%Y 23:59:59")
    
    icloud_cals = get_icloud_calendars()
    lines = []
    for c_name in icloud_cals.values():
        lines.append(f'''
        if (exists (first calendar whose name is "{c_name}")) then
            tell calendar "{c_name}"
                set filterStart to date "{s_str}"
                set filterEnd to date "{e_str}"
                delete (events whose start date ≥ filterStart and start date ≤ filterEnd)
            end tell
        end if
        ''')
        
    scpt = f'''
    tell application "Calendar"
        {chr(10).join(lines)}
    end tell
    '''
    subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)


def get_event_category(title: str, description: str = "", raw_text: str = "", is_yellow: bool = False) -> str:
    """
    Détermine la catégorie (EVAL, CM, TD ou TP) pour l'aiguillage dans le bon calendrier iCloud.
    Priorité maximale accordée aux évaluations, contrôles et DS (fond jaune sur ADE ou mention dans le texte/PDF).
    """
    if is_yellow:
        return "EVAL"
        
    full_text = f"{title} {description} {raw_text}"
    check_text = re.sub(r'contr[oô]le\s+de\s+gestion', '', full_text, flags=re.I)
    
    # 1. Détection des Évaluations / Contrôles / DS / Examens
    eval_patterns = [
        r'\bCONTROLE\b', r'\bCONTRÔLE\b', r'\bEVALUATION\b', r'\bÉVALUATION\b',
        r'\bEVAL\b', r'\bEXAMEN\b', r'\bPARTIEL\b', r'\bDS\b', r'\bDS\d+\b',
        r'\bDEVOIR\s+SURVEILL[EÉ]\b', r'\bINTERROGATION\b', r'\bTEST\b', r'\bQCM\b'
    ]
    if any(re.search(p, check_text, re.I) for p in eval_patterns):
        return "EVAL"
        
    # 2. Détection du type de cours (CM, TD, TP)
    clean_text = re.sub(r'GEMA\d?[-_ ]?TP\d?', '', title, flags=re.I)
    
    if re.search(r'\bTP\b|\(TP\d*\)', clean_text, re.I):
        return "TP"
    if re.search(r'\bCM\b|\(CM\d*\)', clean_text, re.I):
        return "CM"
    if re.search(r'\bTD\b|\(TD\d*\)', clean_text, re.I):
        return "TD"
        
    return "TD"


def insert_events_by_category(events: list, chunk_size: int = 20) -> int:
    """Insère les cours dans les calendriers iCloud CM, TD, TP et Contrôles."""
    subprocess.run(["open", "-a", "Calendar"])
    total_success = 0
    icloud_cals = get_icloud_calendars()
    
    categorized = {"CM": [], "TD": [], "TP": [], "EVAL": []}
    for ev in events:
        cat = ev.get("category") or get_event_category(ev["title"], ev.get("description", ""))
        categorized[cat].append(ev)
        
    for cat, cat_events in categorized.items():
        if not cat_events:
            continue
            
        c_name = icloud_cals.get(cat, "TD")
        print(f"[*] Injection dans '{c_name}' (iCloud) : {len(cat_events)} cours...")
        
        for i in range(0, len(cat_events), chunk_size):
            chunk = cat_events[i:i + chunk_size]
            lines = []
            for ev in chunk:
                summary = ev["title"].replace('"', '\\"')
                location = ev["location"].replace('"', '\\"')
                description = ev["description"].replace('"', '\\"').replace('\n', ' ')
                start_str = ev["start_dt"].strftime("%d/%m/%Y %H:%M:%S")
                end_str = ev["end_dt"].strftime("%d/%m/%Y %H:%M:%S")
                lines.append(f'make new event with properties {{summary:"{summary}", start date:date "{start_str}", end date:date "{end_str}", location:"{location}", description:"{description}"}}')
                
            scpt = f'''
            tell application "Calendar"
                tell calendar "{c_name}"
                    {chr(10).join(lines)}
                end tell
            end tell
            '''
            res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
            if res.returncode == 0:
                total_success += len(chunk)
            else:
                print(f"[!] Erreur sur {c_name}: {res.stderr.strip()[:100]}")
                
    return total_success


def parse_pdf_timetable(pdf_path: Path, week_num: int, year: int = None) -> list:
    """Extrait les cours directement depuis la grille PDF hebdomadaire de l'IUT."""
    if year is None:
        year = datetime.now().year
        
    # Calcul du lundi de la semaine ISO
    jan4 = date(year, 1, 4)
    start_of_year = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = start_of_year + timedelta(weeks=week_num - 1)
    
    events = []
    
    with pdfplumber.open(str(pdf_path)) as pdf:
        p = pdf.pages[0]
        course_rects = [r for r in p.rects if r["width"] < 700 and r["height"] > 20]
        
        for r in course_rects:
            # 1. Jour de la semaine (X axis)
            cx = (r["x0"] + r["x1"]) / 2
            day_idx = int((cx - 56.0) / 126.9)
            if day_idx < 0 or day_idx > 5:
                continue
            event_date = monday + timedelta(days=day_idx)
            
            # 2. Heures de début et fin (Y axis)
            start_hour_float = 7.0 + (r["top"] - 60.0) / 36.52
            end_hour_float = 7.0 + (r["bottom"] - 60.0) / 36.52
            
            start_h = int(start_hour_float)
            start_m = int(round((start_hour_float - start_h) * 60 / 5) * 5)
            if start_m == 60:
                start_h += 1
                start_m = 0
                
            end_h = int(end_hour_float)
            end_m = int(round((end_hour_float - end_h) * 60 / 5) * 5)
            if end_m == 60:
                end_h += 1
                end_m = 0
                
            start_dt = datetime(event_date.year, event_date.month, event_date.day, start_h, start_m)
            end_dt = datetime(event_date.year, event_date.month, event_date.day, end_h, end_m)
            
            # 3. Extraction du texte
            cropped = p.crop((r["x0"], r["top"], r["x1"], r["bottom"]))
            text = cropped.extract_text() or ""
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if not lines:
                continue
                
            raw_code_line = lines[0]
            
            # Enseignant, salle, groupes
            teacher = ""
            location = "IUT Limoges"
            groups = []
            
            for l in lines[1:]:
                if re.match(r'^(Amphi\s+[A-Z0-9]+|\d{3}|R\.\d{2}|R\d{2})$', l, re.I):
                    location = f"Salle {l} - IUT Limoges"
                elif any(g in l for g in ["GEMA", "TP", "TD", "CM"]):
                    groups.append(l)
                elif not any(char.isdigit() for char in l) and len(l) > 3 and not any(k in l.lower() for k in ["gestion", "finance", "droit", "economie", "anglais", "espagnol", "developpement", "numerique", "business"]):
                    teacher = l
                    
            cat = get_event_category(raw_code_line, text, raw_code_line)
            title = resolve_course_title(raw_code_line, cat, teacher)
            desc = f"Cours: {title}\nType: {cat}\nEnseignant: {teacher}\nGroupes: {', '.join(set(groups))}\nLieu: {location}"
            
            events.append({
                "title": title,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "location": location,
                "description": desc,
                "category": cat,
                "teacher": teacher
            })
            
    return events



def fetch_edtts_events(target_group: str) -> list:
    '''Récupère les cours via la nouvelle URL mmi.unilim.fr (sans VPN).'''
    import urllib.request
    import json
    
    print(f"[*] --- Récupération des événements EDTTS pour le groupe {target_group} ---")
    manifest_url = "https://mmi.unilim.fr/edtts/pub/gea/manifest.json"
    base_url = "https://mmi.unilim.fr/edtts/pub/gea/"
    
    try:
        req = urllib.request.Request(manifest_url)
        with urllib.request.urlopen(req) as response:
            manifest = json.loads(response.read().decode())
    except Exception as e:
        print(f"[!] Erreur lors de la récupération du manifest : {e}")
        return []
        
    target_id_normalized = target_group.upper().replace(" ", "-").replace("_", "-")
    target_ics_url = None
    for cal_entry in manifest.get("calendars", []):
        if cal_entry.get("type") == "group" and cal_entry.get("id", "").upper() == target_id_normalized:
            target_ics_url = base_url + cal_entry["file"]
            break
            
    if not target_ics_url:
        print(f"[!] Aucun calendrier trouvé pour le groupe {target_id_normalized}.")
        return []
        
    print(f"[+] Téléchargement de l'ICS depuis : {target_ics_url}")
    try:
        req = urllib.request.Request(target_ics_url)
        with urllib.request.urlopen(req) as response:
            ics_content = response.read()
    except Exception as e:
        print(f"[!] Erreur lors du téléchargement de l'ICS : {e}")
        return []
        
    events = []
    try:
        import re
        cal = Calendar.from_ical(ics_content)
        for ev in cal.walk("VEVENT"):
            raw_summary = str(ev.get("summary", ""))
            raw_desc = str(ev.get("description", ""))
            raw_loc = str(ev.get("location", ""))
            
            start_dt = ev.get("dtstart").dt
            end_dt = ev.get("dtend").dt
            if isinstance(start_dt, datetime):
                start_dt = TZ.localize(start_dt) if start_dt.tzinfo is None else start_dt.astimezone(TZ)
                start_dt = start_dt.replace(tzinfo=None)
            if isinstance(end_dt, datetime):
                end_dt = TZ.localize(end_dt) if end_dt.tzinfo is None else end_dt.astimezone(TZ)
                end_dt = end_dt.replace(tzinfo=None)
                
            code_match = re.search(r'Code:\s*([^\n]+)', raw_desc)
            raw_code = code_match.group(1).strip() if code_match else raw_summary.split(' ')[0]
            
            teacher_match = re.search(r'Enseignant\(s\):\s*([^\n]+)', raw_desc)
            teacher = teacher_match.group(1).strip() if teacher_match else ''
            
            group_match = re.search(r'Groupe\(s\):\s*([^\n]+)', raw_desc)
            groups = group_match.group(1).strip() if group_match else ''
            
            course_type = get_event_category(raw_summary, raw_desc, f"{raw_code} {teacher}")
            title = resolve_course_title(raw_code, course_type, teacher)
            
            location = f"Salle {raw_loc} - IUT Limoges" if raw_loc and not raw_loc.startswith("Salle") else (raw_loc or "IUT Limoges")
            desc = f"Cours: {title}\nType: {course_type}\nEnseignant: {teacher}\nGroupes: {groups}\nLieu: {location}"
            
            events.append({
                "title": title,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "location": location,
                "description": desc,
                "category": course_type,
                "teacher": teacher
            })
    except Exception as e:
        print(f"[!] Erreur lors du parsing de l'ICS : {e}")
        
    print(f"[+] {len(events)} cours récupérés depuis EDTTS.")
    return events

def generate_ics_file(events: list, output_path: Path) -> None:
    """Génère un fichier standard .ics (iCalendar RFC 5545)."""
    cal = Calendar()
    cal.add("prodid", "-//Unilim EDT Sync//Pirkah//FR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", f"Cours IUT BUT GEA {TARGET_GROUP}")
    cal.add("x-wr-timezone", "Europe/Paris")
    
    for ev in events:
        e = Event()
        e.add("summary", ev["title"])
        e.add("dtstart", TZ.localize(ev["start_dt"]))
        e.add("dtend", TZ.localize(ev["end_dt"]))
        e.add("location", vText(ev["location"]))
        e.add("description", vText(ev["description"]))
        uid = f"{ev['start_dt'].strftime('%Y%m%d%H%M')}-{re.sub(r'[^a-zA-Z0-9]', '', ev['title'])[:20]}@unilim.fr"
        e.add("uid", uid)
        e.add("dtstamp", datetime.now(TZ))
        cal.add_component(e)
        
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())
        
    print(f"[+] Fichier ICS exporté avec succès : {output_path} ({len(events)} événements)")


def send_apple_notifications(title: str, subtitle: str, message: str, sound: str = "Glass") -> None:
    """Envoie une notification locale sur Mac + une notification Push sur iPhone via Rappels iCloud."""
    t = title.replace('"', '\\"')
    s = subtitle.replace('"', '\\"')
    m = message.replace('"', '\\"')
    
    # 1. Bannière de notification sur Mac
    scpt_mac = f'display notification "{m}" with title "{t}" subtitle "{s}" sound name "{sound}"'
    subprocess.run(["osascript", "-e", scpt_mac], capture_output=True, text=True)
    
    # 2. Push sur iPhone via Rappels Apple (liste dédiée 'Unilim EDT' synchronisée iCloud)
    scpt_iphone = f'''
    tell application "Reminders"
        if not (exists (first list whose name is "Unilim EDT")) then
            make new list with properties {{name:"Unilim EDT"}}
        end if
        tell list "Unilim EDT"
            delete every reminder
            make new reminder with properties {{name:"{t} : {s}", body:"{m}", due date:(current date)}}
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", scpt_iphone], capture_output=True, text=True)


def sync():
    """Point d'entrée principal de la synchronisation."""
    print("=" * 60)
    print(f"🚀 SYNCHRONISATION EDT UNILIM -> APPLE CALENDAR iCLOUD ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})")
    print(f"👤 Étudiant : {CAS_USERNAME} | Groupe : {TARGET_GROUP}")
    print(f"☁️  Calendriers iCloud : CM | TD | TP | Contrôles")
    print("=" * 60)
    
    # 1. Récupérer les événements depuis toutes les sources (Community IUT + ADE Campus)
    events = fetch_edtts_events(TARGET_GROUP)
    
    if not events:
        print("[!] Aucun événement récupéré. Vérifiez les identifiants ou l'accès réseau.")
        send_apple_notifications(
            title="Unilim EDT Sync ⚠️",
            subtitle="Mise à jour impossible",
            message="Vérifiez votre connexion ou relancez la validation 2FA (login.py)."
        )
        return
        
    # 2. Sauvegarder le fichier .ics local
    ics_path = BASE_DIR / "unilim_edt.ics"
    generate_ics_file(events, ics_path)
    
    # 3. Nettoyage ciblé : Uniquement à partir d'AUJOURD'HUI pour préserver les anciens jours
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    latest_dt = max(e["end_dt"] for e in events)
    print(f"[*] Nettoyage des événements futurs (du {today_start.strftime('%d/%m')} au {latest_dt.strftime('%d/%m')}, anciens jours préservés)...")
    clean_target_range_events(today_start, latest_dt)
    
    # 4. Injecter les événements futurs / en cours dans les 4 calendriers iCloud
    future_events = [e for e in events if e["end_dt"] >= today_start]
    success_count = insert_events_by_category(future_events, chunk_size=20)
    print(f"✅ SYNCHRONISATION RÉUSSIE : {success_count}/{len(future_events)} cours futurs injectés dans CM, TD, TP, Contrôles (anciens cours conservés) !")
    
    # 5. Notifications automatiques Mac + iPhone (iCloud)
    send_apple_notifications(
        title="Unilim EDT Sync 🎓",
        subtitle="Emploi du temps à jour ✅",
        message=f"{success_count} cours synchronisés sur iCloud ({TARGET_GROUP})."
    )


if __name__ == "__main__":
    sync()
