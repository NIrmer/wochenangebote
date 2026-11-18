# Wochenangebote Braunschweig

Website: https://wochenangebote-bs.de

Zeigt die gefilterten Prospekt-Angebote von LIDL (Celler Str.), REWE (Wendenring) und EDEKA Center Görge.

- `index.html` – die Seite (statisch, kein Build)
- `angebote.json` – Daten der aktuellen Woche, wird jeden Sonntag vom geplanten Auftrag aktualisiert
- `tools/prospekt_scraper.py` – Noahs Scraper (wird vom Sonntagsauftrag direkt aus dem Repo ausgeführt), schreibt Notion-Markdown und `angebote.json`

## /restaurants

- `restaurants/index.html` – Restaurant-Liste von Noah & Helen (Liquid-Glass-Design, statisch)
- `restaurants/data.json` – Daten; Bewertungen/Listen kommen aus der Notion-Datenbank „Restaurants“, Details (Adresse, Zeiten, Links) sind recherchiert
- `restaurants/config.json` – optional `google_maps_api_key` (Places API New + Maps JavaScript API, auf `wochenangebote-bs.de/*` beschränken) für Fotos, Live-Öffnungszeiten und Google-Bewertungen
- `tools/restaurants_sync.py` – mischt Notion-Zeilen in `data.json` (wird vom täglichen Sync-Auftrag aufgerufen)
