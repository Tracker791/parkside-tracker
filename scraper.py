"""
Parkside availability scraper for Lidl's European markets.

Uporablja interni Lidl iskalni API (/q/api/search) z generi_cnim iskanjem
"q=parkside" (brez omejitve na kategorijo) - to smo preverili, deluje
zanesljivo v vseh podprtih drzavah, medtem ko je konkretna kategorija
"Vse za dom in vrt" imela v razlicnih drzavah razlicne (in ne vedno
delujoce) ID-je. V manjsih trgih (SI/HR/AT/...) to ustreza tedenski
rotirajoci ponudbi, v vecjih trgih (DE/FR/CZ/SK/PL/ES/BE...) pa Lidl
prodaja precej sirsi, trajno dostopen Parkside asortiman.

Za vsak izdelek izlusci ceno, kategorijo in datume veljavnosti ponudbe
(startDate/endDate po regijah, ce so na voljo), ter zapise rezultat v
data/products.json in data.js (za prikaz v index.html).

Vsak nov zagon (urno) primerja rezultate z DNEVNIM izhodiscem (stanje ob
prvem zagonu tega koledarskega dne, po ljubljanskem casu) - ne z zadnjim
urnim zagonom. Tako znacka "SPREMEMBA" ostane vidna ves preostanek dneva,
ne le eno uro, izhodisce pa se osvezi ob prehodu na nov dan (prvi zagon po
polnoci). Oznaci nove izdelke ter izdelke, ki so od jutranjega izhodisca
spremenili ceno/razpolozljivost/status.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
CATALOG_FILE = DATA_DIR / "performance_catalog.json"
DAILY_BASELINE_FILE = DATA_DIR / "daily_baseline.json"
DATA_JS_FILE = BASE_DIR / "data.js"
LOCAL_TZ = ZoneInfo("Europe/Ljubljana")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "sl,en;q=0.8",
}

# Vsi Lidl trgi, kjer je Parkside preverjeno na voljo prek /q/api/search
# (preverjeno rocno, sept. 2026). Danska je izpuscena - Parkside tam ni
# zaznan. NL/FI trenutno vracata napako (bot-zascita) - pustimo ju v
# seznamu, saj scraper napake na posamezni drzavi obravnava locenu in ne
# vpliva na ostale; ce Lidl kdaj odblokira dostop, bosta zafunkcionirala
# sama od sebe.
COUNTRIES = {
    "si": {"label": "Lidl Slovenija", "domain": "https://www.lidl.si", "assortment": "SI", "locale": "sl_SI"},
    "hr": {"label": "Lidl Hrvaška", "domain": "https://www.lidl.hr", "assortment": "HR", "locale": "hr_HR"},
    "at": {"label": "Lidl Avstrija", "domain": "https://www.lidl.at", "assortment": "AT", "locale": "de_AT"},
    "de": {"label": "Lidl Nemčija", "domain": "https://www.lidl.de", "assortment": "DE", "locale": "de_DE"},
    "fr": {"label": "Lidl Francija", "domain": "https://www.lidl.fr", "assortment": "FR", "locale": "fr_FR"},
    "it": {"label": "Lidl Italija", "domain": "https://www.lidl.it", "assortment": "IT", "locale": "it_IT"},
    "pl": {"label": "Lidl Poljska", "domain": "https://www.lidl.pl", "assortment": "PL", "locale": "pl_PL"},
    "es": {"label": "Lidl Španija", "domain": "https://www.lidl.es", "assortment": "ES", "locale": "es_ES"},
    "gb": {"label": "Lidl Velika Britanija", "domain": "https://www.lidl.co.uk", "assortment": "GB", "locale": "en_GB"},
    "cz": {"label": "Lidl Češka", "domain": "https://www.lidl.cz", "assortment": "CZ", "locale": "cs_CZ"},
    "sk": {"label": "Lidl Slovaška", "domain": "https://www.lidl.sk", "assortment": "SK", "locale": "sk_SK"},
    "pt": {"label": "Lidl Portugalska", "domain": "https://www.lidl.pt", "assortment": "PT", "locale": "pt_PT"},
    "hu": {"label": "Lidl Madžarska", "domain": "https://www.lidl.hu", "assortment": "HU", "locale": "hu_HU"},
    "ie": {"label": "Lidl Irska", "domain": "https://www.lidl.ie", "assortment": "IE", "locale": "en_IE"},
    "gr": {"label": "Lidl Grčija", "domain": "https://www.lidl.gr", "assortment": "GR", "locale": "el_GR"},
    "bg": {"label": "Lidl Bolgarija", "domain": "https://www.lidl.bg", "assortment": "BG", "locale": "bg_BG"},
    "ro": {"label": "Lidl Romunija", "domain": "https://www.lidl.ro", "assortment": "RO", "locale": "ro_RO"},
    "rs": {"label": "Lidl Srbija", "domain": "https://www.lidl.rs", "assortment": "RS", "locale": "sr_RS"},
    "se": {"label": "Lidl Švedska", "domain": "https://www.lidl.se", "assortment": "SE", "locale": "sv_SE"},
    "lt": {"label": "Lidl Litva", "domain": "https://www.lidl.lt", "assortment": "LT", "locale": "lt_LT"},
    "lv": {"label": "Lidl Latvija", "domain": "https://www.lidl.lv", "assortment": "LV", "locale": "lv_LV"},
    "ee": {"label": "Lidl Estonija", "domain": "https://www.lidl.ee", "assortment": "EE", "locale": "et_EE"},
    "be": {"label": "Lidl Belgija", "domain": "https://www.lidl.be", "assortment": "BE", "locale": "nl_BE"},
    "ch": {"label": "Lidl Švica", "domain": "https://www.lidl.ch", "assortment": "CH", "locale": "de_CH"},
    "cy": {"label": "Lidl Ciper", "domain": "https://www.lidl.com.cy", "assortment": "CY", "locale": "el_CY"},
    "mt": {"label": "Lidl Malta", "domain": "https://www.lidl.com.mt", "assortment": "MT", "locale": "en_MT"},
    "lu": {"label": "Lidl Luksemburg", "domain": "https://www.lidl.lu", "assortment": "LU", "locale": "fr_LU"},
    "nl": {"label": "Lidl Nizozemska", "domain": "https://www.lidl.nl", "assortment": "NL", "locale": "nl_NL"},
}


def search_api_url(domain: str, assortment: str, locale: str, extra: str = "") -> str:
    return (
        f"{domain}/q/api/search?offset=0&fetchsize=1000&locale={locale}"
        f"&assortment={assortment}&version=2.1.0&q=parkside{extra}"
    )


def fetch_category(domain: str, assortment: str, locale: str) -> dict:
    url = search_api_url(domain, assortment, locale)
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.json()


# Iskalni API (/q/api/search) za nekatere izdelke ne vrne cene (price.price
# manjka, čeprav je izdelek "havingPrice": true in trenutno na voljo) - to je
# vrzel na Lidlovi strani, ne napaka pri nas. Cena PA je vedno prisotna na
# posamezni strani izdelka, vgrajena v Nuxt "__NUXT_DATA__" JSON (isti Vue/
# Nuxt frontend na vseh trgih). Zato za take izdelke kot rezervo poberemo se
# stran izdelka in ceno poiscemo tam - le za peščico izdelkov na zagon, saj
# je vecina cen ze na voljo iz iskalnega API-ja.
NUXT_DATA_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch_detail_price(url: str):
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        match = NUXT_DATA_RE.search(resp.text)
        if not match:
            return None
        arr = json.loads(match.group(1))
        for entry in arr:
            # "oldPrice" je bil prej pogoj, a se pojavi le pri izdelkih z
            # aktivnim popustom (precrtana stara cena) - za izdelke brez
            # popusta (npr. se ne na voljo, prihodnji artikli) ta kljuc
            # manjka, cetudi basePrice/price obstajata in sta veljavna.
            if isinstance(entry, dict) and "basePrice" in entry and "price" in entry:
                price_idx = entry.get("price")
                if isinstance(price_idx, int) and 0 <= price_idx < len(arr):
                    value = arr[price_idx]
                    if isinstance(value, (int, float)):
                        return float(value)
        return None
    except Exception:  # noqa: BLE001 - to je zgolj rezervni poskus, ne sme podreti scrapea
        return None


def is_performance(brand: str, title: str) -> bool:
    text = f"{brand or ''} {title or ''}".lower()
    return "performance" in text


def is_parkside_brand(brand: str) -> bool:
    """Iskanje "q=parkside" na Lidlovem API ni omejeno na blagovno znamko -
    vrne tudi nepovezane izdelke (pijace, igrace, meso ...), kadar beseda
    "parkside" nastopi kjerkoli v rezultatu (npr. otroska igraca teme
    "Parkside" pod znamko LUPILU/PLAYTIVE, ali celo zlepljeno ime znamke kot
    "PARKSIDE KONG STRONG" pri energijski pijaci). Zato preverimo z belim
    seznamom, ne s podnizom - blagovna znamka mora biti (skoraj) natanko
    "Parkside" ali "Parkside Performance" (dovoljen je simbol (R) oz.
    popacen zapis znaka zaradi kodiranja na koncu niza)."""
    normalized = re.sub(r"[^a-z ]", "", (brand or "").lower()).strip()
    return normalized in ("parkside", "parkside performance")


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

    Razlogi so vrnjeni kot strukturirani objekti (type + morebitni podatki),
    NE kot vnaprej izpisani slovenski stavki - tako jih lahko frontend
    prikaze v izbranem jeziku uporabnika (glej I18N v index.html).
    """
    reasons = []
    if warranty_years == 5:
        reasons.append({"type": "warranty5"})
    if is_perf:
        reasons.append({"type": "performance"})
    if x20v:
        reasons.append({"type": "x20v"})
    return bool(reasons), reasons


# Rocno preverjeni razponi cen primerljivih akumulatorskih orodij uveljavljenih
# znamk (Bosch, Einhell, Black+Decker) na slovenskih primerjalnikih cen
# (ceneje.si, preverjeno 2026-09). Ni popolna/samodejna primerjava vsakega
# modela - gre za tipicno ceno PRIMERLJIVEGA orodja v isti kategoriji, da
# damo realen obcutek, koliko bi isto orodje stalo pri drugi znamki.
# "key" doloca, kateri prevedeni naziv/opombo frontend prikaze (I18N.competitorCategories).
COMPETITOR_REFERENCE = [
    {
        "key": "angle_grinder",
        "keywords": ["kotni brusilnik", "kutna brusilic", "winkelschleifer"],
        "low": 58, "high": 100,
    },
    {
        "key": "hedge_trimmer",
        "keywords": ["škarje za živo mejo", "škare za živic", "heckenschere"],
        "low": 120, "high": 220,
    },
    {
        "key": "chainsaw",
        "keywords": ["verižna žaga", "lančana pila", "kettensäge", "kettensaege"],
        "low": 131, "high": 164,
    },
    {
        "key": "leaf_blower",
        "keywords": [
            "pihalnik za listje", "puhalnik za listje",
            "puhač lišć", "puhac lisc", "puhalo za lišć", "puhalo za lisc",
            "laubbläser", "laubblaeser", "turbinenlaubbläser",
        ],
        "low": 64, "high": 137,
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


# Priblizni menjalni tecaji (koliko EUR je 1 enota valute), rocno preverjeni
# sept. 2026 - NISO live tecaji, le dovolj natancni za smiselno primerjavo
# cen med drzavami z razlicno valuto. Brez tega bi npr. "38 PLN" in "38 EUR"
# obravnavali kot enako vredna, kar je narobe za priblizno 4x.
EUR_PER_UNIT = {
    "EUR": 1.0,
    "PLN": 0.235,
    "GBP": 1.19,
    "CZK": 0.040,
    "HUF": 0.00253,
    "RON": 0.201,
    "RSD": 0.00855,
    "SEK": 0.0893,
    "CHF": 1.064,
}


def to_eur(price, currency):
    if price is None:
        return None
    rate = EUR_PER_UNIT.get((currency or "EUR").upper())
    if rate is None:
        return None
    return round(price * rate, 2)


def match_competitor_reference(title: str, price_eur):
    """Primerja s konkurenco - COMPETITOR_REFERENCE spodnje/zgornje meje so v
    EUR, zato mora biti tudi vhodna cena ze pretvorjena v EUR (price_eur),
    ne surova cena v lokalni valuti."""
    if not title or price_eur is None or not is_battery_powered_title(title):
        return None
    text = title.lower()
    for ref in COMPETITOR_REFERENCE:
        if any(kw in text for kw in ref["keywords"]):
            if price_eur < ref["low"]:
                return {
                    "categoryKey": ref["key"],
                    "competitorLow": ref["low"],
                    "competitorHigh": ref["high"],
                    "savingsMin": round(ref["low"] - price_eur, 2),
                    "savingsMax": round(ref["high"] - price_eur, 2),
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
    currency = (price_info or {}).get("currencyCode")
    if price is None and currency and url:
        price = fetch_detail_price(url)
    price_eur = to_eur(price, currency)
    competitor = match_competitor_reference(title, price_eur)

    worth_it, worth_it_reasons = worth_it_assessment(perf, warranty_years, x20v)
    if competitor:
        worth_it = True
        worth_it_reasons.append({
            "type": "competitor",
            "categoryKey": competitor["categoryKey"],
            "competitorLow": competitor["competitorLow"],
            "competitorHigh": competitor["competitorHigh"],
        })

    return {
        "id": pid,
        "key": ean or f"id:{pid}",
        "ean": ean,
        "title": title,
        "shortTitle": keyfacts.get("title"),
        "image": image,
        "brand": brand,
        "price": price,
        "priceEur": price_eur,
        "currency": currency,
        "online": gb_data.get("online"),
        "inStoreNow": gb_data.get("store"),
        "onlineAvailable": stock.get("onlineAvailable"),
        "availabilityBadge": badge_text,
        "category": keyfacts.get("wonCategoryPrimary"),
        "url": url,
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
        if p["id"] is not None and is_parkside_brand(p["brand"]):
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


def today_str() -> str:
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d")


def load_daily_baseline():
    if DAILY_BASELINE_FILE.exists():
        try:
            return json.loads(DAILY_BASELINE_FILE.read_text(encoding="utf-8"))
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
                "priceEur": p["priceEur"],
                "currency": p["currency"],
                "url": p["url"],
                "availableFrom": p["availableFrom"],
                "availableUntil": p["availableUntil"],
                "availabilityBadge": p["availabilityBadge"],
            })

    return catalog


# "inStoreNow" namenoma NI v tem seznamu - v vmesniku se nikjer ne prikaze,
# zato bi njegov preklop (razmeroma pogost/nihajoc signal iz Lidlovega API-ja)
# sprozil znacko "SPREMEMBA" brez ustrezne razlage v changeNote() - uporabnik
# bi videl oznako spremembe, kjer se na kartici dejansko ni nic vidno spremenilo.
TRACKED_FIELDS = ("price", "online", "availableFrom", "availableUntil", "worthIt")


def diff_against_baseline(country_code: str, products: list, baseline_countries: dict):
    """Primerja s podanim DNEVNIM izhodiscem (glej komentar ob TRACKED_FIELDS
    in main()) - baseline_countries je slovar {drzava: {"products": [...]}} in
    NI nujno zadnji urni zagon, temvec stanje ob prvem zagonu danasnjega dne."""
    old_products = {}
    if baseline_countries:
        for p in baseline_countries.get(country_code, {}).get("products", []):
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
    today = today_str()
    daily_baseline = load_daily_baseline()
    if daily_baseline and daily_baseline.get("date") == today:
        # Se isti (ljubljanski) dan kot shranjeno izhodisce - primerjaj z
        # JUTRANJIM stanjem, ne z zadnjim urnim zagonom, da znacka
        # "SPREMEMBA" ostane vidna ves preostanek dneva.
        baseline_countries = daily_baseline.get("countries", {})
        is_new_day = False
    else:
        # Prvi zagon danasnjega dne (ali izhodisce se ne obstaja) - primerjaj
        # se vedno z zadnjim znanim stanjem, nato TO isto stanje ob koncu
        # zapisemo kot danasnje izhodisce za preostanek dneva.
        baseline_countries = (previous or {}).get("countries", {})
        is_new_day = True

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "countries": {},
    }

    had_error = False
    for code, cfg in COUNTRIES.items():
        print(f"Pobiram {cfg['label']} ({cfg['assortment']}, {cfg['locale']}) ...")
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

        products = diff_against_baseline(code, products, baseline_countries)
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
    if is_new_day:
        DAILY_BASELINE_FILE.write_text(
            json.dumps({"date": today, "countries": baseline_countries}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Novo dnevno izhodisce za spremembe: {today}")
    print(f"\nShranjeno v {PRODUCTS_FILE}, {CATALOG_FILE} in {DATA_JS_FILE}")
    print(f"Katalog Parkside Performance orodij skupaj: {len(catalog)}")
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
