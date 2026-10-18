"""
Bierpreise rund um Langlingen (29364) – Wochenangebote aller Supermärkte, Discounter und Großmärkte.

Ergebnis: bier-langlingen/bier.json (+ bier-langlingen/verlauf.json für den Preisverlauf)
Seite:    https://wochenangebote-bs.de/bier-langlingen/  (bewusst nirgends verlinkt, noindex)

Quellen
  kaufDA   Prospekte der Händler in der Nähe von Langlingen (strukturierte Angebote, wie im prospekt_scraper):
           ALDI Nord, Lidl, Netto, Penny, Kaufland, combi, METRO (Wochenprospekt, Preise brutto)
  EDEKA    edeka.de blockt Skripte aus der Cloud -> der Sonntagslauf liest die Marktseite
           https://www.edeka.de/maerkte/400899/angebote/ (EDEKA Müller, Langlingen) per WebFetch aus
           und übergibt die Bier-Angebote mit --edeka-json (Format siehe EDEKA_FORMAT unten).

Aufruf
  python3 tools/bier_scraper.py [--edeka-json edeka_bier.json] [--hinweise text] [--out bier-langlingen]

Filialen: kaufDA-Filialverzeichnis je Ort/Händler (ORTE, RADIUS_KM), Cache bier-langlingen/filialen.json,
          wird alle 4 Wochen neu geladen. Bilder: Produktfoto aus dem Prospekt -> bier-langlingen/img/.

Was ist "Bier"? kaufDA-Kategorie "Bier" (oder "Bier" im Produktnamen bei Lebensmitteln/Getränken).
Gebinde, Pfand und Preis pro Liter werden aus dem Kleintext berechnet (eigene Rechnung, damit alle
Märkte vergleichbar sind). Pfand ist NICHT im Literpreis enthalten.

pip install requests
Alle Quellen sind inoffiziell und können sich ändern.
"""
import argparse, json, os, re, sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128", "Accept-Language": "de-DE"}
LAT, LNG = 52.5558, 10.2862          # Langlingen (kaufDA)
BERLIN = ZoneInfo("Europe/Berlin")

# kaufDA-Seiten, deren Prospektlisten zusammen die Region abdecken (Langlingen selbst + Filialseiten in Celle,
# weil kaufDA ALDI Nord / combi nicht auf der Ortsseite von Langlingen listet)
KAUFDA_SEITEN = [
    "https://www.kaufda.de/Langlingen",
    "https://www.kaufda.de/Langlingen/Supermarkt/p-c11",
    "https://www.kaufda.de/Filialen/Langlingen/EDEKA-Mueller-Hauptstrasse-EDEKA/v-f328663512",
    "https://www.kaufda.de/Wathlingen",
    "https://www.kaufda.de/Filialen/Celle/ALDI-Nord-Laerchenweg/v-f913810896",
    "https://www.kaufda.de/Filialen/Celle/Trinkgut-Neuenhaeuser-Strasse/v-f1122504660",
    "https://www.kaufda.de/Filialen/Celle/REWE/v-r101",
]

# kaufDA-Publisher-ID (Prospekte) -> Markt. "laden" = kaufDA-Filialverzeichnis (Slug, Händler-ID) für die Filialsuche.
# Die Prospekte gelten regional, also in allen Filialen des Händlers im Umkreis.
MAERKTE = {
    "75":        {"name": "ALDI Nord", "farbe": "#00559f", "laden": ("ALDI-Nord", 43)},
    "1013":      {"name": "Lidl",      "farbe": "#0050aa", "laden": ("Lidl", 74)},
    "1034":      {"name": "Netto",     "farbe": "#e2001a", "laden": ("Netto-Marken-Discount", 9)},
    "1050":      {"name": "Penny",     "farbe": "#cd1719", "laden": ("Penny-Markt", 75)},
    "424316869": {"name": "Kaufland",  "farbe": "#e10915", "laden": ("Kaufland", 2801)},
    "42265682":  {"name": "combi",     "farbe": "#f39200", "laden": ("combi", 173)},
    "1040":      {"name": "Norma",     "farbe": "#c4161c", "laden": ("Norma", 78)},
    "1074":      {"name": "Trinkgut",  "farbe": "#7a1f2b", "laden": ("Trinkgut", 4)},
    "86285183":  {"name": "METRO",     "farbe": "#002d72", "laden": ("Metro", 287), "hinweis": "nur mit METRO-Kundenkarte"},
}
EDEKA_MARKT = {"name": "EDEKA", "farbe": "#f0b400"}
EDEKA_SEITE = "https://www.edeka.de/maerkte/400899/angebote/"
# EDEKA-Preise gelten nur in diesem einen Markt (Kaufmann-Preise)
EDEKA_FILIALE = {"name": "EDEKA Müller", "adresse": "Hauptstraße 30", "ort": "29364 Langlingen", "km": 0.3}

# Orte im Umkreis (kaufDA-Slug), deren Filialen angezeigt werden. Radius in km (Luftlinie Ortsmitte).
# kaufDA hat für manche Orte falsche Koordinaten (Mueden-Aller zeigt auf Müden/Örtze) -> hier überschreiben
ORT_KOORD = {"Mueden-Aller": (52.527, 10.367)}
ORTE = ["Langlingen", "Wienhausen", "Eicklingen", "Wathlingen", "Lachendorf", "Mueden-Aller",
        "Meinersen", "Hohne", "Beedenbostel", "Ahnsbeck", "Adelheidsdorf", "Celle", "Gifhorn", "Uetze",
        "Wesendorf", "Hambuehren", "Leiferde", "Hillerse"]
RADIUS_KM = 25
FILIALEN_MAX_ALTER = timedelta(days=28)       # Filialliste nur alle 4 Wochen neu laden

# Prospekte, die keine Wochenangebote sind (Online-Shop, Monatskataloge)
PROSPEKT_AUSSCHLUSS = re.compile(r"netto-online|monatsmen|rezepte", re.I)

EDEKA_FORMAT = """Liste von Objekten, je Bier-Angebot:
  {"marke": "Haake Beck", "produkt": "Haake Beck", "preis": 10.99, "app_preis": null,
   "info": "versch. Sorten, + 3,50 Pfand, 25x0,33l Flasche", "normal": null, "tiefst30": 15.49}
  info = Kleintext wörtlich (Gebinde + Pfand), tiefst30 = "Niedrigster Gesamtpreis der letzten 30 Tage"."""

BIER_RX = re.compile(r"\bbier|pils|pilsener|pilsner|weizen|weißbier|weissbier|radler|lager|\bhell\b|helles|urtyp|"
                     r"export|alster|bock\b|kellerbier|landbier|schwarzbier|altbier|kölsch|\bipa\b|porter|stout", re.I)
KEIN_BIER_RX = re.compile(r"wein\b|weißwein|rotwein|sekt|prosecco|brötchen|\bbrot\b|bratwurst|senf|essig|"
                          r"bierzelt|garnitur|krug|gläser|\bglas\b(?!.*fl)|kühlschrank|zapfanlage(?!.*fass)", re.I)


# ======================= Woche =======================
def zielwoche(heute=None):
    """Sonntags läuft der Auftrag für die KOMMENDE Woche, sonst gilt die laufende Woche (Mo–Sa)."""
    heute = heute or datetime.now(BERLIN).date()
    montag = heute + timedelta(days=1) if heute.weekday() == 6 else heute - timedelta(days=heute.weekday())
    return montag, montag + timedelta(days=5)


def _lokal(iso):
    iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso.replace("Z", "+00:00"))
    return datetime.fromisoformat(iso).astimezone(BERLIN).date()


# ======================= Text-Parsing =======================
def _zahl(s):
    return float(s.replace(",", "."))


def gebinde_parsen(text):
    """'20 x 0,5 / 24 x 0,33 Liter' -> [(20, 0.5), (24, 0.33)]; '0,5-L-Dose' -> [(1, 0.5)]; '4 x 355 ml' -> [(4, .355)]"""
    t = (text or "").replace("×", "x")
    res = []
    # "20 x 0,4 / 28 x 0,25 Liter": Einheit steht nur am Ende -> Liter, wenn < 2
    for anz, menge, einheit in re.findall(r"(\d{1,2})\s*x\s*(\d+(?:[.,]\d+)?)\s*-?\s*(ml|l\b|liter|l-|)", t, re.I):
        m = _zahl(menge)
        e = einheit.lower()
        if e == "ml" or (not e.startswith("l") and m >= 100):
            m = m / 1000
        if 0.1 <= m <= 2:
            res.append((int(anz), round(m, 3)))
    if not res:
        for menge, einheit in re.findall(r"(\d+(?:[.,]\d+)?)\s*-?\s*(ml|l\b|liter|l-)", t, re.I):
            m = _zahl(menge)
            if einheit.lower() == "ml":
                m = m / 1000
            if 0.2 <= m <= 50:
                res.append((1, round(m, 3)))
                break
    return list(dict.fromkeys(res))


def pfand_parsen(text):
    """'zzgl. Pfand 3.10 / 3.42', '+ 3.10 Pfand', 'Pfand = 0.25', '+ 3,50 Pfand' -> [3.1, 3.42]"""
    t = text or ""
    m = re.search(r"pfand\s*(?:=|:)?\s*(\d+[.,]\d{2})(?:\s*/\s*(\d+[.,]\d{2}))?", t, re.I)
    if m:
        return [_zahl(x) for x in m.groups() if x]
    werte = re.findall(r"(\d+[.,]\d{2})\s*(?:€\s*)?pfand", t, re.I)
    return [_zahl(x) for x in werte]


def typ_von(anzahl, liter_einzel, text):
    if re.search(r"adventskalender", text, re.I):
        return "Sonstiges"
    gesamt = anzahl * liter_einzel
    if anzahl == 1 and liter_einzel >= 2:
        return "Fass"
    if anzahl >= 12:
        return "Kasten"
    if anzahl >= 2:
        return "Pack"
    return "Einzeln"


def art_von(produkt, text):
    """Bier / Alkoholfrei / Radler & Mix / Malz. 'Pils oder Radler' zählt als Bier (Auswahl im Angebot)."""
    auswahl = re.search(r"(pils|bier|lager|hell|weizen|weißbier|urtyp|export)\w*.*(\boder\b|/|,)", produkt, re.I)
    if re.search(r"malz", produkt, re.I) and not re.search(r"pils|bier\b", produkt, re.I):
        return "Malz"
    if re.search(r"radler|alster|\bmix\b|desperados|curuba|tequila|cola.?bier|v\+|biermisch", text, re.I) and not auswahl:
        return "Radler & Mix"
    if re.search(r"alkoholfrei|0,0\s*%|\b0\.0\b", produkt, re.I) and not re.search(r"/|\boder\b|\bauch\b", produkt, re.I):
        return "Alkoholfrei"
    return "Bier"


# ======================= kaufDA =======================
def _next_data(url):
    html = requests.get(url, headers=UA, timeout=25).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1))["props"]["pageProps"]["pageInformation"]


def prospekte(montag, samstag):
    gefunden, fehler = {}, []
    for url in KAUFDA_SEITEN:
        try:
            pi = _next_data(url)
        except Exception as e:
            fehler.append(f"{url}: {e}")
            continue
        for liste in pi.get("brochures", {}).values():
            if not isinstance(liste, list):
                continue
            for b in liste:
                pid = str(b.get("publisher", {}).get("id", "")).replace("DE-", "")
                if pid not in MAERKTE or PROSPEKT_AUSSCHLUSS.search(b.get("title") or ""):
                    continue
                von, bis = _lokal(b["validFrom"]), _lokal(b["validUntil"])
                if von > samstag or bis < montag:
                    continue
                gefunden[b["contentId"]] = (pid, b)
    return gefunden, fehler


def _deals(deals):
    """kaufDA-Preisarten -> preis, app_preis, normal, staffel."""
    verkauf = [d for d in deals if d.get("type") == "SALES_PRICE" and d.get("min")]
    spezial = [d for d in deals if d.get("type") == "SPECIAL_PRICE" and d.get("min")]
    normal = [d.get("max") or d.get("min") for d in deals
              if d.get("type") in ("REGULAR_PRICE", "RECOMMENDED_RETAIL_PRICE") and (d.get("max") or d.get("min"))]
    bed = lambda d: " ".join(c.get("other") or "" for c in d.get("conditions", []))
    app = [d for d in spezial if re.search(r"app|plus", bed(d), re.I)]
    staffel = [d for d in spezial if re.search(r"\bab\b|für", bed(d), re.I) and d not in app]
    preis = min((d["min"] for d in verkauf), default=None)
    if preis is None and spezial:          # nur Aktionspreis vorhanden
        preis = min(d["min"] for d in spezial)

    def je_stueck(d):
        """'2 für' 8.00 -> 4.00 je Packung; 'ab 3 Kisten je' 15.93 -> 15.93"""
        m = re.search(r"(\d+)\s*für", bed(d), re.I)
        return round(d["min"] / int(m.group(1)), 2) if m else d["min"]

    def bedingung(d):
        b = bed(d).strip()
        m = re.search(r"(\d+)\s*für", b, re.I)
        return f"{m.group(1)} für {str(d['min']).replace('.', ',')} €" if m else re.sub(r"\s+je$", "", b)

    return {
        "preis": preis,
        "app_preis": min((d["min"] for d in app), default=None),
        "normal": max(normal) if normal else None,
        "staffel": [{"preis": je_stueck(d), "bedingung": bedingung(d)} for d in sorted(staffel, key=je_stueck)],
    }


def kaufda_angebote(montag, samstag):
    brochures, fehler = prospekte(montag, samstag)
    roh, zaehler = [], {}
    for cid, (pid, b) in brochures.items():
        markt = MAERKTE[pid]["name"]
        try:
            d = requests.get(f"https://content-viewer-be.kaufda.de/v1/brochures/{cid}/pages",
                             params={"partner": "kaufda_web", "lat": LAT, "lng": LNG}, headers=UA, timeout=40).json()
        except Exception as e:
            fehler.append(f"{markt} ({b.get('title')}): {e}")
            continue
        n_offers = 0
        for page in d.get("contents", []):
            for off in page.get("offers", []):
                c = off.get("content", {})
                prods = c.get("products", [])
                if not prods:
                    continue
                n_offers += 1
                kats = [cp["name"] for p in prods for cp in p.get("categoryPaths", [])]
                namen = " / ".join(dict.fromkeys(p.get("name") or "" for p in prods))
                marken = ", ".join(dict.fromkeys(p.get("brandName") for p in prods if p.get("brandName")))
                info = " ".join(dict.fromkeys(x.get("paragraph", "") for p in prods for x in p.get("description", [])))
                info = re.sub(r"\s+", " ", info).strip()
                alles = f"{namen} {marken} {info}"
                ist_bier = "Bier" in kats or (re.search(r"\bbier", namen, re.I) and "Lebensmittel und Getränke" in kats)
                if not ist_bier or KEIN_BIER_RX.search(f"{namen} {info} {' '.join(kats[-3:])}"):
                    continue
                if not BIER_RX.search(alles + " " + " ".join(kats)):
                    continue
                gueltig = (c.get("publicationProfiles") or [{}])[0].get("validity") or {}
                von = _lokal(gueltig["startDate"]) if gueltig.get("startDate") else _lokal(b["validFrom"])
                bis = _lokal(gueltig["endDate"]) if gueltig.get("endDate") else _lokal(b["validUntil"])
                roh.append({
                    "markt": markt, "pid": pid, "marke": marken or None, "produkt": namen, "info": info,
                    **_deals(c.get("deals", [])),
                    "von": max(von, montag).isoformat(), "bis": min(bis, samstag).isoformat(),
                    "bild": next((im["url"] for p in prods for im in (p.get("images") or []) if im.get("url")), None)
                            or c.get("image"),
                    "quelle": "kaufDA", "prospekt": b.get("title"),
                })
        zaehler[markt] = zaehler.get(markt, 0) + n_offers
        print(f"{markt:10} {b.get('title')!r}: {n_offers} Angebote im Prospekt", file=sys.stderr)
    return roh, zaehler, fehler


# ======================= EDEKA (über --edeka-json) =======================
def edeka_angebote(pfad, montag, samstag):
    daten = json.load(open(pfad, encoding="utf-8"))
    if isinstance(daten, dict):
        daten = daten.get("angebote", [])
    roh = []
    for o in daten:
        if not isinstance(o.get("preis"), (int, float)):
            continue
        roh.append({
            "markt": "EDEKA", "pid": "edeka", "marke": o.get("marke"), "produkt": o.get("produkt") or o.get("marke"),
            "info": re.sub(r"\s+", " ", o.get("info") or "").strip(),
            "preis": o["preis"], "app_preis": o.get("app_preis"), "normal": o.get("normal"), "staffel": [],
            "tiefst30": o.get("tiefst30"),
            "von": o.get("von") or montag.isoformat(), "bis": o.get("bis") or samstag.isoformat(),
            "bild": None, "quelle": "edeka.de", "prospekt": "Marktangebote",
        })
    return roh


# ======================= Filialen (kaufDA-Filialverzeichnis) =======================
def _km(lat1, lng1, lat2, lng2):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _seite(url):
    r = requests.get(url, headers=UA, timeout=25)
    if r.status_code == 404:
        return None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    return json.loads(m.group(1))["props"]["pageProps"].get("pageInformation") if m else None


def filialen_laden():
    """{Marktname: [{name, adresse, ort, km, maps}]} für alle Händler in MAERKTE, Orte aus ORTE im RADIUS_KM."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote

    def ort_info(ort):
        if ort in ORT_KOORD:
            return ort, *ORT_KOORD[ort]
        try:
            pi = _seite(f"https://www.kaufda.de/{ort}")
            loc = (pi or {}).get("location") or {}
            return ort, loc.get("lat"), loc.get("lng")
        except Exception:
            return ort, None, None

    with ThreadPoolExecutor(8) as ex:
        orte = [o for o in ex.map(ort_info, ORTE) if o[1]]
    orte = [(o, _km(LAT, LNG, la, ln)) for o, la, ln in orte if _km(LAT, LNG, la, ln) <= RADIUS_KM]

    def abfrage(args):
        markt, slug, rid, ort, km = args
        try:
            pi = _seite(f"https://www.kaufda.de/Filialen/{ort}/{slug}/v-r{rid}")
        except Exception:
            return markt, []
        box = ((pi or {}).get("template") or {}).get("content", {}).get("StoreLogoLinkbox") or {}
        res = []
        for l in box.get("links", []):
            t = l.get("link_text") or {}
            if not t.get("address"):
                continue
            res.append({"name": t.get("name"), "adresse": t["address"], "ort": t.get("city", ""),
                        "km": round(km + min(l.get("distance") or 0, 5) * 0.5 if (l.get("distance") or 0) < 5 else km, 1)})
        return markt, res

    jobs = [(m["name"], *m["laden"], ort, km) for m in MAERKTE.values() for ort, km in orte]
    alle = {}
    with ThreadPoolExecutor(8) as ex:
        for markt, liste in ex.map(abfrage, jobs):
            for f in liste:
                key = (f["adresse"].lower(), f["ort"][:5])
                vorh = {(x["adresse"].lower(), x["ort"][:5]): x for x in alle.setdefault(markt, [])}
                if key in vorh:
                    vorh[key]["km"] = min(vorh[key]["km"], f["km"])
                else:
                    alle[markt].append(f)
    for markt, liste in alle.items():
        for f in liste:
            f["ort"] = re.sub(r",\s*(Kr|Niedersachs).*$", "", f["ort"]).strip()
            f["maps"] = "https://www.google.com/maps/search/?api=1&query=" + quote(f"{markt} {f['adresse']} {f['ort']}")
        liste.sort(key=lambda f: f["km"])
    return alle


def filialen(pfad):
    """Filialliste aus Cache (bis 4 Wochen alt), sonst neu von kaufDA; bei Fehlern alter Cache."""
    try:
        cache = json.load(open(pfad, encoding="utf-8"))
        alter = datetime.now(BERLIN) - datetime.fromisoformat(cache["stand"])
    except Exception:
        cache, alter = None, None
    if cache and alter is not None and alter < FILIALEN_MAX_ALTER:
        return cache["filialen"]
    try:
        neu = filialen_laden()
        if sum(len(v) for v in neu.values()) >= 5:
            json.dump({"stand": datetime.now(BERLIN).isoformat(timespec="minutes"), "radius_km": RADIUS_KM,
                       "filialen": neu}, open(pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"Filialen neu geladen: {', '.join(f'{k} {len(v)}' for k, v in neu.items())}", file=sys.stderr)
            return neu
    except Exception as e:
        print(f"Filialen: {e}", file=sys.stderr)
    return cache["filialen"] if cache else {}


# ======================= Bilder =======================
def bilder_speichern(angebote, ordner):
    """Produktfoto je Angebot als kleines WebP nach ordner/ (alte Bilder werden entfernt)."""
    import io
    from PIL import Image
    os.makedirs(ordner, exist_ok=True)
    for f in os.listdir(ordner):
        if f.endswith(".webp"):
            os.remove(os.path.join(ordner, f))
    ok = 0
    for i, a in enumerate(angebote):
        url = a.pop("bild", None)
        a["bild"] = None
        if not url:
            continue
        name = f"{i:03d}-{re.sub(r'[^a-z0-9]+', '-', (a['marke'] or a['produkt'] or 'bier').lower())[:30]}.webp"
        try:
            im = Image.open(io.BytesIO(requests.get(url, headers=UA, timeout=30).content))
            im = im.convert("RGBA")
            hg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(hg, im).convert("RGB")
            im.thumbnail((240, 240))
            im.save(os.path.join(ordner, name), "WEBP", quality=78)
            a["bild"] = f"img/{name}"
            ok += 1
        except Exception as e:
            print(f"  ! Bild {a['marke']}: {e}", file=sys.stderr)
    return ok


# ======================= Aufbereitung =======================
def info_kurz(info):
    """Kleintext ohne Gebinde/Pfand/Grundpreis (die zeigt die Seite separat): 'versch. Sorten, auch alkoholfrei'."""
    t = " " + (info or "") + " "
    t = re.sub(r",?\s*pfandfrei", " ", t, flags=re.I)
    t = re.sub(r"(zzgl\.?|\+)?\s*\d+[.,]\d{2}(\s*/\s*\d+[.,]\d{2})*\s*(€\s*)?pfand", " ", t, flags=re.I)
    t = re.sub(r"(zzgl\.?|\+|,)?\s*\(?\s*(zzgl\.?\s*)?pfand\s*(=|:)?\s*(\d+[.,]\d{2}(\s*/\s*\d+[.,]\d{2})*)?\s*\)?", " ", t, flags=re.I)
    menge = r"\d+(?:[.,]\d+)?\s*-?\s*(?:liter|ml|l)(?![a-zäöü])"
    t = re.sub(r"(je\s*)?(ka\.?|kasten|packg?\.?|kg\.)?\s*\d{1,2}\s*[x×]\s*\d+(?:[.,]\d+)?(\s*(?:liter|ml|l)(?![a-zäöü]))?"
               r"(\s*/\s*\d{1,2}\s*[x×]\s*\d+(?:[.,]\d+)?(\s*(?:liter|ml|l)(?![a-zäöü]))?)*"
               r"(-?(?:liter|ml|l)\b)?(-[a-zäöü.]+)*\.?", " ", t, flags=re.I)
    t = re.sub(r"(je\s*)?" + menge + r"(-[a-zäöü.]+)*", " ", t, flags=re.I)
    t = re.sub(r"\b(flaschen?|fl\.|dosen?|dpg-(flasche|dose)|pet-dpg-flasche|fass|kasten|sixpack|-?kasten)\b", " ", t, flags=re.I)
    t = re.sub(r"\(?\s*1\s*(l|kg)\s*=\s*\d+[.,]\d+\s*\)?", " ", t, flags=re.I)
    t = re.sub(r"\b(je|zzgl\.?|ka\.|packg\.|kg\.)\s*(?=[,.;/]|$)", " ", t.strip(), flags=re.I)
    t = re.sub(r"\s*/\s*(?=[,.;]|$)", " ", t)
    t = re.sub(r"\s*([,;])(\s*[,;])+", ",", t)
    t = re.sub(r"\s+([,;.])", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;.·-/")
    return t


def _marke_kurz(m):
    """'BECK'S' -> "Beck's", 'KÖNIG-BRAUEREI' -> 'König-Brauerei'; gemischte Schreibweise bleibt."""
    def wort(w):
        if not (w.isupper() and len(w) > 3):
            return w
        return re.sub(r"(^|[\-/&.])(\w)", lambda x: x.group(1) + x.group(2).upper(), w.lower())
    return " ".join(wort(w) for w in (m or "").split())


def aufbereiten(roh):
    res, seen = [], set()
    for o in roh:
        if not o.get("preis"):
            continue
        text = f"{o['produkt']} {o.get('marke') or ''} {o['info']}"
        gebinde = gebinde_parsen(o["info"]) or gebinde_parsen(o["produkt"])
        if not gebinde:
            print(f"  ! kein Gebinde erkannt: {o['markt']} {o.get('marke')} {o['produkt']} | {o['info']}", file=sys.stderr)
            continue
        anzahl, liter = gebinde[0]
        gesamt = round(anzahl * liter, 3)
        pfand = [0.0] if re.search(r"pfandfrei", o["info"], re.I) else pfand_parsen(o["info"])
        marke = _marke_kurz(o.get("marke"))
        produkt = o["produkt"]
        if not marke:                       # METRO/ALDI liefern oft keine Marke -> Produktname ist die Marke
            marke, produkt = _marke_kurz(produkt), ""
        if marke and produkt.lower().startswith(marke.lower()):
            produkt = produkt[len(marke):].strip(" -/,")
        if re.fullmatch(r"(bier|biere)", produkt, re.I) and marke:
            produkt = "Bier"
        key = (o["markt"], (marke or "").lower(), produkt.lower(), o["preis"])
        if key in seen:
            continue
        seen.add(key)
        bester = min(x for x in (o["preis"], o.get("app_preis"), *(s["preis"] for s in o.get("staffel", []))) if x)
        res.append({
            "markt": o["markt"], "marke": marke or None, "produkt": produkt, "info": o["info"],
            "info_kurz": info_kurz(o["info"]),
            "typ": typ_von(anzahl, liter, text), "art": art_von(o["produkt"], text),
            "anzahl": anzahl, "liter_einzel": liter, "liter": gesamt,
            "gebinde_text": f"{anzahl} × {str(liter).replace('.', ',')} l" if anzahl > 1 else f"{str(liter).replace('.', ',')} l",
            "weitere_gebinde": [f"{a} × {str(l).replace('.', ',')} l" for a, l in gebinde[1:]],
            "preis": o["preis"], "app_preis": o.get("app_preis"), "normal": o.get("normal"),
            "staffel": o.get("staffel") or [], "tiefst30": o.get("tiefst30"),
            "eur_l": round(o["preis"] / gesamt, 2),
            "eur_l_bester": round(bester / gesamt, 2),
            "pfand": pfand[0] if pfand else None,
            "von": o["von"], "bis": o["bis"], "bild": o.get("bild"),
            "quelle": o["quelle"], "prospekt": o.get("prospekt"),
        })
    return sorted(res, key=lambda r: (r["eur_l"], r["preis"]))


def verlauf_aktualisieren(pfad, kw, angebote):
    try:
        verlauf = json.load(open(pfad, encoding="utf-8"))
    except Exception:
        verlauf = {"wochen": {}}
    verlauf["wochen"][kw] = [
        {"markt": a["markt"], "marke": a["marke"], "produkt": a["produkt"], "gebinde": a["gebinde_text"],
         "preis": a["preis"], "eur_l": a["eur_l"]}
        for a in angebote if a["typ"] == "Kasten" and a["art"] in ("Bier", "Alkoholfrei")
    ]
    # nur das letzte Jahr behalten
    verlauf["wochen"] = dict(sorted(verlauf["wochen"].items())[-52:])
    json.dump(verlauf, open(pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return verlauf


def bestpreise(verlauf, aktuelle_kw):
    """Günstigster Kasten-Literpreis je Marke in den Vorwochen (ohne aktuelle Woche)."""
    best = {}
    for kw, liste in verlauf["wochen"].items():
        if kw == aktuelle_kw:
            continue
        for e in liste:
            k = (e["marke"] or e["produkt"] or "").lower()
            if k and (k not in best or e["eur_l"] < best[k]["eur_l"]):
                best[k] = {"eur_l": e["eur_l"], "preis": e["preis"], "markt": e["markt"], "kw": kw}
    return best


def main():
    ap = argparse.ArgumentParser(description="Bierpreise rund um Langlingen")
    ap.add_argument("--edeka-json", help="EDEKA-Bierangebote (aus WebFetch der EDEKA-Marktseite). " + EDEKA_FORMAT)
    ap.add_argument("--hinweise", help="Datei oder Text mit Hinweisen für die Seite")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bier-langlingen"))
    ap.add_argument("--datum", help="Stichtag JJJJ-MM-TT (Standard: heute)")
    a = ap.parse_args()

    heute = date.fromisoformat(a.datum) if a.datum else None
    montag, samstag = zielwoche(heute)
    kw = f"{montag.isocalendar().year}-W{montag.isocalendar().week:02d}"

    roh, zaehler, fehler = kaufda_angebote(montag, samstag)
    if a.edeka_json:
        e = edeka_angebote(a.edeka_json, montag, samstag)
        roh += e
        zaehler["EDEKA"] = len(e)
    angebote = aufbereiten(roh)

    hinweise = ""
    if a.hinweise:
        hinweise = open(a.hinweise, encoding="utf-8").read().strip() if os.path.exists(a.hinweise) else a.hinweise

    os.makedirs(a.out, exist_ok=True)
    verlauf = verlauf_aktualisieren(os.path.join(a.out, "verlauf.json"), kw, angebote)
    best = bestpreise(verlauf, kw)
    for x in angebote:
        b = best.get((x["marke"] or x["produkt"] or "").lower())
        if b and x["typ"] == "Kasten":
            x["bisher_bester"] = b

    fil = filialen(os.path.join(a.out, "filialen.json"))
    fil["EDEKA"] = [{**EDEKA_FILIALE, "maps": "https://www.google.com/maps/search/?api=1&query="
                     + requests.utils.quote(f"EDEKA Müller {EDEKA_FILIALE['adresse']} {EDEKA_FILIALE['ort']}")}]
    n_bilder = bilder_speichern(angebote, os.path.join(a.out, "img"))

    maerkte = []
    for pid, m in list(MAERKTE.items()) + [("edeka", EDEKA_MARKT)]:
        anz = sum(1 for x in angebote if x["markt"] == m["name"])
        if m["name"] in zaehler or anz:
            maerkte.append({"name": m["name"], "farbe": m["farbe"], "hinweis": m.get("hinweis"),
                            "angebote": anz, "im_prospekt": zaehler.get(m["name"]),
                            "filialen": fil.get(m["name"], [])})

    out = {
        "stand": datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M"),
        "woche": {"kw": montag.isocalendar().week, "von": montag.isoformat(), "bis": samstag.isoformat()},
        "ort": "Langlingen (29364) und Umgebung",
        "maerkte": maerkte,
        "hinweise": hinweise,
        "angebote": angebote,
    }
    json.dump(out, open(os.path.join(a.out, "bier.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\nKW {montag.isocalendar().week} ({montag:%d.%m.}–{samstag:%d.%m.}): {len(angebote)} Bier-Angebote")
    for m in maerkte:
        print(f"  {m['name']:10} {m['angebote']:3} Bier  (Prospekt: {m['im_prospekt']} Angebote, "
              f"{len(m['filialen'])} Filialen im Umkreis)")
    print(f"Bilder: {n_bilder}/{len(angebote)}")
    kaesten = [x for x in angebote if x["typ"] == "Kasten" and x["art"] == "Bier"][:5]
    print("Günstigste Kästen:")
    for x in kaesten:
        print(f"  {x['eur_l']:.2f} €/l  {x['preis']:6.2f} €  {x['markt']:9} {x['marke']} {x['produkt']} ({x['gebinde_text']})")
    if fehler:
        print("Fehler:", *fehler, sep="\n  ")
    leer = [m["name"] for m in maerkte if m["im_prospekt"] == 0]
    if leer:
        print("Prospekt ohne strukturierte Angebote (nur Bilder):", ", ".join(leer))


if __name__ == "__main__":
    main()
