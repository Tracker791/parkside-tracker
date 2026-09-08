"""
Lidl store-locator scraper.

Uporablja isti javni (v uradnem Lidl "poisci trgovino" frontend JS-u
razkrit, brez potrebe po prijavi/skrivnem kljucu) API, ki ga uporablja
uradni store-finder widget na lidl.<xx> straneh:

    https://live.api.schwarz/odj/stores-api/v2/myapi/stores-frontend/stores

Ta klic NE deluje neposredno iz brskalnika (CORS dovoljuje samo uradne
Lidl domene), zato podatke poberemo tukaj (server-side, brez CORS
omejitev) in jih zapisemo v staticno datoteko, ki jo stran nalozi šele,
ko uporabnik odpre panel "Trgovine v blizini" (lazy-load, da ne
napihuje glavnega data.js).

12.000+ trgovin po Evropi je preveliko za podrobne podatke o vsaki -
zato hranimo le minimalen nabor polj (ime, naslov, koordinate, redni
tedenski urnik), brez opisov/ikon/prihodnjih izjem.
"""

import json
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
STORES_FILE = BASE_DIR / "data" / "stores.json"

STORES_API = "https://live.api.schwarz/odj/stores-api/v2/myapi/stores-frontend/stores"
STORES_API_KEY = "16QaHsGX3Uc3JLhNlS2ZG1CmosbzVPs2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "x-apikey": STORES_API_KEY,
}

# Ista drzavna koda (assortment), ki jo uporablja tudi scraper.py za
# Parkside izdelke.
COUNTRY_CODES = [
    "SI", "HR", "AT", "DE", "FR", "IT", "PL", "ES", "GB", "CZ", "SK", "PT",
    "HU", "IE", "GR", "BG", "RO", "RS", "SE", "LT", "LV", "EE", "BE", "CH",
    "CY", "MT", "LU", "NL",
]

PAGE_SIZE = 100
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def compact_hours(general_opening_hours):
    """Iz {regular: {monday: [{from,to}], ...}} naredi kompakten seznam po
    tednu (mon..sun) kot niz "HH:MM-HH:MM" (vec obdobij locenih z vejico),
    ali null za zaprto - brez tega bi gnezdeni objekti s ponovljenimi
    kljuci "from"/"to" pri 12.000+ trgovinah nepotrebno napihnili datoteko."""
    regular = (general_opening_hours or {}).get("regular") or {}
    out = []
    for day in WEEKDAYS:
        ranges = regular.get(day) or []
        if not ranges:
            out.append(None)
        else:
            out.append(",".join(f"{r.get('from')}-{r.get('to')}" for r in ranges))
    return out


def fetch_country_stores(country_code: str) -> list:
    stores = []
    offset = 0
    while True:
        url = (
            f"{STORES_API}?limit={PAGE_SIZE}&offset={offset}"
            f"&country_code={country_code}&expand=GENERAL_HOURS"
        )
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        stores.extend(items)
        total = (data.get("meta") or {}).get("total", len(stores))
        offset += PAGE_SIZE
        if offset >= total or not items:
            break
    return stores


def extract_store(raw: dict, country_code: str):
    """Vrne kompakten POZICIJSKI seznam (ne slovar) - pri 12.000+ trgovinah
    bi ponavljanje polnih imen kljucev v vsakem zapisu podvojilo velikost
    datoteke. Vrstni red ustreza STORE_FIELDS v index.html (stores.js)."""
    addr = raw.get("address") or {}
    lat, lng = addr.get("latitude"), addr.get("longitude")
    if lat is None or lng is None:
        return None
    street = " ".join(
        p for p in [addr.get("streetName"), addr.get("streetNumber")] if p
    )
    return [
        raw.get("objectNumber"),
        raw.get("storeName"),
        country_code,
        street or None,
        addr.get("zip"),
        addr.get("city"),
        lat,
        lng,
        compact_hours(raw.get("generalOpeningHours")),
    ]


def main():
    all_stores = []
    had_error = False
    for cc in COUNTRY_CODES:
        print(f"Pobiram trgovine za {cc} ...")
        try:
            raw_stores = fetch_country_stores(cc)
        except Exception as exc:  # noqa: BLE001
            had_error = True
            print(f"  NAPAKA pri {cc}: {exc}", file=sys.stderr)
            continue
        extracted = [s for s in (extract_store(r, cc) for r in raw_stores) if s]
        print(f"  {len(extracted)} trgovin")
        all_stores.extend(extracted)

    STORES_FILE.parent.mkdir(exist_ok=True)
    STORES_FILE.write_text(json.dumps(all_stores, ensure_ascii=False), encoding="utf-8")
    print(f"\nShranjeno {len(all_stores)} trgovin v {STORES_FILE}")
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
