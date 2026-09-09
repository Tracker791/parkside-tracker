"""
Grizzly Tools (grizzlytools.shop) - katalog rezervnih delov za Parkside orodja.

Grizzly Tools je proizvajalec, ki za Lidl izdeluje vecino Parkside orodij, in
na svoji trgovini prodaja rezervne dele (baterije, polnilce, verige, rezila,
motorje ...) za VSAK Parkside model, ki ga je kdaj koli izdelal - tudi za
modele, ki jih Lidl ne prodaja vec. To je namenoma sirsi nabor kot nas
obstojeci scraper.py (ki sledi samo TRENUTNI Lidl ponudbi).

Stran je navadni server-rendered HTML (JTL-Shop), brez JS/API - zato jo
lahko poberemo z navadnimi HTTP zahtevami, enako kot scraper.py.

Struktura strani:
  Parkside_221 (koren znamke)
    -> vsaka "sub-categories" plosica je BODISI nadaljnja podkategorija
       (navadna povezava) BODISI neposredno model orodja (povezava "?k=NNNN")
    -> na strani modela (?k=NNNN) je seznam rezervnih delov zanj
       (vsak del je en "div.product-box" z schema.org mikropodatki za
       ime/ceno/valuto, plus "signal_image" razred za zalogo)

Ker isto plosico (in isti "?k=" model) najdemo prek vec razlicnih poti po
drevesu (npr. isti akumulator se pojavi pod "Batteries" in pod konkretnim
orodjem), model med obhodom deduplicira po njegovem "k" ID-ju.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
OUT_FILE = BASE_DIR / "data" / "spare_parts.json"

BASE_URL = "https://grizzlytools.shop"
PARKSIDE_ROOT = f"{BASE_URL}/Parkside_221?lang=eng"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en,sl;q=0.8",
}

# Koliko pocakamo med zahtevami - njihov streznik ni nas, zato ne silimo.
REQUEST_DELAY = 0.2


def fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(resp.text, "html.parser")


def get_tiles(soup: BeautifulSoup):
    """Vrne (href, label) za vse 'sub-categories' plosice na strani - to so
    lahko nadaljnje podkategorije ALI neposredno modeli orodij (?k=)."""
    tiles = []
    for box in soup.select("div.sub-categories"):
        a = box.find("a", href=True)
        if not a:
            continue
        img = box.find("img")
        label = ((img.get("alt") if img else None) or a.get_text(strip=True) or "").strip()
        if not label:
            continue
        tiles.append((urljoin(BASE_URL, a["href"]), label))
    return tiles


def crawl_models(start_url: str) -> dict:
    """Rekurzivno obhodi drevo podkategorij pod Parkside in vrne slovar
    {k_id: {"name":..., "url":...}} za vse najdene modele orodij."""
    seen_categories = set()
    models = {}

    def visit(url, category_label):
        if url in seen_categories:
            return
        seen_categories.add(url)
        try:
            soup = fetch_soup(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  NAPAKA pri kategoriji {url}: {exc}", file=sys.stderr)
            return
        for href, label in get_tiles(soup):
            match = re.search(r"[?&]k=(\d+)", href)
            if match:
                key = match.group(1)
                if key not in models:
                    # kategorija modela je stran, na kateri smo ga nasli
                    # (category_label), NE ime plosice (to je ime modela)
                    models[key] = {"name": label, "url": href, "category": category_label}
            else:
                visit(href, label)

    visit(start_url, "Parkside")
    return models


def parse_model_parts(url: str) -> list:
    soup = fetch_soup(url)
    parts = []
    for box in soup.select("div.product-box"):
        title_el = box.select_one(".productbox-title a")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        part_url = urljoin(BASE_URL, title_el.get("href") or "")
        brand_el = box.select_one(".manufacturer [itemprop=name]")
        brand = brand_el.get_text(strip=True) if brand_el else None
        price_el = box.select_one('meta[itemprop="price"]')
        price = None
        if price_el and price_el.get("content"):
            try:
                price = float(price_el["content"])
            except ValueError:
                price = None
        currency_el = box.select_one('meta[itemprop="priceCurrency"]')
        currency = currency_el.get("content") if currency_el else None
        status_el = box.select_one(".signal_image")
        stock = status_el.get_text(strip=True) if status_el else None

        parts.append({
            "name": name,
            "url": part_url,
            "brand": brand,
            "price": price,
            "currency": currency,
            "stock": stock,
        })
    return parts


def main():
    print("Iscem vse Parkside modele na grizzlytools.shop ...")
    models = crawl_models(PARKSIDE_ROOT)
    print(f"Najdenih modelov: {len(models)}")

    result = []
    had_error = False
    total = len(models)
    for i, (key, model) in enumerate(models.items(), 1):
        try:
            parts = parse_model_parts(model["url"])
        except Exception as exc:  # noqa: BLE001
            had_error = True
            print(f"  NAPAKA pri {model['name']}: {exc}", file=sys.stderr)
            continue
        if parts:
            result.append({
                "id": key,
                "name": model["name"],
                "url": model["url"],
                "category": model.get("category"),
                "parts": parts,
            })
        if i % 50 == 0 or i == total:
            print(f"  ... {i}/{total} modelov obdelanih")

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    total_parts = sum(len(m["parts"]) for m in result)
    print(f"Shranjeno {len(result)} modelov ({total_parts} rezervnih delov) v {OUT_FILE}")
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
