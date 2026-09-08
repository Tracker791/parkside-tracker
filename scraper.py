"""
Parkside availability scraper for Lidl Slovenija, Lidl Hrvaska in Lidl Austria.

Uporablja interni Lidl iskalni API (/q/api/search) na kategoriji
"Vse za dom in vrt" (category.id=10068222), ki je ista za vse tri drzave.
Ta kategorija vsebuje trenutno aktivno DIY/vrtno ponudbo (v veliki vecini
znamke Parkside), skupaj z znamko "Parkside Performance" kot locenim
brand-facetom.

Za vsak izdelek izlusci ceno, kategorijo in datume veljavnosti ponudbe
(startDate/endDate po regijah, ce so na voljo), ter zapise rezultat v
data/products.json in data.js (za prikaz v index.html).

Vsak nov zagon primerja rezultate s prejsnjim zagonom in oznaci nove
izdelke ter izdelke, ki so spremenili ceno/razpolozljivost/status.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
CATALOG_FILE = DATA_DIR / "performance_catalog.json"
DATA_JS_FILE = BASE_DIR / "data.js"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "sl,en;q=0.8",
}

HOME_GARDEN_CATEGORY_ID = "10068222"

COUNTRIES = {
    "si": {
        "label": "Lidl Slovenija",
        "domain": "https://www.lidl.si",
        "assortment": "SI",
        "locale": "sl_SI",
    },
    "hr": {
        "label": "Lidl Hrvaška",
        "domain": "https://www.lidl.hr",
        "assortment": "HR",
        "locale": "hr_HR",
    },
    "at": {
        "label": "Lidl Austria",
        "domain": "https://www.lidl.at",
        "assortment": "AT",
        "locale": "de_AT",
    },
}


def search_api_url(domain: str, assortment: str, locale: str, extra: str = "") -> str:
    return (
        f"{domain}/q/api/search?offset=0&fetchsize=250&locale={locale}"
        f"&assortment={assortment}&version=2.1.0&category.id={HOME_GARDEN_CATEGORY_ID}{extra}"
    )


def fetch_category(domain: str, assortment: str, locale: str) -> dict:
    url = search_api_url(domain, assortment, locale)
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.json()


def is_performance(brand: str, title: str) -> bool:
    text = f"{brand or ''} {title or ''}".lower()
    return "performance" in text


WARRANTY_KEYWORDS = ("garanc", "jamstv", "garantie", "warranty")


def extract_warranty_years(seals: list) -> int | None:
    """Sezname pecatov/sealov Lidl uporablja za garancijsko oznako (npr.
    '5-letna garancija', '5 godina jamstva', 'Garantie ... 5 ... Jahre').
    Ker je besedilo v razlicnih jezikih razlicno formatirano, preverimo le,
    ali pecat sploh omenja garancijo in ali vsebuje '3' ali '5'."""
    years = []
    for s in seals or []:
        text = (s.get("altText") or "").lower()
        if not any(k in text for k in WARRANTY_KEYWORDS):
            continue
        if re.search(r"\b5\b", text):
            years.append(5)
        elif re.search(r"\b3\b", text):
            years.append(3)
    return max(years) if years else None


def is_x20v_team(seals: list, description: str) -> bool:
    combined = " ".join((s.get("altText") or "") for s in (seals or [])) + " " + (description or "")
    combined = combined.lower()
    return "x 20 v team" in combined or "x20v team" in combined


def worth_it_assessment(is_perf: bool, warranty_years, x20v: bool):
    """Objektivna, iz podatkov razvidna ocena 'vredno cene' - NI izmisljena
    ocena kakovosti, temvec preprost, pregleden kriterij:
      - 5-letna garancija -> Parkside najvisje zaupa temu izdelku (obicajno
        Performance linija z brezkrtacnim motorjem)
      - del baterijskega sistema X 20 V TEAM -> ce ze imas kompatibilno
        baterijo, je "gola" naprava veliko ceneje kot enakovredno orodje
        drugje, ker ne placas se enkrat za baterijo/polnilnik
    """
    reasons = []
    if warranty_years == 5:
        reasons.append("5-letna garancija (Parkside najvišji nivo zaupanja)")
    if is_perf:
        reasons.append("Parkside Performance – brezkrtačni motor")
    if x20v:
        reasons.append("Del sistema X 20 V TEAM – poceni, če že imaš baterijo")
    return bool(reasons), reasons


# Rocno preverjeni razponi cen primerljivih akumulatorskih orodij uveljavljenih
# znamk (Bosch, Einhell, Black+Decker) na slovenskih primerjalnikih cen
# (ceneje.si, preverjeno 2026-09). Ni popolna/samodejna primerjava vsakega
# modela - gre za tipicno ceno PRIMERLJIVEGA orodja v isti kategoriji, da
# damo realen obcutek, koliko bi isto orodje stalo pri drugi znamki.
COMPETITOR_REFERENCE = [
    {
        "keywords": ["kotni brusilnik", "kutna brusilic", "winkelschleifer"],
        "label": "akumulatorski kotni brusilnik",
        "low": 58, "high": 100,
        "note": "Einhell/Bosch akumulatorski kotni brusilnik, brez baterije (ceneje.si)",
    },
    {
        "keywords": ["škarje za živo mejo", "škare za živic", "heckenschere"],
        "label": "akumulatorske škarje za živo mejo",
        "low": 120, "high": 220,
        "note": "Bosch primerljive akumulatorske škarje za živo mejo, ~55-60 cm rezilo (ceneje.si)",
    },
    {
        "keywords": ["verižna žaga", "lančana pila", "kettensäge", "kettensaege"],
        "label": "akumulatorska verižna žaga",
        "low": 131, "high": 164,
        "note": "Bosch EasyChain 18V akumulatorska verižna žaga (ceneje.si)",
    },
    {
        "keywords": [
            "pihalnik za listje", "puhalnik za listje", "puhač lišć", "puhac lisc",
            "laubbläser", "laubblaeser", "turbinenlaubbläser",
        ],
        "label": "akumulatorski puhalnik/sesalnik listja",
        "low": 64, "high": 137,
        "note": "Bosch / Black+Decker akumulatorski puhalnik listja 18V (ceneje.si)",
    },
]


def is_battery_powered_title(title: str) -> bool:
    """Filter proti neposteni primerjavi: naslov mora eksplicitno navajati
    akumulatorski/battery pogon, sicer bi lahko rocno ali omrezno (corded)
    orodje primerjali s cenami akumulatorske konkurence, kar bi umetno
    napihnilo 'prihranek'."""
    t = (title or "").lower()
    if "akumulator" in t or "akku" in t:
        return True
    return bool(re.search(r"\baku\b", t))


def match_competitor_reference(title: str, price):
    if not title or price is None or not is_battery_powered_title(title):
        return None
    text = title.lower()
    for ref in COMPETITOR_REFERENCE:
        if any(kw in text for kw in ref["keywords"]):
            if price < ref["low"]:
                return {
                    "label": ref["label"],
                    "competitorLow": ref["low"],
                    "competitorHigh": ref["high"],
                    "note": ref["note"],
                    "savingsMin": round(ref["low"] - price, 2),
                    "savingsMax": round(ref["high"] - price, 2),
                }
            return None
    return None


def epoch_to_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def extract_fields(gb_data: dict, domain: str) -> dict:
    keyfacts = gb_data.get("keyfacts") or {}
    price_info = gb_data.get("price") or {}
    brand = (gb_data.get("brand") or {}).get("name")
    title = keyfacts.get("fullTitle") or keyfacts.get("title")

    # Cenovno okno (regionsPrices) pove, koliko casa velja TA cena - to je
    # praviloma sirsi/celoten kataloški cikel, NE dejanski datum dobave v
    # trgovino. Dejanski datum, kdaj je izdelek FIZICNO na voljo v trgovini,
    # je v "stockAvailability" / "storeStartDate" / "storeEndDate".
    regions = []
    for region_id, rp in (gb_data.get("regionsPrices") or {}).items():
        cp = (rp or {}).get("currentPrice") or {}
        discount = cp.get("discount") or {}
        regions.append({
            "region": region_id,
            "startDate": cp.get("startDate"),
            "endDate": cp.get("endDate"),
            "discountText": discount.get("discountText"),
        })

    price_start_dates = [r["startDate"] for r in regions if r["startDate"]]
    price_end_dates = [r["endDate"] for r in regions if r["endDate"]]

    stock = gb_data.get("stockAvailability") or {}
    badges = (stock.get("badgeInfo") or {}).get("badges") or []
    badge_text = badges[0].get("text") if badges else None

    store_start = epoch_to_iso(gb_data.get("storeStartDate"))
    store_end = epoch_to_iso(gb_data.get("storeEndDate"))

    # Prednost: dejanski datum dobave v trgovino (storeStartDate/storeEndDate).
    # Ce ga ni, uporabi cenovno okno kot priblizek.
    available_from = store_start or (min(price_start_dates) if price_start_dates else None)
    available_until = store_end or (max(price_end_dates) if price_end_dates else None)

    canonical = gb_data.get("canonicalUrl") or gb_data.get("canonicalPath")
    url = f"{domain}{canonical}" if canonical and canonical.startswith("/") else canonical

    image = gb_data.get("image") or (gb_data.get("image_V1") or {}).get("image")
    pid = gb_data.get("productId") or gb_data.get("itemId")
    ean = (gb_data.get("ians") or [None])[0]
    description = keyfacts.get("description")
    perf = is_performance(brand, title)

    seals = gb_data.get("seals") or []
    warranty_years = extract_warranty_years(seals)
    x20v = is_x20v_team(seals, description)
    price = (price_info or {}).get("price")
    competitor = match_competitor_reference(title, price)

    worth_it, worth_it_reasons = worth_it_assessment(perf, warranty_years, x20v)
    if competitor:
        worth_it = True
        worth_it_reasons.append(
            f"Cenejše od konkurence: {competitor['label']} pri drugih znamkah "
            f"{competitor['competitorLow']:.0f}–{competitor['competitorHigh']:.0f}€"
        )

    return {
        "id": pid,
        "key": ean or f"id:{pid}",
        "ean": ean,
        "title": title,
        "shortTitle": keyfacts.get("title"),
        "description": description,
        "image": image,
        "brand": brand,
        "price": price,
        "currency": (price_info or {}).get("currencyCode"),
        "online": gb_data.get("online"),
        "inStoreNow": gb_data.get("store"),
        "onlineAvailable": stock.get("onlineAvailable"),
        "availabilityBadge": badge_text,
        "category": keyfacts.get("wonCategoryPrimary"),
        "url": url,
        "regions": regions,
        "warrantyYears": warranty_years,
        "isX20vTeam": x20v,
        "competitorReference": competitor,
        "worthIt": worth_it,
        "worthItReasons": worth_it_reasons,
        "availableFrom": available_from,
        "availableUntil": available_until,
        "isPerformance": perf,
    }


def scrape_country(cfg: dict):
    payload = fetch_category(cfg["domain"], cfg["assortment"], cfg["locale"])
    items = payload.get("items", [])
    products = []
    for item in items:
        gb_data = ((item or {}).get("gridbox") or {}).get("data")
        if not gb_data:
            continue
        p = extract_fields(gb_data, cfg["domain"])
        if p["id"] is not None:
            products.append(p)

    brand_counts = {}
    for facet in payload.get("facets", []):
        if facet.get("code") == "brand":
            for v in facet.get("values", []):
                brand_counts[v.get("label")] = v.get("count")

    return products, payload.get("numFound"), brand_counts


def load_previous():
    if PRODUCTS_FILE.exists():
        try:
            return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def load_catalog():
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def catalog_key(p: dict) -> str:
    return p.get("key") or p["ean"] or f"id:{p['id']}"


def update_catalog(catalog: dict, country_products: dict, generated_at: str) -> dict:
    """Vzdrzuje trajen seznam VSEH Parkside Performance orodij, ki so bila
    kdajkoli zaznana - tudi ko izdelek izgine iz trenutne tedenske ponudbe.
    Isto fizicno orodje se v razlicnih drzavah pojavi pod razlicnim
    productId, zato za dedupliciranje uporabimo EAN (polje 'ean'/'ians'),
    ki je za isti izdelek enak ne glede na drzavo."""

    for entry in catalog.values():
        entry["currentListings"] = []
        entry["currentlyListed"] = False

    for country_code, products in country_products.items():
        for p in products:
            if not p.get("isPerformance"):
                continue
            key = catalog_key(p)
            entry = catalog.setdefault(key, {
                "key": key,
                "ean": p["ean"],
                "firstSeenAt": generated_at,
                "countriesSeen": [],
                "currentListings": [],
                "currentlyListed": False,
            })
            entry["title"] = p["title"] or entry.get("title")
            entry["image"] = p["image"] or entry.get("image")
            entry["category"] = p["category"] or entry.get("category")
            entry["lastSeenAt"] = generated_at
            entry["currentlyListed"] = True
            if country_code not in entry["countriesSeen"]:
                entry["countriesSeen"].append(country_code)
            entry["currentListings"].append({
                "country": country_code,
                "price": p["price"],
                "currency": p["currency"],
                "url": p["url"],
                "availableFrom": p["availableFrom"],
                "availableUntil": p["availableUntil"],
                "availabilityBadge": p["availabilityBadge"],
            })

    return catalog


TRACKED_FIELDS = ("price", "online", "inStoreNow", "availableFrom", "availableUntil", "worthIt")


def diff_against_previous(country_code: str, products: list, previous: dict):
    old_products = {}
    if previous:
        for p in previous.get("countries", {}).get(country_code, {}).get("products", []):
            old_products[p["id"]] = p

    for p in products:
        old = old_products.get(p["id"])
        if old is None:
            p["status"] = "new"
            p["changedFields"] = []
        else:
            changed = [f for f in TRACKED_FIELDS if old.get(f) != p.get(f)]
            p["status"] = "changed" if changed else "same"
            p["changedFields"] = changed
            p["previous"] = {f: old.get(f) for f in changed} if changed else {}
    return products


def main():
    previous = load_previous()
    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "countries": {},
    }

    had_error = False
    for code, cfg in COUNTRIES.items():
        print(f"Pobiram {cfg['label']} (category {HOME_GARDEN_CATEGORY_ID}, {cfg['assortment']}) ...")
        try:
            products, num_found, brand_counts = scrape_country(cfg)
        except Exception as exc:  # noqa: BLE001
            had_error = True
            print(f"  NAPAKA pri {cfg['label']}: {exc}", file=sys.stderr)
            old = (previous or {}).get("countries", {}).get(code)
            result["countries"][code] = {
                "label": cfg["label"],
                "domain": cfg["domain"],
                "error": str(exc),
                "products": (old or {}).get("products", []),
                "numFound": (old or {}).get("numFound"),
                "brandCounts": (old or {}).get("brandCounts", {}),
            }
            continue

        products = diff_against_previous(code, products, previous)
        new_count = sum(1 for p in products if p["status"] == "new")
        changed_count = sum(1 for p in products if p["status"] == "changed")
        perf_count = sum(1 for p in products if p["isPerformance"])
        print(
            f"  {len(products)} izdelkov (numFound={num_found}), "
            f"Parkside Performance: {perf_count}, novih: {new_count}, spremenjenih: {changed_count}"
        )

        result["countries"][code] = {
            "label": cfg["label"],
            "domain": cfg["domain"],
            "error": None,
            "products": products,
            "numFound": num_found,
            "brandCounts": brand_counts,
        }

    country_products = {
        code: c["products"] for code, c in result["countries"].items()
    }
    catalog = load_catalog()
    catalog = update_catalog(catalog, country_products, result["generatedAt"])
    result["performanceCatalog"] = sorted(
        catalog.values(), key=lambda e: (e.get("title") or "").lower()
    )

    DATA_DIR.mkdir(exist_ok=True)
    PRODUCTS_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    CATALOG_FILE.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    DATA_JS_FILE.write_text(
        "window.__PARKSIDE_DATA__ = " + json.dumps(result, ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    print(f"\nShranjeno v {PRODUCTS_FILE}, {CATALOG_FILE} in {DATA_JS_FILE}")
    print(f"Katalog Parkside Performance orodij skupaj: {len(catalog)}")
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
