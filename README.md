# Wochenangebote Braunschweig

Website: https://wochenangebote-bs.de

Zeigt die gefilterten Prospekt-Angebote von LIDL (Celler Str.), REWE (Wendenring) und EDEKA Center Görge.

- `index.html` – die Seite (statisch, kein Build)
- `angebote.json` – Daten der aktuellen Woche, wird jeden Sonntag vom geplanten Auftrag aktualisiert
- `tools/prospekt_scraper.py` – Noahs Scraper (wird vom Sonntagsauftrag direkt aus dem Repo ausgeführt), schreibt Notion-Markdown und `angebote.json`

## /restaurants

- `restaurants/index.html` – Restaurant-Liste von Noah & Helen (Liquid-Glass-Design, statisch). Bewerten, Hinzufügen, Bearbeiten direkt auf der Seite.
- Daten live in **Firebase Firestore** (Collection `restaurants`, `personen`); Login mit Google, schreiben dürfen nur die in den Firestore-Regeln eingetragenen Konten.
- `restaurants/data.json` – Startliste (wird beim ersten Login einmalig nach Firestore übernommen) und Anzeige, solange Firebase nicht erreichbar ist.
- `restaurants/config.json` – `firebase` (Web-App-Konfiguration, öffentlich unbedenklich) und optional `google_maps_api_key` (Places API New + Maps JavaScript API, auf `wochenangebote-bs.de/*` beschränkt) für Fotos, Live-Öffnungszeiten und Google-Bewertungen.
