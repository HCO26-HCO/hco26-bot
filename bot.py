"""
Bot Telegram HCO26
Publie automatiquement les produits de produits.csv sur le canal,
répartis régulièrement sur la journée.
"""
import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ================= RÉGLAGES (à modifier) =================
CANAL = "@HCO26link"
DATE_DEBUT = "2026-10-02"    # jour où le 1er produit du CSV est publié (AAAA-MM-JJ)
PRODUITS_PAR_JOUR = 30
HEURE_DEBUT = 9              # premier post de la journée (heure de Paris)
HEURE_FIN = 19               # dernier créneau avant cette heure
LIGNE_CODE = "🎁 Code HCO26 = -15%"
MAX_PAR_PASSAGE = 4          # sécurité : jamais plus de 4 posts d'un coup en cas de retard
# =========================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TEST = os.environ.get("TEST") == "1"   # TEST=1 => affiche sans rien publier
FUSEAU = ZoneInfo("Europe/Paris")
FICHIER_CSV = "produits.csv"
FICHIER_PUBLIES = "publies.txt"
API = f"https://api.telegram.org/bot{TOKEN}"


def lire_produits():
    with open(FICHIER_CSV, encoding="utf-8-sig", newline="") as f:
        contenu = f.read()
    premiere_ligne = contenu.split("\n", 1)[0]
    # Excel en français enregistre avec des ";" -> on détecte tout seul
    sep = ";" if premiere_ligne.count(";") > premiere_ligne.count(",") else ","
    produits = []
    for ligne in csv.DictReader(io.StringIO(contenu), delimiter=sep):
        ligne = {k.strip().lower(): (v or "").strip() for k, v in ligne.items() if k}
        if ligne.get("lien"):
            produits.append(ligne)
    return produits


def lire_publies():
    if not os.path.exists(FICHIER_PUBLIES):
        return set()
    with open(FICHIER_PUBLIES, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def noter_publie(lien):
    with open(FICHIER_PUBLIES, "a", encoding="utf-8") as f:
        f.write(lien + "\n")


def heure_prevue(index):
    jour = index // PRODUITS_PAR_JOUR
    rang = index % PRODUITS_PAR_JOUR
    debut = datetime.fromisoformat(DATE_DEBUT).replace(hour=HEURE_DEBUT, tzinfo=FUSEAU)
    minutes_dispo = (HEURE_FIN - HEURE_DEBUT) * 60
    return debut + timedelta(days=jour, minutes=rang * minutes_dispo / PRODUITS_PAR_JOUR)


def legende(p):
    lignes = [p.get("message", ""), p["lien"], LIGNE_CODE]
    return "\n".join(l for l in lignes if l)


def appel_telegram(methode, donnees):
    for _ in range(3):
        r = requests.post(f"{API}/{methode}", data=donnees, timeout=30)
        if r.status_code == 429:  # Telegram demande d'attendre
            attente = r.json().get("parameters", {}).get("retry_after", 10)
            time.sleep(attente + 1)
            continue
        return r
    return r


def envoyer(p):
    texte = legende(p)
    if TEST:
        print(f"[TEST] photo : {p.get('photo') or '(aucune)'}\n{texte}\n")
        return True
    if p.get("photo"):
        r = appel_telegram("sendPhoto", {"chat_id": CANAL, "photo": p["photo"], "caption": texte})
        if r.ok:
            return True
        print(f"⚠️ Photo refusée ({r.text}) -> envoi en texte seul")
    r = appel_telegram("sendMessage", {"chat_id": CANAL, "text": texte})
    if not r.ok:
        print(f"❌ Échec : {r.text}")
    return r.ok


def main():
    if not TOKEN and not TEST:
        sys.exit("TELEGRAM_TOKEN manquant (à mettre dans les Secrets GitHub).")

    produits = lire_produits()
    publies = lire_publies()
    maintenant = datetime.now(FUSEAU)

    en_attente = [
        p for i, p in enumerate(produits)
        if p["lien"] not in publies and heure_prevue(i) <= maintenant
    ]
    print(f"{len(produits)} produits dans le CSV | {len(publies)} déjà publiés | "
          f"{len(en_attente)} à publier maintenant")

    for p in en_attente[:MAX_PAR_PASSAGE]:
        if envoyer(p):
            if not TEST:
                noter_publie(p["lien"])
            print(f"✅ Publié : {p['lien']}")
        time.sleep(3)

    restants = [(i, p) for i, p in enumerate(produits) if p["lien"] not in lire_publies()]
    futurs = [heure_prevue(i) for i, _ in restants if heure_prevue(i) > maintenant]
    if futurs:
        print(f"Prochain post prévu : {min(futurs):%d/%m à %H:%M}")
    elif not restants:
        print("🎉 Tout le CSV a été publié, pense à mettre les produits de la semaine suivante !")


if __name__ == "__main__":
    main()
