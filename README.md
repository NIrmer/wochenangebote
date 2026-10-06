# Wochenangebote Braunschweig

Website: https://wochenangebote-bs.de

Zeigt die gefilterten Prospekt-Angebote von LIDL (Celler Str.), REWE (Wendenring) und EDEKA Center Görge.

- `index.html` – die Seite (statisch, kein Build)
- `angebote.json` – Daten der aktuellen Woche, wird jeden Sonntag vom geplanten Auftrag aktualisiert
- `tools/prospekt_scraper.py` – Noahs Scraper (wird vom Sonntagsauftrag direkt aus dem Repo ausgeführt), schreibt Notion-Markdown und `angebote.json`
