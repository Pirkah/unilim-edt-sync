#!/usr/bin/env python3
"""
Unilim EDT Sync - Synchronisation automatique vers Apple Calendar (iCloud)
Auteur: Julien Nicolle
Synchronisation dans les 3 calendriers iCloud : CM (Rose), TD (Vert), TP (Bleu)
"""

import os
import re
import sys
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

CAS_USERNAME = os.getenv("CAS_USERNAME", os.getenv("UNILIM_USERNAME", ""))
CAS_PASSWORD = os.getenv("CAS_PASSWORD", os.getenv("UNILIM_PASSWORD", ""))
TARGET_GROUP = os.getenv("TARGET_GROUP", "GEMA1 TP2")
TZ = pytz.timezone("Europe/Paris")

# Calendriers cibles sur iCloud
ICLOUD_CALENDARS = {
    "CM": "CM",
    "TD": "TD",
    "TP": "TP"
}


def clean_target_range_events(start_dt: datetime, end_dt: datetime) -> None:
    """Nettoie la plage glissante sur les calendriers iCloud CM, TD, TP."""
    subprocess.run(["open", "-a", "Calendar"])
    s_str = start_dt.strftime("%d/%m/%Y 00:00:00")
    e_str = (end_dt + timedelta(days=1)).strftime("%d/%m/%Y 23:59:59")
    
    lines = []
    for c_name in ICLOUD_CALENDARS.values():
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


def get_event_category(title: str, description: str) -> str:
    """Détermine la catégorie (CM, TD ou TP) pour l'aiguillage dans le bon calendrier iCloud."""
    t = (title + " " + description).upper()
    if re.search(r'\bTP\d*\b', title.upper()) or "TP GEMA" in description.upper() or "PPP (TP" in title.upper():
        return "TP"
    if re.search(r'\bCM\d*\b', title.upper()) or "CM BUT" in description.upper() or "RÉUNION DE RENTRÉE" in t:
        return "CM"
    return "TD"


def insert_events_by_category(events: list, chunk_size: int = 20) -> int:
    """Insère les cours dans les calendriers iCloud CM, TD et TP."""
    subprocess.run(["open", "-a", "Calendar"])
    total_success = 0
    
    # Regrouper par catégorie
    categorized = {"CM": [], "TD": [], "TP": []}
    for ev in events:
        cat = get_event_category(ev["title"], ev["description"])
        categorized[cat].append(ev)
        
    for cat, cat_events in categorized.items():
        if not cat_events:
            continue
            
        c_name = ICLOUD_CALENDARS[cat]
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


async def scrape_unilim_edt(num_weeks: int = 2) -> list:
    """Récupère l'emploi du temps depuis ADE Campus via Playwright."""
    print(f"[*] Démarrage du scraping Playwright pour {CAS_USERNAME} (horizon: {num_weeks} semaines, groupe: {TARGET_GROUP})...")
    
    all_extracted_events = []
    profile_dir = BASE_DIR / ".browser_profile"
    profile_dir.mkdir(exist_ok=True)
    auth_file = BASE_DIR / "auth_state.json"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context_kwargs = {"viewport": {"width": 1400, "height": 900}}
        if auth_file.exists():
            print(f"[*] Chargement de la session sauvegardée depuis {auth_file.name}...")
            context_kwargs["storage_state"] = str(auth_file)
            
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        
        # 1. Accès et Authentification
        print("[*] Accès à ADE Campus...")
        await page.goto("https://planning.unilim.fr/direct/myplanning.jsp", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        if "cas.unilim.fr" in page.url:
            print("[*] Authentification CAS Unilim...")
            await page.fill('input[name="user"]', CAS_USERNAME)
            await page.fill('input[name="password"]', CAS_PASSWORD)
            stay = page.locator('input[name="stayconnected"]').first
            if await stay.count() > 0:
                await stay.check()
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)
            
        # Sauvegarder l'état pour les prochaines requêtes
        await context.storage_state(path=str(auth_file))
        print("[+] Connecté avec succès!")
        
        # 2. Navigation dans l'arbre vers BUT 2 GEA GEMA Semestre 3
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
        
        print("[+] Cours chargés dans le planning!")
        
        # 3. Récupération des 2 semaines cibles (semaine actuelle + semaine suivante)
        target_weeks = await page.evaluate('''() => {
            const allWeekBtns = Array.from(document.querySelectorAll('.x-btn-text')).filter(b => {
                const t = b.innerText || '';
                return t.startsWith('S') && t.includes(' du ');
            });
            
            let activeIdx = allWeekBtns.findIndex(b => {
                const parent = b.closest('.x-btn, table, td');
                return parent && (parent.className.includes('pressed') || parent.className.includes('active') || parent.className.includes('focus'));
            });
            
            if (activeIdx === -1) {
                activeIdx = allWeekBtns.findIndex(b => b.innerText.includes('31 août') || b.innerText.includes('S36'));
            }
            if (activeIdx === -1) activeIdx = 0;
            
            return allWeekBtns.slice(activeIdx, activeIdx + 2).map(b => b.innerText.trim());
        }''')
        
        print(f"[+] Semaines cibles détectées : {target_weeks}")
        
        # 4. Extraction des cours pour chacune des 2 semaines
        for week_idx, w_label in enumerate(target_weeks):
            print(f"[*] Analyse de la semaine {week_idx + 1}/{len(target_weeks)} : {w_label}...")
            
            if week_idx > 0:
                w_code = w_label.split(' ')[0]
                print(f"    -> Basculement vers {w_code}...")
                target_btn = page.locator('.x-btn-text').filter(has_text=w_code).first
                if await target_btn.count() > 0:
                    await target_btn.click()
                    await page.wait_for_timeout(2500)
            
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
                    if (rect.left > 200 && rect.width > 50 && rect.height > 25 && t.includes('h') && (t.includes('CM') || t.includes('TD') || t.includes('TP') || t.includes('AUTONOMIE') || t.includes('SAE') || t.includes('R3.') || t.includes('Réunion') || t.includes('REUNION') || t.includes('Contrôle'))) {
                        const hasMatchingChild = Array.from(d.querySelectorAll('div')).some(child => {
                            const ct = child.innerText || '';
                            return ct.includes('h') && (ct.includes('CM') || ct.includes('TD') || ct.includes('TP') || ct.includes('AUTONOMIE') || ct.includes('SAE') || ct.includes('R3.'));
                        });
                        if (!hasMatchingChild) {
                            const cx = (rect.left + rect.right) / 2;
                            const day = days.find(dayObj => cx >= dayObj.left && cx <= dayObj.right);
                            matches.push({
                                text: t.trim(),
                                day: day ? day.text : null
                            });
                        }
                    }
                }
                return matches;
            }''')
            
            print(f"    -> {len(cards)} séances détectées au planning cette semaine")
            
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
                
                # Filtrage précis selon le groupe cible (ex: GEMA1 TP2)
                my_td = "GEMA1" if "GEMA1" in TARGET_GROUP else "GEMA2"
                my_tp = "TP2" if "TP2" in TARGET_GROUP else "TP1"
                
                group_lines = [l for l in lines if any(k in l for k in ["CM", "TD", "TP", "GEMA"])]
                
                # 1. Si c'est un CM pur (CM BUT2 pour toute la promo) -> on garde
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
                    all_extracted_events.append({
                        "title": title,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                        "location": location,
                        "description": description,
                        "teacher": teacher
                    })
                    
        await browser.close()
        
    # Déduplication stricte par clé unique (titre, date début, date fin)
    unique_events = []
    seen = set()
    for ev in all_extracted_events:
        key = (ev["title"], ev["start_dt"], ev["end_dt"])
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)
            
    print(f"[+] Total de cours uniques filtrés ({TARGET_GROUP}) : {len(unique_events)}")
    return unique_events


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


def sync():
    """Point d'entrée principal de la synchronisation."""
    print("=" * 60)
    print(f"🚀 SYNCHRONISATION EDT UNILIM -> APPLE CALENDAR iCLOUD ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})")
    print(f"👤 Étudiant : {CAS_USERNAME} | Groupe : {TARGET_GROUP}")
    print(f"☁️  Calendriers iCloud : CM | TD | TP")
    print("=" * 60)
    
    # 1. Récupérer les événements via Playwright (2 prochaines semaines)
    events = asyncio.run(scrape_unilim_edt(num_weeks=2))
    
    if not events:
        print("[!] Aucun événement récupéré. Vérifiez les identifiants ou l'accès réseau.")
        return
        
    # 2. Sauvegarder le fichier .ics local
    ics_path = BASE_DIR / "unilim_edt.ics"
    generate_ics_file(events, ics_path)
    
    # 3. Nettoyage de la plage et injection dans les 3 calendriers iCloud
    earliest_dt = min(e["start_dt"] for e in events)
    latest_dt = max(e["end_dt"] for e in events)
    print(f"[*] Nettoyage de la plage du {earliest_dt.strftime('%d/%m')} au {latest_dt.strftime('%d/%m')} dans CM, TD, TP...")
    clean_target_range_events(earliest_dt, latest_dt)
    
    success_count = insert_events_by_category(events, chunk_size=20)
    print(f"✅ SYNCHRONISATION RÉUSSIE : {success_count}/{len(events)} cours injectés dans les calendriers iCloud CM, TD, TP !")


if __name__ == "__main__":
    sync()
