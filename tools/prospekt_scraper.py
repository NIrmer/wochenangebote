"""
Prospekt-Angebote für Noahs 3 Märkte in Braunschweig auslesen und nach Watchlist filtern.

  LIDL  Celler Straße 81        -> kaufDA Filialseite -> strukturierte JSON-Angebote
  REWE  Wendenring 2            -> kaufDA Filialseite -> strukturierte JSON-Angebote ("Dein Markt")
  EDEKA Center Görge, Hamburger Str. 280
                                -> goerge-markt.de -> Yumpu-Prospekt (nur Bilder)
                                -> Seitenbilder (--edeka-pages) -> von Claude ausgelesen -> edeka.json (--edeka-json)

Ist ein Angebot wirklich reduziert? LIDL/REWE drucken den Originalpreis oft nicht ab. Deshalb:
  --crops DIR     lädt die Prospekt-Ausschnitte der Treffer ohne Normalpreis -> DIR/liste.json
  --aktion FILE   Einstufung je Ausschnitt (von Claude): rabatt / aktion / kein
                  "kein" = keine Hervorhebung im Prospekt -> wird ausgeblendet

Ausgaben: --notion-md (Notion-Seite) und --site-json (Website wochenangebote-bs.de)

pip install requests
Alle Quellen sind inoffiziell und können sich ändern.
"""
import os, re, json, requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128", "Accept-Language": "de-DE"}
LAT, LNG = 52.2833, 10.5150

# label: (kaufDA-Filialseite, kaufDA-Publisher-ID, kaufDA-Händlerseite Braunschweig als Fallback)
STORES = {
    "LIDL":  ("https://www.kaufda.de/Filialen/Braunschweig/Lidl-Celler-Strasse/v-f33837", "1013",
              "https://www.kaufda.de/Filialen/Braunschweig/Lidl/v-r74"),
    "REWE":  ("https://www.kaufda.de/Filialen/Braunschweig/REWE-Braunschweig-Wendenring-1-Wendenring-REWE/v-f471086941", "1062",
              "https://www.kaufda.de/Filialen/Braunschweig/REWE/v-r101"),
}
QUELLEN = {}
CACHE_FILE = "prospekt_cache.json"  # merkt sich den filialgenauen Prospekt, falls kaufDA ihn mal nicht anzeigt
GOERGE_ANGEBOTE = "https://goerge-markt.de/angebote"

# ======================= WATCHLIST =======================
# any     : mind. ein Muster muss passen (Name + Marke + Beschreibung + Kategorie)
# all     : zusätzlich muss eins dieser Muster passen
# exclude : Treffer verwerfen
# want    : gewünschte Variante (z. B. Zero). Fehlt sie, aber "versch. Sorten" steht da -> "Sorten prüfen"
# store   : nur in diesem Markt
# prio    : 1 = Kernprodukt, 2 = nice to have
WATCHLIST = [
    {"name": "Vegane Alternativen", "prio": 1,
     "any": [r"rügenwalder", r"vegan", r"veggie", r"vegetarisch", r"pflanzlich"],
     "all": [r"rügenwalder", r"wurst", r"aufschnitt", r"hack", r"schnitzel", r"nugget", r"frikadell", r"burger",
             r"salami", r"mühlen", r"filet", r"geschnetzelt", r"bratwurst", r"cordon", r"schinken"]},
    {"name": "Rinderhack (fettreduziert)", "prio": 1,
     "any": [r"rinderhack", r"rinder-hack", r"hackfleisch vom rind", r"rinder.?hackfleisch", r"tatar"],
     "want": r"fettreduziert|mager|light|\b[1-9]\s?% fett|max\.? ?\d+ ?% fett",
     "exclude": [r"gemischt", r"halb und halb", r"schwein"]},
    {"name": "Hähnchen", "prio": 2,
     "any": [r"hähnchen", r"hühnchen", r"chicken", r"geflügel"],
     "all": [r"brust", r"filet", r"schnitzel", r"steak", r"geschnetzelt", r"hack", r"keule", r"innenfilet", r"minutenschnitzel"],
     "exclude": [r"nudel", r"noodle", r"terrine", r"aspik", r"sülze", r"nugget", r"kebab", r"wurst", r"gebacken", r"paniert", r"finesse", r"\bente", r"gans"]},
    {"name": "Softdrinks Zero", "prio": 1,  # nur Markengetränke, keine Eigenmarken
     "any": [r"coca.?cola", r"\bcoke\b", r"fanta", r"sprite", r"mezzo.?mix", r"pepsi", r"7.?up", r"seven.?up",
             r"schwip.?schwap", r"mirinda", r"dr\.? ?pepper", r"schweppes", r"mountain dew", r"red bull",
             r"monster", r"rockstar", r"fuze", r"lipton ice", r"\blift\b"],
     "want": r"zero|light|ohne zucker|zuckerfrei|max\b|sugar ?free",
     "exclude": [r"\bja!", r"\briver\b", r"freeway", r"k-?classic", r"gut ?& ?günstig", r"herzstücke", r"beste wahl",
                 r"booster", r"solevita", r"\bbillig", r"bier", r"radler", r"likör", r"wein", r"kaffee", r"muffin"]},
    {"name": "Zero Sirup", "prio": 1,
     "any": [r"sirup"], "exclude": [r"goldsaft", r"zuckerrüben", r"rübenkraut", r"ahorn", r"agave", r"dattel", r"husten"],
     "want": r"zero|ohne zucker|zuckerfrei|light|kalorienarm"},
    {"name": "Skyr", "prio": 1, "any": [r"skyr"]},
    {"name": "Nimm's leicht", "prio": 1, "any": [r"nimm'?s ?leicht"]},
    {"name": "Herta Finesse Aufschnitt", "prio": 1, "any": [r"finesse"], "exclude": [r"rasier", r"haar", r"shampoo"]},
    {"name": "Harry Anno 1688 Dinkel Saaten", "prio": 1, "any": [r"anno ?1688", r"\banno\b"], "all": [r"dinkel", r"harry", r"brot"]},
    {"name": "Hummus", "prio": 1, "any": [r"hummus", r"houmous"]},
    {"name": "Kartoffeln", "prio": 2, "any": [r"\bkartoffeln\b", r"speisekartoffel", r"drillinge", r"\bfrühkartoffel"],
     "exclude": [r"chips", r"puffer", r"salat", r"püree", r"kroketten", r"gnocchi", r"pommes", r"rösti", r"knödel",
                 r"wedges", r"fresh cut", r"gratin", r"suppe", r"sticks", r"glas", r"dose"]},
    {"name": "Eier", "prio": 1, "any": [r"\beier\b", r"freilandeier", r"bodenhaltung", r"\bfreiland\b.*eier"],
     "exclude": [r"spätzle", r"nudel", r"likör", r"überraschung", r"schoko", r"oster", r"teigwaren", r"salat", r"ravioli"]},
    {"name": "TK Gemüsemischung", "prio": 1,
     "any": [r"gemüse", r"pfannengemüse", r"buttergemüse", r"brokkoli", r"erbsen", r"bohnen", r"rosenkohl", r"blumenkohl"],
     "all": [r"tiefkühl", r"tiefgefroren", r"\btk\b", r"iglo", r"frosta", r"pfanne", r"mischung"],
     "exclude": [r"pizza", r"nudel", r"lasagne", r"suppe", r"puffer", r"kartoffel", r"chips", r"fisch", r"konserve", r"glas", r"dose"]},
    {"name": "Frosta Fertiggerichte", "prio": 1, "any": [r"frosta"]},
    {"name": "Iglo Schlemmerfilet", "prio": 1, "any": [r"schlemmer.?filet", r"schlemmer.?lachs"]},
    {"name": "Iglo Spinat mit Blubb", "prio": 1, "any": [r"blubb", r"rahm.?spinat", r"iglo.*spinat", r"spinat.*iglo"]},
    {"name": "Lidl Hähnchennuggets", "prio": 1, "store": "LIDL",
     "any": [r"nugget"], "all": [r"hähnchen", r"chicken", r"geflügel"]},
    {"name": "Gustavo Gusto", "prio": 1, "any": [r"gustavo"]},
    {"name": "Proteinpulver", "prio": 1, "any": [r"protein.?pulver", r"eiweiß.?pulver", r"whey", r"protein.?shake"]},
    {"name": "Philadelphia", "prio": 1, "any": [r"philadelphia"]},
    {"name": "Körniger Frischkäse", "prio": 1, "any": [r"körnig", r"hüttenkäse", r"cottage"], "exclude": [r"brot\b", r"brötchen"]},
    {"name": "Haferflocken", "prio": 1, "any": [r"haferflocken", r"\bhafer\b.*flocken", r"porridge", r"oats"],
     "exclude": [r"riegel", r"keks", r"cookie", r"drink", r"milch", r"krusti", r"brötchen", r"brot\b"]},
    {"name": "Gewürze", "prio": 2,
     "any": [r"gewürzmischung", r"gewürzmühle", r"\bgewürze\b", r"gewürzsalz", r"ostmann", r"fuchs gewürz",
             r"kotan[yý]i", r"just spices", r"würzmischung"],
     "exclude": [r"gurke", r"ketchup", r"chips", r"spekulatius", r"traminer", r"regal", r"marinade", r"gyros", r"ferdi"]},
    {"name": "Marken-Tee", "prio": 2, "any": [r"\btee\b", r"teekanne", r"meßmer", r"messmer", r"yogi", r"pukka", r"twinings",
                                              r"onno behrends", r"westminster", r"milford", r"goldmännchen", r"bünting", r"lipton"],
     "all": [r"teekanne", r"meßmer", r"messmer", r"yogi", r"pukka", r"twinings", r"onno", r"westminster", r"milford",
             r"goldmännchen", r"bünting", r"lipton", r"ostfriesen", r"tee"],
     "exclude": [r"eistee", r"ice tea", r"tee-?licht", r"teelicht", r"volvic", r"tee-extrakt"]},
    {"name": "Proteinpudding / High Protein", "prio": 1,
     "any": [r"protein", r"eiweiß"], "exclude": [r"pulver", r"whey", r"tierfutter", r"katze", r"hund", r"brot", r"brötchen"]},
]
EMOJI = {"Vegane Alternativen": "🌱", "Rinderhack (fettreduziert)": "🐄", "Hähnchen": "🍗", "Softdrinks Zero": "🥤",
         "Zero Sirup": "🧃", "Skyr": "🥛", "Nimm's leicht": "🧈", "Herta Finesse Aufschnitt": "🥪",
         "Harry Anno 1688 Dinkel Saaten": "🍞", "Hummus": "🫘", "Kartoffeln": "🥔", "Eier": "🥚",
         "TK Gemüsemischung": "🥦", "Frosta Fertiggerichte": "🍲", "Iglo Schlemmerfilet": "🐟",
         "Iglo Spinat mit Blubb": "🥬", "Lidl Hähnchennuggets": "🐔", "Gustavo Gusto": "🍕", "Proteinpulver": "💪",
         "Philadelphia": "🧀", "Körniger Frischkäse": "🥣", "Haferflocken": "🌾", "Gewürze": "🧂",
         "Marken-Tee": "🍵", "Proteinpudding / High Protein": "🍮"}
MARKT_TITEL = {"LIDL": "LIDL – Celler Straße 81", "REWE": "REWE – Wendenring 2", "EDEKA": "EDEKA Center Görge – Hamburger Str. 280"}
VARIANT_RX = re.compile(r"versch\.?\s*sorten|verschiedene\s+sorten|versch\.\s|sortiert|sorten|\boder\b|weitere|auswahl", re.I)

# ======================= kaufDA (Lidl, REWE) =======================
def _next_data(url):
    html = requests.get(url, headers=UA, timeout=20).text
    return json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1))["props"]["pageProps"]["pageInformation"]

# Normalpreis = durchgestrichener Preis im Prospekt (REGULAR) bzw. UVP (RECOMMENDED_RETAIL_PRICE)
NORMAL_TYPES = ("REGULAR_PRICE", "RECOMMENDED_RETAIL_PRICE")

def _normalpreis(deals):
    for t in NORMAL_TYPES:
        werte = [d.get("max") or d.get("min") for d in deals if d.get("type") == t and (d.get("max") or d.get("min"))]
        if werte:
            return max(werte)
    return None

def _base_price(txt):
    m = re.search(r"1\s*(kg|l)\s*=\s*(\d+[.,]\d+|\d+)", txt or "", re.I)
    return (float(m.group(2).replace(",", ".")), m.group(1).lower()) if m else (None, None)

def _pick_brochures(label, url, pid, city_url):
    """Filialprospekt = 'viewer'-Slot der Filialseite. Der Slot wird manchmal mit Werbung belegt ->
    dann Cache (diese Woche schon gesehen) oder alle Prospekte des Händlers in der Nähe (regional)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pi = _next_data(url)
    pid_of = lambda b: str(b["publisher"].get("id", "")).replace("DE-", "")
    allb = {b["contentId"]: b for page in (pi, _next_data(city_url)) for v in page["brochures"].values()
            if isinstance(v, list) for b in v if pid_of(b) == pid and b["validUntil"][:10] >= now}
    try:
        cache = json.load(open(CACHE_FILE))
    except Exception:
        cache = {}
    store = [b for b in pi["brochures"].get("viewer", []) if pid_of(b) == pid]
    if store:
        cache[label] = store
        json.dump(cache, open(CACHE_FILE, "w"))
        return store, "filiale"
    cached = [b for b in cache.get(label, []) if b["validUntil"][:10] >= now]
    if cached:
        return cached, "filiale (cache)"
    return list(allb.values()), "regional (alle Prospekte in der Nähe)"

def kaufda_store(label, url, pid, city_url):
    brochures, quelle = _pick_brochures(label, url, pid, city_url)
    print(f"{label}: {len(brochures)} Prospekt(e), Quelle: {quelle}")
    QUELLEN[label] = quelle
    out = []
    for b in brochures:
        d = requests.get(f"https://content-viewer-be.kaufda.de/v1/brochures/{b['contentId']}/pages",
                         params={"partner": "kaufda_web", "lat": LAT, "lng": LNG}, headers=UA, timeout=30).json()
        for page in d.get("contents", []):
            for off in page.get("offers", []):
                c = off.get("content", {})
                prods = c.get("products", [])
                if not prods:
                    continue
                deals = c.get("deals", [])
                aktion = [d for d in deals if d.get("type") not in NORMAL_TYPES] or deals
                deal = min(aktion, key=lambda x: x.get("min") or 1e9) if aktion else {}
                gp, unit = _base_price(deal.get("priceByBaseUnit"))
                normal = _normalpreis(deals)
                names = list(dict.fromkeys(p.get("name") or "" for p in prods))
                brands = list(dict.fromkeys(p.get("brandName") for p in prods if p.get("brandName")))
                desc = " ".join(dict.fromkeys(x.get("paragraph", "") for p in prods for x in p.get("description", [])))
                cats = " > ".join(dict.fromkeys(cp["name"] for p in prods for cp in p.get("categoryPaths", [])))
                out.append({
                    "id": c.get("id"),
                    "markt": label, "produkt": " / ".join(names), "marke": ", ".join(brands) or None,
                    "preis": deal.get("min"), "preisart": deal.get("type"),
                    "normalpreis": normal,
                    "grundpreis": gp, "einheit": unit, "info": desc, "kategorie": cats,
                    "von": b["validFrom"][:10], "bis": b["validUntil"][:10],
                    "seite": (page.get("number") or 0) + 1, "bild": c.get("image"),
                    "produktbild": next((im["url"] for p in prods for im in (p.get("images") or []) if im.get("url")), None),
                })
    return out

# ======================= EDEKA Center Görge (Yumpu + Vision) =======================
def goerge_pages(title_prefix="ECenter"):
    html = requests.get(GOERGE_ANGEBOTE, headers=UA, timeout=20).text
    for key in re.findall(r'yumpu\.com/\w+/embed/view/(\w+)', html):
        emb = requests.get(f"https://www.yumpu.com/xx/embed/view/{key}", headers=UA, timeout=20).text
        title = re.search(r"<title>(.*?)</title>", emb, re.S).group(1)
        if not title.startswith(title_prefix):
            continue
        doc_id = re.search(r"document/view/(\d+)", emb).group(1)
        doc = requests.get(f"https://www.yumpu.com/de/document/json2/{doc_id}", headers=UA, timeout=20).json()["document"]
        urls = [doc["base_path"] + p["images"]["large"] + "?" + p["qss"]["large"] for p in doc["pages"]]
        return title, doc["validity"], urls
    raise RuntimeError("E-Center-Prospekt nicht gefunden")

# ======================= Matching =======================
def _rx(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)

def match(o):
    text = " | ".join(str(o.get(k) or "") for k in ("produkt", "marke", "info", "kategorie"))
    hits = []
    for w in WATCHLIST:
        if w.get("store") and w["store"] != o["markt"]:
            continue
        if not _rx(w["any"], text) or (w.get("all") and not _rx(w["all"], text)) or _rx(w.get("exclude", []), text):
            continue
        status = "✓"
        if w.get("want") and not re.search(w["want"], text, re.I):
            if VARIANT_RX.search(text):
                status = "Sorten prüfen"
            else:
                continue
        elif VARIANT_RX.search(o.get("info") or ""):
            status = "✓ (mehrere Sorten)"
        hits.append((w, status))
    return hits

def selection(alle):
    res, seen = [], set()
    for o in alle:
        key = (o["markt"], tuple(sorted((o["produkt"] or "").split(" / "))), o["preis"])
        if key in seen:
            continue
        seen.add(key)
        for w, status in match(o):
            res.append({**o, "kategorie_watch": w["name"], "prio": w["prio"], "status": status})
            break  # erste passende Regel reicht
    order = {w["name"]: i for i, w in enumerate(WATCHLIST)}
    return sorted(res, key=lambda r: (r["prio"], order[r["kategorie_watch"]], r["grundpreis"] or 999))

# ======================= Reduziert? =======================
# hervorhebung: "rabatt" (Normalpreis/Prozent bekannt) | "aktion" (als Aktion beworben, Höhe unbekannt)
#               | "kein" (keine Hervorhebung -> ausblenden) | None (nicht geprüft -> wird angezeigt)
def _ist_reduziert(r):
    n, p = r.get("normalpreis"), r.get("preis")
    return isinstance(n, (int, float)) and isinstance(p, (int, float)) and n > p > 0

def apply_hervorhebung(sel, aktion):
    for r in sel:
        a = aktion.get(r.get("id") or "", {})
        if a.get("normal") and not r.get("normalpreis"):
            r["normalpreis"] = a["normal"]
        if a.get("prozent"):
            r["prozent"] = int(a["prozent"])
        if _ist_reduziert(r) or r.get("prozent"):
            r["hervorhebung"] = "rabatt"
        else:
            r["hervorhebung"] = a.get("status") or r.get("hervorhebung")
    return sel

def _prozent(r):
    if r.get("prozent"):
        return r["prozent"]
    if _ist_reduziert(r):
        return round((1 - r["preis"] / r["normalpreis"]) * 100)
    return None

def write_crops(sel, folder):
    """Prospekt-Ausschnitte der LIDL/REWE-Treffer ohne Normalpreis laden (zum Ansehen durch Claude)."""
    os.makedirs(folder, exist_ok=True)
    liste = []
    for r in sel:
        if r["markt"] == "EDEKA" or _ist_reduziert(r) or not r.get("bild"):
            continue
        datei = f"{folder}/{r['id']}.jpg"
        open(datei, "wb").write(requests.get(r["bild"], headers=UA, timeout=30).content)
        liste.append({"id": r["id"], "markt": r["markt"], "produkt": r["produkt"], "preis": r["preis"], "datei": datei})
    json.dump(liste, open(f"{folder}/liste.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(liste)} Ausschnitte nach {folder}/ geladen -> {folder}/liste.json")

def write_bilder(sel, folder, prefix):
    """Thumbnails für die Website: Produktfoto (freigestellt, kaufDA) + Prospekt-Ausschnitt.
    EDEKA: Ausschnitte aus der Prospektseite per bbox (ganze Angebotskachel) und bbox_foto (nur Produktfoto),
    je [x0, y0, x1, y1] als Anteile 0–1. Ordner wird jede Woche geleert."""
    import io, shutil
    from PIL import Image
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)

    def save(im, name, maxsize):
        im.thumbnail((maxsize, maxsize))
        im.save(f"{folder}/{name}", "WEBP", quality=80)
        return f"{prefix}/{name}"

    def load(url):
        return Image.open(io.BytesIO(requests.get(url, headers=UA, timeout=30).content))

    n = 0
    for i, r in enumerate(sel):
        if r.get("hervorhebung") == "kein":
            continue
        key = re.sub(r"[^a-z0-9-]", "", str(r.get("id") or i).lower())[:24].rstrip("-")
        try:
            if r["markt"] == "EDEKA":
                bb, seite = r.get("bbox"), r.get("seite")
                pfad = f"edeka_pages/seite_{int(seite):02d}.jpg" if seite else ""
                if bb and os.path.exists(pfad):
                    pg = Image.open(pfad).convert("RGB")
                    w, h = pg.size

                    def cut(b, pad=0.01):
                        x0, y0, x1, y1 = b
                        return pg.crop((int(max(0, (x0 - pad) * w)), int(max(0, (y0 - pad) * h)),
                                        int(min(w, (x1 + pad) * w)), int(min(h, (y1 + pad) * h))))
                    r["img_prospekt"] = save(cut(bb), f"{key}-p.webp", 640)
                    r["img"] = save(cut(r.get("bbox_foto") or bb, 0.005), f"{key}.webp", 320)
            else:
                if r.get("produktbild"):
                    im = load(r["produktbild"])
                    r["img"] = save(im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB"), f"{key}.webp", 320)
                if r.get("bild"):
                    crop = load(r["bild"]).convert("RGB")
                    r["img_prospekt"] = save(crop, f"{key}-p.webp", 640)
                    if not r.get("img"):
                        r["img"] = save(crop.copy(), f"{key}.webp", 320)
            n += bool(r.get("img"))
        except Exception as e:
            print(f"Bild fehlgeschlagen: {r['markt']} {r['produkt']}: {e}")
    print(f"{n} Bilder nach {folder}/")

def print_selection(sel):
    cur = None
    for r in sel:
        if r["kategorie_watch"] != cur:
            cur = r["kategorie_watch"]
            print(f"\n## {cur}")
        gp = f"  [{r['grundpreis']:.2f} €/{r['einheit']}]" if r["grundpreis"] else ""
        app = " (App)" if r["preisart"] == "APP-PREIS" else ""
        flag = "" if r["status"] == "✓" else f"  ⚠ {r['status']}" if "prüfen" in r["status"] else f"  · {r['status'][2:]}"
        hv = f"  [{r.get('hervorhebung')}]" if r.get("hervorhebung") else ""
        info = (r["info"] or "")[:70]
        print(f"  {r['markt']:5} {r['preis']!s:>6} €{app}  {r['produkt']} ({r['marke'] or '-'}){gp}{flag}{hv}\n        {info}")

def download_edeka_pages(folder="edeka_pages"):
    """Lädt die Seitenbilder des Görge-E-Center-Prospekts (für Auslesen ohne API-Key, z. B. durch Claude selbst)."""
    os.makedirs(folder, exist_ok=True)
    title, validity, urls = goerge_pages()
    for i, u in enumerate(urls, 1):
        open(f"{folder}/seite_{i:02d}.jpg", "wb").write(requests.get(u, timeout=30).content)
    json.dump({"title": title, "validity": validity, "pages": len(urls)}, open(f"{folder}/meta.json", "w"))
    print(f"{len(urls)} Seiten nach {folder}/ geladen ({title}, {validity['from'][:10]} bis {validity['until'][:10]})")

def _esc(t):
    return re.sub(r"([\\*~`$\[\]<>{}|^])", r"\\\1", str(t or "")).replace("\n", " ")

# Fleisch: Marke egal -> nur als Info. Sonst: "Marke Produkt" (z. B. "Milbona Skyr", "Gustavo Gusto Steinofenpizza")
FLEISCH = {"Rinderhack (fettreduziert)", "Hähnchen", "Lidl Hähnchennuggets"}

def _brand(b):
    parts = [p.strip() for p in re.split(r",| / ", b or "") if p.strip()]
    return [p.title() if p.isupper() and len(p) > 3 else p for p in parts]

def _produkt_info(r):
    name, brands, info = (r["produkt"] or "").strip(), _brand(r["marke"]), (r["info"] or "").strip()
    if r["kategorie_watch"] in FLEISCH:
        if brands:
            info = f"Marke: {' / '.join(brands)} · {info}" if info else f"Marke: {' / '.join(brands)}"
        return name, info
    neu = [b for b in brands if b.lower() not in name.lower()]
    return (" / ".join(neu) + " " + name if neu else name), info

def _kw(sel, stand):
    from datetime import date
    bis = sorted(r["bis"] for r in sel if r.get("bis"))
    return date.fromisoformat(bis[0]).isocalendar()[1] if bis else date.fromisoformat(stand).isocalendar()[1] + 1

def _label(r):
    prod = _produkt_info(r)[0]
    return prod if prod.upper().startswith(r["markt"]) else f"{r['markt']} {prod}"

def _sichtbar(sel):
    return [r for r in sel if r.get("hervorhebung") != "kein"], [r for r in sel if r.get("hervorhebung") == "kein"]

def to_notion_md(sel, quellen, stand, hinweise=""):
    kw = _kw(sel, stand)
    sel, aus = _sichtbar(sel)
    counts = " · ".join(f"{m}: {sum(r['markt'] == m for r in sel)}" for m in MARKT_TITEL)
    used = list(dict.fromkeys(r["kategorie_watch"] for r in sel))
    legende = " ".join(f"{EMOJI.get(k, '•')} {_esc(k)}" for k in used)
    md = ['<callout icon="🛒" color="gray_bg">',
          f'\t**KW {kw}** · Stand {stand} · {len(sel)} Treffer ({counts})',
          '\tQuellen: ' + " · ".join(f"{k}: {_esc(v)}" for k, v in quellen.items()),
          '\tNormal = durchgestrichener Preis bzw. UVP aus dem Prospekt · „Aktion“ = im Prospekt als Aktion beworben, Originalpreis nicht angegeben',
          f'\tLegende: {legende}']
    if aus:
        md.append('\tAusgeblendet (im Prospekt nicht als Angebot hervorgehoben): '
                  + " · ".join(_esc(f"{_label(r)} {r['preis']:.2f} €") for r in aus))
    if hinweise:
        md.append(f'\tHinweise: {_esc(hinweise)}')
    md.append('</callout>')
    for markt, titel in MARKT_TITEL.items():
        rows = [r for r in sel if r["markt"] == markt]
        md.append(f"## {titel}")
        if not rows:
            md.append("Keine Treffer.")
            continue
        md += ['<table header-row="true" fit-page-width="true">',
               "\t<tr>\n\t\t<td></td>\n\t\t<td>Produkt</td>\n\t\t<td>Info</td>\n\t\t<td>Preis</td>\n\t\t<td>Normal</td>\n\t\t<td>Grundpreis</td>\n\t</tr>"]
        for r in rows:
            gp = f"{r['grundpreis']:.2f} €/{r['einheit']}" if r["grundpreis"] else ""
            preis = (f"{r['preis']:.2f} €" if isinstance(r["preis"], (int, float)) and r["preis"] else "–") + (" (App)" if r["preisart"] == "APP-PREIS" else "")
            prod, info = _produkt_info(r)
            n, pz = r.get("normalpreis"), _prozent(r)
            normal = f"{n:.2f} €" if isinstance(n, (int, float)) and n else ""
            if pz:
                normal = f"{normal} (−{pz:d} %)" if normal else f"−{pz:d} %"
            elif not normal and r.get("hervorhebung") == "aktion":
                normal = "Aktion"
            md.append("\t<tr>\n" + "".join(f"\t\t<td>{c}</td>\n" for c in
                      [EMOJI.get(r["kategorie_watch"], "•"), _esc(prod), _esc(info[:90]), preis, normal, gp]) + "\t</tr>")
        md.append("</table>")
    return "\n".join(md)

def to_site_json(sel, quellen, stand, hinweise=""):
    """Daten für die Website (index.html). Ausgeblendete ('kein') Treffer fehlen."""
    from datetime import date
    kw = _kw(sel, stand)
    sel, aus = _sichtbar(sel)
    jahr = date.fromisoformat(stand).year + (1 if date.fromisoformat(stand).isocalendar()[1] > kw + 10 else 0)
    used = list(dict.fromkeys(r["kategorie_watch"] for r in sel))
    maerkte = []
    for markt, titel in MARKT_TITEL.items():
        name, _, adresse = titel.partition(" – ")
        angebote = []
        for r in (r for r in sel if r["markt"] == markt):
            prod, info = _produkt_info(r)
            angebote.append({
                "id": r.get("id"), "emoji": EMOJI.get(r["kategorie_watch"], "•"), "kategorie": r["kategorie_watch"],
                "produkt": prod, "warn": "prüfen" in r["status"], "info": info[:140],
                "preis": r["preis"], "app": r["preisart"] == "APP-PREIS",
                "normal": r.get("normalpreis"), "ersparnis": _prozent(r),
                "aktion": r.get("hervorhebung") == "aktion",
                "grundpreis": f"{r['grundpreis']:.2f} €/{r['einheit']}" if r["grundpreis"] else None,
                "bild": r.get("img"), "prospekt": r.get("img_prospekt"), "seite": r.get("seite"),
            })
        maerkte.append({"id": markt.lower(), "name": name, "adresse": adresse, "angebote": angebote})
    return {"kw": kw, "stand": stand,
            "von": date.fromisocalendar(jahr, kw, 1).isoformat(), "bis": date.fromisocalendar(jahr, kw, 6).isoformat(),
            "quellen": " · ".join(f"{k}: {v}" for k, v in quellen.items()), "hinweise": hinweise,
            "legende": {EMOJI.get(k, "•"): k for k in used},
            "ausgeblendet": [_label(r) for r in aus],
            "maerkte": maerkte}

if __name__ == "__main__":
    import argparse
    from datetime import date
    ap = argparse.ArgumentParser()
    ap.add_argument("--edeka-pages", action="store_true", help="nur EDEKA-Seitenbilder laden und beenden")
    ap.add_argument("--edeka-json", help="bereits extrahierte EDEKA-Angebote einlesen")
    ap.add_argument("--crops", help="Prospekt-Ausschnitte der LIDL/REWE-Treffer ohne Normalpreis in diesen Ordner laden")
    ap.add_argument("--aktion", help="Einstufung der Ausschnitte (JSON: id -> {status, normal, prozent})")
    ap.add_argument("--hinweise", help="Textdatei mit Hinweisen für Callout/Website")
    ap.add_argument("--notion-md", help="Auswahl zusätzlich als Notion-Markdown in diese Datei schreiben")
    ap.add_argument("--site-json", help="Auswahl als Website-Daten (angebote.json) in diese Datei schreiben")
    ap.add_argument("--bilder", help="Produktbilder für die Website in diesen Ordner schreiben (z. B. <repo>/img)")
    a = ap.parse_args()
    if a.edeka_pages:
        download_edeka_pages(); raise SystemExit
    quellen, alle = QUELLEN, []
    for label, cfg in STORES.items():
        alle += kaufda_store(label, *cfg)
    if a.edeka_json:
        meta = json.load(open("edeka_pages/meta.json")) if os.path.exists("edeka_pages/meta.json") \
            else {"validity": {"from": "", "until": ""}}
        for i, it in enumerate(json.load(open(a.edeka_json))):
            alle.append({"id": f"edeka-{it.get('seite')}-{i}", "markt": "EDEKA", "produkt": it.get("produkt"), "marke": it.get("marke"),
                         "preis": it.get("app_preis") or it.get("preis"),
                         "preisart": "APP-PREIS" if it.get("app_preis") else "SALES_PRICE",
                         "normalpreis": it.get("uvp"), "prozent": it.get("prozent"),
                         "hervorhebung": it.get("hervorhebung"),
                         "grundpreis": it.get("grundpreis"), "einheit": it.get("einheit"),
                         "info": it.get("info") or "", "kategorie": it.get("kategorie") or "",
                         "von": meta["validity"]["from"][:10], "bis": meta["validity"]["until"][:10],
                         "seite": it.get("seite"), "bild": None, "bbox": it.get("bbox"), "bbox_foto": it.get("bbox_foto")})
        quellen["EDEKA"] = "Görge E-Center-Prospekt (aus Bildern ausgelesen)"
    else:
        quellen["EDEKA"] = "nicht ausgelesen"
    sel = selection(alle)
    aktion = json.load(open(a.aktion)) if a.aktion else {}
    apply_hervorhebung(sel, aktion)
    hinweise = open(a.hinweise, encoding="utf-8").read().strip() if a.hinweise and os.path.exists(a.hinweise) else ""
    print(f"{len(alle)} Angebote geladen, {len(sel)} interessant, davon {sum(r.get('hervorhebung') == 'kein' for r in sel)} ausgeblendet")
    print_selection(sel)
    json.dump(alle, open("alle_angebote.json", "w"), ensure_ascii=False, indent=1)
    json.dump(sel, open("auswahl.json", "w"), ensure_ascii=False, indent=1)
    if a.crops:
        write_crops(sel, a.crops)
    stand = date.today().isoformat()
    if a.notion_md:
        open(a.notion_md, "w").write(to_notion_md(sel, quellen, stand, hinweise))
        print(f"Notion-Markdown -> {a.notion_md}")
    if a.bilder:
        write_bilder(sel, a.bilder, os.path.basename(os.path.normpath(a.bilder)))
    if a.site_json:
        json.dump(to_site_json(sel, quellen, stand, hinweise), open(a.site_json, "w"), ensure_ascii=False, indent=1)
        print(f"Website-Daten -> {a.site_json}")
