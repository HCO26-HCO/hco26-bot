"""
Bot Telegram HCO26
Publie automatiquement les produits du Google Sheets (ou de produits.csv)
sur le canal, répartis régulièrement sur la journée.
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
DATE_DEBUT = "2026-10-05"    # jour où le 1er produit de la liste est publié (AAAA-MM-JJ)
PRODUITS_PAR_JOUR = 30
HEURE_DEBUT = 9              # premier post de la journée (heure de Paris)
HEURE_FIN = 19               # dernier créneau avant cette heure
LIGNE_CODE = "🎁 Code HCO26 = -15%"
MAX_PAR_PASSAGE = 4          # sécurité : jamais plus de 4 posts d'un coup en cas de retard
# Google Sheets lu en priorité (partage : "Tous les utilisateurs disposant du lien").
# Laisser vide ("") pour utiliser uniquement produits.csv.
GOOGLE_SHEET_ID = "17RFadumTVXrIIZr6aTUKrTx4FnoqA5HJVHY7NS6XJ6U"
# =========================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TEST = os.environ.get("TEST") == "1"   # TEST=1 => affiche sans rien publier
FUSEAU = ZoneInfo("Europe/Paris")
FICHIER_CSV = "produits.csv"
FICHIER_PUBLIES = "publies.txt"
DOSSIER_PHOTOS = "photos"   # photo "40.jpg" = ligne 40 du Google Sheets
API = f"https://api.telegram.org/bot{TOKEN}"


def lire_sheet():
    """Télécharge le Google Sheets en CSV. Renvoie None si impossible."""
    if not GOOGLE_SHEET_ID:
        return None
    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
    try:
        r = requests.get(url, timeout=30)
        r.encoding = "utf-8"
        texte = r.text
        if r.ok and "lien" in texte.split("\n", 1)[0].lower() and not texte.lstrip().startswith("<"):
            print("📄 Produits lus depuis le Google Sheets")
            return texte
        print(f"⚠️ Google Sheets illisible (code {r.status_code}) : vérifie qu'il est partagé "
              "avec « Tous les utilisateurs disposant du lien ». -> j'utilise produits.csv")
    except requests.RequestException as e:
        print(f"⚠️ Google Sheets injoignable ({e}) -> j'utilise produits.csv")
    return None


def lire_produits():
    contenu = lire_sheet()
    if contenu is None:
        with open(FICHIER_CSV, encoding="utf-8-sig", newline="") as f:
            contenu = f.read()
    contenu = contenu.lstrip("﻿")
    premiere_ligne = contenu.split("\n", 1)[0]
    # Excel en français enregistre avec des ";" -> on détecte tout seul
    sep = ";" if premiere_ligne.count(";") > premiere_ligne.count(",") else ","
    produits = []
    lecteur = csv.DictReader(io.StringIO(contenu), delimiter=sep)
    for ligne in lecteur:
        numero = lecteur.line_num  # numéro de la ligne dans le Sheets (1 = en-têtes)
        ligne = {k.strip().lower(): (v or "").strip() for k, v in ligne.items() if k}
        if not ligne.get("photo") and ligne.get("photo_url"):
            ligne["photo"] = ligne["photo_url"]
        ligne["photo_locale"] = photo_locale(numero)
        if ligne.get("lien"):
            produits.append(ligne)
    return produits


def photo_locale(numero):
    """Cherche photos/<numero>.jpg (ou .jpeg, .png, .webp) dans le repo."""
    for ext in ("jpg", "jpeg", "png", "webp", "JPG", "JPEG", "PNG", "WEBP"):
        chemin = os.path.join(DOSSIER_PHOTOS, f"{numero}.{ext}")
        if os.path.exists(chemin):
            return chemin
    return ""


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
    message = p.get("message", "")
    lignes = [message, p["lien"]]
    # pas de doublon si le message parle déjà du code HCO26
    if "hco26" not in message.lower():
        lignes.append(LIGNE_CODE)
    return "\n".join(l for l in lignes if l)


def appel_telegram(methode, donnees, fichier=None):
    for _ in range(3):
        if fichier:
            with open(fichier, "rb") as f:
                r = requests.post(f"{API}/{methode}", data=donnees, files={"photo": f}, timeout=60)
        else:
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
        print(f"[TEST] photo : {p.get('photo_locale') or p.get('photo') or '(aucune)'}\n{texte}\n")
        return True
    if p.get("photo_locale"):
        r = appel_telegram("sendPhoto", {"chat_id": CANAL, "caption": texte}, fichier=p["photo_locale"])
        if r.ok:
            return True
        print(f"⚠️ Photo du dossier refusée ({r.text})")
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
    print(f"{len(produits)} produits dans la liste | {len(publies)} déjà publiés | "
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
        print("🎉 Tout a été publié, pense à ajouter les produits de la semaine suivante !")


if __name__ == "__main__":
    main()
