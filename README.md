# Wochenangebote Braunschweig

Website: https://wochenangebote-bs.de

Zeigt die gefilterten Prospekt-Angebote von LIDL (Celler Str.), REWE (Wendenring) und EDEKA Center Görge.

- `index.html` – die Seite (statisch, kein Build)
- `angebote.json` – Daten der aktuellen Woche, wird jeden Sonntag vom geplanten Auftrag aktualisiert
- `tools/woche_to_json.py` – wandelt die `woche.md` des Scrapers in `angebote.json` um
