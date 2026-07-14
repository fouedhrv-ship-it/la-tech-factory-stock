#!/usr/bin/env python3
"""
La Tech Factory - surveillance publique du stock et des fiches produits.

Ce script :
1. Crawle le site public page par page, en partant de la page d'accueil et en
   suivant tous les liens internes (categories, sous-categories, marques,
   fabricants...), SANS se baser sur le sitemap.xml. Chaque page produit est
   reperee via la structure propre a ses cartes produit (lien avec la classe
   "cursor-pointer"), ce qui permet de lister la totalite des produits reels
   du site, sans doublon.
2. Pour chaque page produit, détecte :
   - si le texte "rupture de stock" est présent (produit épuisé) ;
   - le nombre de photos réelles du produit (via les attributs alt des balises
     <img>, en excluant les vignettes de variantes de couleur).
3. Met à jour un Google Sheet à deux onglets :
   - "Rupture de stock"   -> produits en rupture de stock
   - "Moins de 4 photos"  -> produits avec 0 à 3 photos

Authentification Google : compte de service (voir README.md), lu depuis la
variable d'environnement GCP_SA_KEY (contenu JSON complet de la clé).

Aucune information de connexion au site la-tech-factory.com n'est utilisée :
uniquement des pages publiques, en lecture seule.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urljoin

import requests
import gspread
from google.oauth2.service_account import Credentials

SITE = "https://la-tech-factory.com"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1v32NNkVbxbqT7H66Cc0S95UPIDzfZ2MDqI5GbqSinEY")
STOCK_SHEET = "Rupture de stock"
PHOTOS_SHEET = "Moins de 4 photos"
PHOTO_THRESHOLD = 4
MAX_WORKERS = 10
REQUEST_TIMEOUT = 20
MAX_CRAWL_PAGES = 50000  # garde-fou anti-boucle infinie uniquement : le crawl est
# volontairement complet et refait de zéro chaque matin (pas d'incrémental), pour
# ne jamais rater les ~15 nouveaux produits ajoutés chaque jour sur le site. Cette
# limite est très large pour ne jamais être atteinte en pratique.

H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
ALT_RE = re.compile(r'alt="([^"]*)"')
HREF_RE = re.compile(r'href="([^"]+)"')
PRODUCT_LINK_RE = re.compile(r'<a class="cursor-pointer[^"]*"\s+href="([^"]+)"')

EXCLUDED_PREFIXES = ("/_next", "/assets", "/favicon", "/api")


def clean(text: str) -> str:
    return unescape(TAG_RE.sub("", text)).strip()


def _fetch(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def discover_product_urls() -> list[str]:
    """Crawle le site page par page (accueil, catégories, sous-catégories,
    marques, fabricants...) sans utiliser le sitemap, et retourne la liste
    dédupliquée de toutes les URLs de pages produit trouvées."""
    visited: set[str] = set()
    product_urls: set[str] = set()
    frontier = [SITE + "/"]

    while frontier and len(visited) < MAX_CRAWL_PAGES:
        batch = [u for u in frontier if u not in visited][:MAX_WORKERS]
        if not batch:
            break
        frontier = [u for u in frontier if u not in batch]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            html_by_url = dict(zip(batch, pool.map(_fetch, batch)))

        next_links: set[str] = set()
        for url, html in html_by_url.items():
            visited.add(url)
            if not html:
                continue

            page_products = {urljoin(SITE, m.group(1)) for m in PRODUCT_LINK_RE.finditer(html)}
            product_urls.update(page_products)

            for m in HREF_RE.finditer(html):
                href = m.group(1)
                if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                if href.startswith("http") and not href.startswith(SITE):
                    continue  # lien externe
                if any(href.startswith(p) for p in EXCLUDED_PREFIXES):
                    continue
                full = urljoin(SITE, href.split("?")[0].split("#")[0])
                if not full.startswith(SITE):
                    continue
                if full in page_products:
                    continue  # déjà identifié comme produit, pas besoin de le re-crawler comme page de liste
                if full not in visited:
                    next_links.add(full)

        frontier.extend(sorted(next_links - visited))

    return sorted(product_urls)


def analyze_product(url: str) -> dict:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        html = r.text
    except requests.RequestException as exc:
        return {"url": url, "title": None, "out_of_stock": False, "photo_count": -1, "error": str(exc)}

    h1_match = H1_RE.search(html)
    title = clean(h1_match.group(1)) if h1_match else None

    out_of_stock = "rupture de stock" in html.lower()

    photo_count = -1
    if title:
        alts = [unescape(a).strip() for a in ALT_RE.findall(html)]
        product_alts = {
            a for a in alts
            if (a == title or a.startswith(title + " - Vue")) and "- Variante" not in a
        }
        photo_count = len(product_alts)

    return {"url": url, "title": title, "out_of_stock": out_of_stock, "photo_count": photo_count}


def crawl() -> list[dict]:
    urls = discover_product_urls()
    print(f"Pages produit découvertes par le crawl : {len(urls)}")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_product, u): u for u in urls}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def get_worksheet(gc: gspread.Client, title: str):
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(title)


def replace_data_rows(ws: gspread.Worksheet, rows: list[list[str]]) -> None:
    """Keep the header row (row 1), clear the rest, and write fresh rows."""
    existing_row_count = ws.row_count
    if existing_row_count > 1:
        ws.batch_clear([f"A2:Z{existing_row_count}"])
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def main() -> int:
    sa_key_raw = os.environ.get("GCP_SA_KEY")
    if not sa_key_raw:
        print("ERREUR: variable d'environnement GCP_SA_KEY manquante.", file=sys.stderr)
        return 1

    creds = Credentials.from_service_account_info(
        json.loads(sa_key_raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)

    print(f"Crawl de {SITE} (public uniquement)...")
    results = crawl()
    errors = [r for r in results if r.get("error")]
    valid = [r for r in results if not r.get("error")]

    out_of_stock_rows = [
        [r["title"] or r["url"], "Rupture de stock", r["url"]]
        for r in valid if r["out_of_stock"]
    ]
    low_photo_rows = [
        [r["title"] or r["url"], r["photo_count"], r["url"]]
        for r in valid if 0 <= r["photo_count"] < PHOTO_THRESHOLD
    ]

    stock_ws = get_worksheet(gc, STOCK_SHEET)
    replace_data_rows(stock_ws, out_of_stock_rows)

    photos_ws = get_worksheet(gc, PHOTOS_SHEET)
    replace_data_rows(photos_ws, low_photo_rows)

    print(f"Produits analysés : {len(valid)} (erreurs : {len(errors)})")
    print(f"Rupture de stock  : {len(out_of_stock_rows)}")
    print(f"Moins de {PHOTO_THRESHOLD} photos : {len(low_photo_rows)}")
    if errors:
        print("URLs en erreur :", [e["url"] for e in errors], file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
