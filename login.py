#!/usr/bin/env python3
"""
Script d'authentification manuelle via interface graphique
Mémorise la session et les cookies dès l'arrivée sur ADE Campus.
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

CAS_USERNAME = os.getenv("CAS_USERNAME", os.getenv("UNILIM_USERNAME", ""))
CAS_PASSWORD = os.getenv("CAS_PASSWORD", os.getenv("UNILIM_PASSWORD", ""))

async def main():
    profile_dir = BASE_DIR / ".browser_profile"
    profile_dir.mkdir(exist_ok=True)
    auth_file = BASE_DIR / "auth_state.json"
    
    print("=" * 60)
    print("🌐 CONNEXION CAS UNILIM (VALIDATION A2F)")
    print("=" * 60)
    print("[*] Une fenêtre s'ouvre sur votre écran.")
    print("[*] Validez votre connexion avec le code reçu par mail.")
    print("[*] Dès que vous arrivez sur le site ADE Campus, la session sera enregistrée automatiquement !\n")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1200, "height": 800}
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        await page.goto("https://planning.unilim.fr/direct/myplanning.jsp")
        
        # Pré-remplir les identifiants depuis le .env
        try:
            if "cas.unilim.fr" in page.url and CAS_USERNAME and CAS_PASSWORD:
                await page.fill('input[name="user"]', CAS_USERNAME)
                await page.fill('input[name="password"]', CAS_PASSWORD)
                stay = page.locator('#stayconnected, input[name="stayconnected"]').first
                if await stay.count() > 0:
                    await stay.check()
        except Exception:
            pass
            
        print("[*] En attente de votre connexion...")
        
        # Attendre d'arriver sur ADE Campus (hors page CAS)
        for _ in range(300):
            try:
                if page.is_closed():
                    print("[-] Fenêtre fermée.")
                    break
                if "planning.unilim.fr" in page.url and "cas.unilim.fr" not in page.url and "login" not in page.url:
                    print("✅ SUCCÈS : Connexion confirmée sur ADE Campus !")
                    await page.wait_for_timeout(3000)
                    await context.storage_state(path=str(auth_file))
                    print(f"[+] Session et cookies enregistrés dans {auth_file.name} !")
                    break
            except Exception:
                break
            await asyncio.sleep(1)
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
