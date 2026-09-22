#!/usr/bin/env python3
"""
Unilim EDT Sync - Synchronisation automatique de l'emploi du temps vers Apple Calendar (iCloud)
Supporte :
1. Community IUT (Moodle - Section Emploi du temps & dossiers de semaines)
2. ADE Campus (planning.unilim.fr)
3. Résolution automatique des codes matières (R3.06 -> Contrôle de gestion, etc.) via Signatures Unilim
4. Aiguillage automatique en 4 calendriers : CM, TD, TP, et Contrôles / Évaluations
Auteur: Julien Nicolle
"""

import os
import re
import sys
import json
import asyncio
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
import pytz
from icalendar import Calendar, Event, vText
from playwright.async_api import async_playwright

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


def resolve_course_title(raw_code: str, course_type: str) -> str:
    """
    Associe le code matière (ex: R3.06, R3.GEMA.13, SAE3.01) à son nom officiel issu de signatures.unilim.fr.
    Ne confond jamais les salles (ex: R04, R01, 103) avec un code matière.
    """
    clean_code = raw_code.strip()
    
    # 1. Si le titre contient déjà un nom explicite (ex: 'TC R3.04 Fiscalité (CM01)')
    if any(m in clean_code.lower() for m in ["fiscalit", "gestion", "juridique", "finance", "communication", "anglais", "business model", "droit", "numérique"]):
        return clean_code
        
    # 2. Extraire le code canonique (ex: R3.06, R3.GEMA.13 -> R3.13, SAE3.01 -> SAE3.01)
    # Attention: R\d{2} seul (ex: R04) est une salle, pas un code matière (qui a toujours un point R3. ou R4.)
    m = re.search(r'(R[34]\.(?:GEMA\.|GCFF\.|GPRH\.)?(\d{2}))|(SAE\s*3\.?\d*)', clean_code, re.I)
    
    name = ""
    if m:
        if m.group(1):
            full_r, num = m.group(1), m.group(2)
            prefix = full_r[:2] # R3 ou R4
            norm_key = f"{prefix}.{num}"
            name = COURSES_DICTIONARY.get(norm_key, "")
        elif m.group(3):
            sae_str = m.group(3).upper().replace(" ", "")
            norm_key = "SAE3.01" if "3.1" in sae_str or "3.01" in sae_str else "SAE3.02"
            name = COURSES_DICTIONARY.get(norm_key, "")
            
    suffix = "Contrôle" if course_type == "EVAL" else f"({course_type})"
    
    if name:
        # Formater proprement: ex 'R3.06 Contrôle de gestion (TD)'
        return f"{clean_code} {name} {suffix}"
    else:
        return f"{clean_code} {suffix}"


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
    # 1. Fond jaune sur ADE Campus -> 100% Évaluation / Contrôle
    if is_yellow:
        return "EVAL"
        
    full_text = f"{title} {description} {raw_text}"
    
    # Exclure le terme pédagogique "Contrôle de gestion"
    check_text = re.sub(r'contr[oô]le\s+de\s+gestion', '', full_text, flags=re.I)
    
    # 2. Détection des Évaluations / Contrôles / DS / Examens
    eval_patterns = [
        r'\bCONTROLE\b', r'\bCONTRÔLE\b', r'\bEVALUATION\b', r'\bÉVALUATION\b',
        r'\bEVAL\b', r'\bEXAMEN\b', r'\bPARTIEL\b', r'\bDS\b', r'\bDS\d+\b',
        r'\bDEVOIR\s+SURVEILL[EÉ]\b', r'\bINTERROGATION\b', r'\bTEST\b', r'\bQCM\b'
    ]
    if any(re.search(p, check_text, re.I) for p in eval_patterns):
        return "EVAL"
        
    # 3. Détection du type de cours (CM, TD, TP)
    # Nettoyer les mentions de groupe comme 'GEMA1-TP1', 'GEMA1-TP2' pour ne pas fausser la détection
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
    
    # Regrouper par catégorie
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


async def fetch_community_iut_events(context) -> list:
    """Récupère les cours publiés sur Community IUT (Moodle GEA) avec enrichissement des noms de matières."""
    print(f"\n[*] --- Connexion à Community IUT (Moodle GEA) pour {TARGET_GROUP} ---")
    page = context.pages[0] if context.pages else await context.new_page()
    download_dir = BASE_DIR / "downloaded_edt"
    download_dir.mkdir(exist_ok=True)
    
    events = []
    group_norm = re.sub(r'[^A-Z0-9]', '', TARGET_GROUP.upper()) # GEMA1TP2
    
    try:
        # 1. Authentification CAS pour Community IUT
        await page.goto("https://community-iut.unilim.fr/login/index.php?authCAS=CAS", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        if "cas.unilim.fr" in page.url:
            print("[*] Connexion CAS Unilim pour Community IUT...")
            await page.fill('input[name="user"]', CAS_USERNAME)
            await page.fill('input[name="password"]', CAS_PASSWORD)
            stay = page.locator('input[name="stayconnected"]').first
            if await stay.count() > 0:
                await stay.check()
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
            
        # 2. Accès à la section EMPLOIS DU TEMPS
        course_url = "https://community-iut.unilim.fr/course/view.php?id=1790&section=1#tabs-tree-start"
        print(f"[*] Accès à {course_url}...")
        await page.goto(course_url, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # 3. Récupérer tous les dossiers de semaines (ex: 'Semaine 39', 'S40', 'S41', etc.)
        folders = await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href*="mod/folder/view.php"]')).map(a => ({
                title: a.innerText.trim(),
                href: a.href
            })).filter(f => {
                const t = f.title.toLowerCase();
                return f.href.includes('mod/folder') && (
                    t.includes('semaine') || 
                    t.includes('sem') || 
                    /^s\d+/i.test(t) || 
                    /\b\d{1,2}\b/.test(t) ||
                    t.includes('dossier')
                );
            });
            
            const unique = [];
            const seen = new Set();
            for (const f of links) {
                if (!seen.has(f.href)) {
                    seen.add(f.href);
                    unique.push(f);
                }
            }
            return unique;
        }''')
        
        print(f"[+] Dossiers de semaines détectés sur Community IUT : {[f['title'].splitlines()[0] for f in folders]}")
        
        for f in folders:
            folder_title = f['title'].splitlines()[0].strip()
            folder_url = f['href']
            print(f"[*] Analyse de {folder_title} ({folder_url})...")
            await page.goto(folder_url, wait_until="networkidle")
            await page.wait_for_timeout(1500)
            
            files = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.href
                })).filter(l => l.href.includes('pluginfile.php') || l.text.includes('.ics') || l.text.includes('.pdf'));
            }''')
            
            # Rechercher le fichier ICS correspondant à notre groupe
            target_file = None
            for file_info in files:
                fn_norm = re.sub(r'[^A-Z0-9]', '', file_info['text'].upper())
                fn_href = file_info['href'].upper()
                if group_norm in fn_norm and ('.ICS' in fn_norm or '.ICS' in fn_href):
                    target_file = file_info
                    break
                    
            if target_file:
                print(f"    -> Téléchargement de {target_file['text']}...")
                async with page.expect_download() as download_info:
                    await page.locator(f'a:has-text("{target_file["text"]}")').first.click()
                download = await download_info.value
                save_file = download_dir / f"{folder_title.replace(' ', '_')}_{download.suggested_filename}"
                await download.save_as(save_file)
                print(f"    [+] Fichier sauvegardé : {save_file}")
                
                # Parser et corriger le fichier ICS
                with open(save_file, "rb") as fp:
                    cal = Calendar.from_ical(fp.read())
                    
                for ev in cal.walk("VEVENT"):
                    raw_summary = str(ev.get("summary", ""))
                    raw_desc = str(ev.get("description", ""))
                    raw_loc = str(ev.get("location", ""))
                    
                    start_dt = ev.get("dtstart").dt
                    end_dt = ev.get("dtend").dt
                    if isinstance(start_dt, datetime):
                        start_dt = TZ.localize(start_dt) if start_dt.tzinfo is None else start_dt.astimezone(TZ)
                        start_dt = start_dt.replace(tzinfo=None) # Stocker en heure locale naïve pour AppleScript
                    if isinstance(end_dt, datetime):
                        end_dt = TZ.localize(end_dt) if end_dt.tzinfo is None else end_dt.astimezone(TZ)
                        end_dt = end_dt.replace(tzinfo=None)
                        
                    code_match = re.search(r'Code:\s*([^\n]+)', raw_desc)
                    raw_code = code_match.group(1).strip() if code_match else raw_summary.split(' ')[0]
                    
                    teacher_match = re.search(r'Enseignant\(s\):\s*([^\n]+)', raw_desc)
                    teacher = teacher_match.group(1).strip() if teacher_match else ''
                    
                    group_match = re.search(r'Groupe\(s\):\s*([^\n]+)', raw_desc)
                    groups = group_match.group(1).strip() if group_match else ''
                    
                    # Déterminer la catégorie (EVAL, TP, CM ou TD)
                    course_type = get_event_category(raw_summary, raw_desc, f"{raw_code} {teacher}")
                    
                    # Résoudre le nom complet de la matière via le référentiel signatures.unilim.fr
                    title = resolve_course_title(raw_code, course_type)
                    
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
            else:
                print(f"    [!] Aucun fichier ICS trouvé pour {TARGET_GROUP} dans {folder_title}")
                
    except Exception as e:
        print(f"[!] Erreur lors de la récupération Community IUT : {e}")
        
    print(f"[+] Total cours extraits depuis Community IUT : {len(events)}")
    return events


async def scrape_ade_campus_events(context, num_weeks: int = 3) -> list:
    """Récupère l'emploi du temps depuis ADE Campus via Playwright."""
    print(f"\n[*] --- Consultation ADE Campus (planning.unilim.fr) ---")
    page = context.pages[0] if context.pages else await context.new_page()
    all_extracted_events = []
    
    try:
        await page.goto("https://planning.unilim.fr/direct/myplanning.jsp", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        if "cas.unilim.fr" in page.url:
            print("[*] Authentification CAS Unilim (ADE Campus)...")
            await page.fill('input[name="user"]', CAS_USERNAME)
            await page.fill('input[name="password"]', CAS_PASSWORD)
            stay = page.locator('input[name="stayconnected"]').first
            if await stay.count() > 0:
                await stay.check()
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
            
        async def click_node(name):
            loc = page.get_by_text(name, exact=False).first
            await loc.scroll_into_view_if_needed()
            await loc.dblclick()
            await page.wait_for_timeout(1500)
            
        print("[*] Navigation vers Semestre 3 GEA GEMA...")
        await click_node("Groupes Etudiants")
        await click_node("I. U. T. du Limousin")
        await click_node("BACHELOR UNIVERSITAIRE DE TECHNOLOGIE")
        
        tree_scroller = page.locator(".x-grid3-scroller").first
        await tree_scroller.evaluate("el => el.scrollTop = 350")
        await page.wait_for_timeout(1000)
        
        await click_node("BUT 2 - GEA LIMOGES - GEMA")
        await page.wait_for_timeout(1000)
        await click_node("Semestre 3")
        await page.wait_for_timeout(3000)
        
        now = datetime.now()
        current_iso_week = now.isocalendar()[1]
        target_week_codes = [f"S{current_iso_week + i}" for i in range(num_weeks)]
        
        for week_idx, w_code in enumerate(target_week_codes):
            target_btn = page.locator('.x-btn-text').filter(has_text=re.compile(rf'^{w_code}\b')).first
            if await target_btn.count() > 0:
                await target_btn.click()
                await page.wait_for_timeout(2000)
            else:
                alt_btn = page.locator('.x-btn-text').filter(has_text=w_code).first
                if await alt_btn.count() > 0:
                    await alt_btn.click()
                    await page.wait_for_timeout(2000)
            
            cards = await page.evaluate('''() => {
                const dayHeaders = Array.from(document.querySelectorAll('div, td, span')).filter(e => {
                    const t = e.innerText || '';
                    return (t.startsWith('Lundi ') || t.startsWith('Mardi ') || t.startsWith('Mercredi ') || t.startsWith('Jeudi ') || t.startsWith('Vendredi ')) && t.includes('/');
                });
                
                const days = dayHeaders.map(dh => {
                    const rect = dh.getBoundingClientRect();
                    return { text: dh.innerText.trim(), left: rect.left, right: rect.right };
                });
                
                const allDivs = Array.from(document.querySelectorAll('div'));
                const matches = [];
                for (const d of allDivs) {
                    const t = d.innerText || '';
                    const rect = d.getBoundingClientRect();
                    if (rect.left > 200 && rect.width > 50 && rect.height > 25 && t.includes('h') && (t.includes('CM') || t.includes('TD') || t.includes('TP') || t.includes('AUTONOMIE') || t.includes('SAE') || t.includes('R3.') || t.includes('Réunion') || t.includes('REUNION') || t.includes('Contrôle') || t.includes('Evaluation') || t.includes('DS'))) {
                        const hasMatchingChild = Array.from(d.querySelectorAll('div')).some(child => {
                            const ct = child.innerText || '';
                            return ct.includes('h') && (ct.includes('CM') || ct.includes('TD') || ct.includes('TP') || ct.includes('AUTONOMIE') || ct.includes('SAE') || ct.includes('R3.'));
                        });
                        if (!hasMatchingChild) {
                            const cx = (rect.left + rect.right) / 2;
                            const day = days.find(dayObj => cx >= dayObj.left && cx <= dayObj.right);
                            const bg = window.getComputedStyle(d).backgroundColor || '';
                            const isYellow = bg.includes('255, 255') || bg.includes('255, 235') || bg.includes('255, 240') || bg.includes('yellow');
                            matches.push({
                                text: t.trim(),
                                day: day ? day.text : null,
                                isYellow: isYellow
                            });
                        }
                    }
                }
                return matches;
            }''')
            
            for card in cards:
                if not card["day"]:
                    continue
                lines = [l.strip() for l in card["text"].split("\n") if l.strip()]
                if not lines:
                    continue
                    
                date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', card["day"])
                if not date_match:
                    continue
                day_val, month_val, year_val = map(int, date_match.groups())
                
                time_line_idx = -1
                start_h, start_m, end_h, end_m = 8, 0, 10, 0
                for idx, line in enumerate(lines):
                    tm = re.search(r'(\d{1,2})h(\d{2})\s*-\s*(\d{1,2})h(\d{2})', line)
                    if tm:
                        start_h, start_m, end_h, end_m = map(int, tm.groups())
                        time_line_idx = idx
                        break
                        
                if time_line_idx == -1:
                    continue
                    
                start_dt = datetime(year_val, month_val, day_val, start_h, start_m)
                end_dt = datetime(year_val, month_val, day_val, end_h, end_m)
                title = lines[0]
                
                location = "IUT Limoges"
                teacher = ""
                groups = []
                
                for idx, line in enumerate(lines[1:], 1):
                    if idx == time_line_idx:
                        continue
                    if re.match(r'^(Amphi\s+[A-Z0-9]+|\d{3}|R\.\d{2}|R\d{2})$', line, re.I):
                        location = f"Salle {line} - IUT Limoges"
                    elif any(g in line for g in ["CM", "TD", "TP", "GEMA"]):
                        groups.append(line)
                    elif not any(char.isdigit() for char in line) and len(line) > 3:
                        teacher = line
                        
                description = f"Cours: {title}\nGroupes: {', '.join(set(groups))}\nEnseignant: {teacher}\nLieu: {location}"
                
                my_td = "GEMA1" if "GEMA1" in TARGET_GROUP else "GEMA2"
                my_tp = "TP2" if "TP2" in TARGET_GROUP else "TP1"
                group_lines = [l for l in lines if any(k in l for k in ["CM", "TD", "TP", "GEMA"])]
                
                if group_lines and all(l.startswith("CM") for l in group_lines):
                    is_for_user = True
                else:
                    has_my_td = any(f"TD {my_td}" in l for l in lines)
                    has_other_td = any(bool(re.search(r'TD\s+GEMA[234]', l)) if my_td == "GEMA1" else bool(re.search(r'TD\s+GEMA1', l)) for l in lines)
                    has_my_tp = any(f"{my_tp}" in l for l in lines)
                    has_other_tp = any(("TP1" in l if my_tp == "TP2" else "TP2" in l) for l in lines)
                    
                    is_for_user = True
                    if has_other_td and not has_my_td:
                        is_for_user = False
                    elif any("TP" in l for l in lines) and has_other_tp and not has_my_tp:
                        is_for_user = False
                    
                if is_for_user:
                    cat = get_event_category(title, description, card["text"], is_yellow=card.get("isYellow", False))
                    resolved_title = resolve_course_title(title, cat)
                    all_extracted_events.append({
                        "title": resolved_title,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                        "location": location,
                        "description": description,
                        "category": cat,
                        "teacher": teacher
                    })
    except Exception as e:
        print(f"[!] Info ADE Campus : {e}")
        
    print(f"[+] Total cours extraits depuis ADE Campus : {len(all_extracted_events)}")
    return all_extracted_events


def merge_events_with_priority(community_events: list, ade_events: list) -> list:
    """
    Fusionne les événements en donnant la priorité absolue aux fichiers de Community IUT.
    Si un créneau horaire chevauche un cours des fichiers, le cours ADE est automatiquement ignoré.
    """
    print(f"\n[*] --- Fusion intelligente avec priorité aux fichiers de Community IUT ---")
    print(f"    -> Cours issus des fichiers (Community IUT) : {len(community_events)}")
    print(f"    -> Cours issus d'ADE Campus : {len(ade_events)}")
    
    final_events = list(community_events)
    ignored_ade_count = 0
    added_ade_count = 0
    
    for ade_ev in ade_events:
        ade_start = ade_ev["start_dt"]
        ade_end = ade_ev["end_dt"]
        
        # 1. Vérifier si un cours Community IUT chevauche ce créneau horaire
        conflict = False
        for com_ev in community_events:
            com_start = com_ev["start_dt"]
            com_end = com_ev["end_dt"]
            
            # Chevauchement temporel : (StartA < EndB) et (EndA > StartB)
            if (ade_start < com_end) and (ade_end > com_start):
                conflict = True
                ignored_ade_count += 1
                break
                
        if not conflict:
            if not any(e["title"] == ade_ev["title"] and e["start_dt"] == ade_ev["start_dt"] for e in final_events):
                final_events.append(ade_ev)
                added_ade_count += 1
                
    final_events.sort(key=lambda x: x["start_dt"])
    print(f"[+] Résultat de la fusion : {len(final_events)} cours retenus ({len(community_events)} fichiers + {added_ade_count} ADE uniques, {ignored_ade_count} doublons ADE ignorés)")
    return final_events


async def scrape_all_sources() -> list:
    """Récupère l'emploi du temps depuis Community IUT et ADE Campus, avec priorité absolue aux fichiers."""
    profile_dir = BASE_DIR / ".browser_profile"
    profile_dir.mkdir(exist_ok=True)
    auth_file = BASE_DIR / "auth_state.json"
    
    community_events = []
    ade_events = []
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            viewport={"width": 1400, "height": 900}
        )
        
        # 1. Récupération prioritaire sur Community IUT (fichiers hebdomadaires)
        community_events = await fetch_community_iut_events(context)
        
        # 2. Récupération complémentaire sur ADE Campus (fallback si besoin)
        ade_events = await scrape_ade_campus_events(context, num_weeks=3)
        
        # Sauvegarder la session active
        await context.storage_state(path=str(auth_file))
        await context.close()
        
    # Fusion avec priorité aux fichiers de Community IUT
    return merge_events_with_priority(community_events, ade_events)


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
    events = asyncio.run(scrape_all_sources())
    
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
