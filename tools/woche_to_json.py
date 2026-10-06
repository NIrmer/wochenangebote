"""woche.md (Notion-Markdown aus prospekt_scraper.py) -> angebote.json für die Website.

Aufruf:  python3 tools/woche_to_json.py woche.md angebote.json
"""
import html, json, re, sys, unicodedata
from datetime import date

MARKT_IDS = {"LIDL": "lidl", "REWE": "rewe", "EDEKA": "edeka"}


def _clean(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    t = re.sub(r"(?<!\\)\*\*", "", t)       # Fettdruck
    t = re.sub(r"\\(.)", r"\1", t)          # Notion-Escapes entfernen
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _num(t):
    m = re.search(r"(\d+[.,]\d+|\d+)", t or "")
    return float(m.group(1).replace(",", ".")) if m else None


def parse(md):
    callout = re.search(r"<callout[^>]*>(.*?)</callout>", md, re.S)
    lines = [_clean(l) for l in (callout.group(1).splitlines() if callout else []) if l.strip()]
    kopf = next((l for l in lines if l.startswith("KW")), "")
    kw = int(_num(kopf) or 0)
    stand = re.search(r"Stand (\d{4}-\d{2}-\d{2})", kopf)
    stand = stand.group(1) if stand else date.today().isoformat()
    hinweise = next((l[len("Hinweise:"):].strip() for l in lines if l.startswith("Hinweise:")), "")
    quellen = next((l[len("Quellen:"):].strip() for l in lines if l.startswith("Quellen:")), "")
    legende = {}
    leg = next((l[len("Legende:"):].strip() for l in lines if l.startswith("Legende:")), "")
    cur = None
    for w in leg.split():
        if unicodedata.category(w[0]).startswith("S"):     # Emoji startet neue Kategorie
            cur = w
            legende[cur] = ""
        elif cur:
            legende[cur] = (legende[cur] + " " + w).strip()

    # Gültigkeit: Montag–Samstag der KW
    jahr = int(stand[:4])
    if kw and date.fromisoformat(stand).isocalendar()[1] > kw + 10:   # Jahreswechsel
        jahr += 1
    von = date.fromisocalendar(jahr, kw, 1).isoformat() if kw else None
    bis = date.fromisocalendar(jahr, kw, 6).isoformat() if kw else None

    maerkte = []
    for block in re.split(r"^## ", md, flags=re.M)[1:]:
        titel = block.splitlines()[0].strip()
        kette = titel.split()[0].upper()
        name, _, adresse = titel.partition(" – ")
        angebote = []
        for i, tr in enumerate(re.findall(r"<tr>(.*?)</tr>", block, re.S)):
            cells = [_clean(c) for c in re.findall(r"<td>(.*?)</td>", tr, re.S)]
            if i == 0 or len(cells) < 6:
                continue                     # Kopfzeile
            emoji, produkt, info, preis, normal, grundpreis = cells[:6]
            warn = produkt.startswith("⚠")
            produkt = produkt.lstrip("⚠ ").strip()
            ersparnis = re.search(r"−\s*(\d+)\s*%", normal)
            angebote.append({
                "emoji": emoji,
                "kategorie": legende.get(emoji, ""),
                "produkt": produkt,
                "warn": warn,
                "info": info,
                "preis": _num(preis),
                "app": "(App)" in preis,
                "normal": _num(normal.split("(")[0]) if normal else None,
                "ersparnis": int(ersparnis.group(1)) if ersparnis else None,
                "grundpreis": grundpreis or None,
            })
        maerkte.append({"id": MARKT_IDS.get(kette, kette.lower()), "name": name.strip(),
                        "adresse": adresse.strip(), "angebote": angebote})

    return {"kw": kw, "stand": stand, "von": von, "bis": bis, "quellen": quellen,
            "hinweise": hinweise, "legende": legende, "maerkte": maerkte}


if __name__ == "__main__":
    src, dst = (sys.argv[1:3] + ["woche.md", "angebote.json"][len(sys.argv[1:3]):])
    data = parse(open(src, encoding="utf-8").read())
    n = sum(len(m["angebote"]) for m in data["maerkte"])
    if not n:
        sys.exit("Keine Angebote gefunden – angebote.json NICHT überschrieben.")
    json.dump(data, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"KW {data['kw']}: {n} Angebote in {len(data['maerkte'])} Märkten -> {dst}")
