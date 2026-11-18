#!/usr/bin/env python3
"""Restaurants-Sync: Notion-Datenbank "Restaurants" -> restaurants/data.json

Die Website /restaurants liest nur restaurants/data.json. Dieses Skript
mischt die Notion-Zeilen (Name, Liste, Bewertungen, Küche, Notiz) mit den
recherchierten Details (Adresse, Öffnungszeiten, Links …), die schon in
data.json stehen oder per --details neu dazukommen.

Aufruf:
  python3 tools/restaurants_sync.py --notion rows.json [--details details.json]

rows.json   = Liste der Notion-Zeilen, so wie sie das Notion-Query-Tool
              liefert (Schlüssel: url, Name, Liste, Noah, Helen, Küche, Notiz).
details.json = optional, {"<Notion-Page-ID oder Name>": {…Details…}}
              (gleiches Format wie "details" in data.json).

Am Ende listet das Skript Restaurants ohne Details auf ("FEHLT: …"),
damit der geplante Auftrag sie recherchieren und per --details nachtragen kann.
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "restaurants" / "data.json"
NOTION_DB = "https://www.notion.so/41c334cadfee801b85d1dcffd349fcc1"


def page_id(url_or_id: str) -> str:
    m = re.search(r"([0-9a-f]{32})", (url_or_id or "").replace("-", ""))
    return m.group(1) if m else ""


def stars(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) or None
    n = str(v).count("⭐")
    return n or None


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notion", required=True, help="JSON-Liste der Notion-Zeilen")
    ap.add_argument("--details", help="JSON-Objekt mit neuen/geänderten Details")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    alt = json.loads(out.read_text("utf-8")) if out.exists() else {"restaurants": []}
    alt_by_id = {r["id"]: r for r in alt.get("restaurants", [])}
    alt_by_name = {norm(r["name"]): r for r in alt.get("restaurants", [])}

    rows = json.loads(pathlib.Path(a.notion).read_text("utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("results", [])
    neu_details = json.loads(pathlib.Path(a.details).read_text("utf-8")) if a.details else {}

    liste = []
    for row in rows:
        pid = page_id(row.get("url") or row.get("id") or "")
        name = (row.get("Name") or "").strip()
        if not pid or not name:
            continue
        vorher = alt_by_id.get(pid) or alt_by_name.get(norm(name)) or {}
        details = neu_details.get(pid) or neu_details.get(name) or vorher.get("details")
        liste.append({
            "id": pid,
            "name": name,
            "liste": row.get("Liste") or "Ausprobieren",
            "noah": stars(row.get("Noah")),
            "helen": stars(row.get("Helen")),
            "kueche": row.get("Küche") or None,
            "notiz": (row.get("Notiz") or "").strip(),
            "notion_url": f"https://www.notion.so/{pid}",
            "details": details,
        })

    if not liste:
        sys.exit("Keine Notion-Zeilen gelesen – data.json bleibt unverändert.")

    liste.sort(key=lambda r: (r["liste"] != "Favorit", r["name"].lower()))
    if liste == alt.get("restaurants"):
        print("Keine Änderungen – data.json bleibt unverändert.")
        for r in liste:
            if not r["details"]:
                print(f"FEHLT: {r['name']} ({r['id']}) – noch keine Details recherchiert")
        return
    data = {
        "stand": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="minutes"),
        "notion": NOTION_DB,
        "restaurants": liste,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")

    bewertet = sum(1 for r in liste if r["noah"] or r["helen"])
    print(f"{len(liste)} Restaurants, {bewertet} bewertet -> {out}")
    for r in liste:
        if not r["details"]:
            print(f"FEHLT: {r['name']} ({r['id']}) – noch keine Details recherchiert")


if __name__ == "__main__":
    main()
