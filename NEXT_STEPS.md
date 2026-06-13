# HCR2 Bot Refactor - Next Steps

Stand: 2026-06-13

## Kurzfassung fuer die naechste Codex-Session

Wir refactoren `hcr2-bot` schrittweise von alten `modules/*`-Skripten in eine saubere Paketstruktur unter `hcr2/`.

Aktueller Stand:

- Typer ist installiert und in `requirements.txt` dokumentiert.
- `hcr2.py` ist nur noch ein Compatibility-Entrypoint.
- `python -m hcr2` funktioniert.
- Einheitliche Help-Ausgaben sind umgesetzt.
- Bash Completion liegt unter `completions/hcr2.bash`.
- DB-Zugriff ist zentral in `hcr2/db/connection.py`.
- Migration Runner ist umgesetzt:
  - `migrate_db.py`
  - `create_db.py` als Compatibility Wrapper
  - `hcr2/db/migrations.py`
  - `hcr2/db/migrations/0001_initial_schema.sql`
- Nextcloud/WebDAV ist aus `modules/sheet.py` nach `hcr2/integrations/nextcloud.py` extrahiert.
- Tests liegen in `tests/test_cli_smoke.py`.
- Letzter Teststand: `python3 -m unittest discover -v` lief mit `86 tests` erfolgreich.

Bereits migrierte Domains:

- `vehicle`
  - Model
  - Repository
  - Service
  - Output
- `season`
  - Model
  - Repository
  - Output
- `match`
  - Model
  - Repository
  - Output
- `teamevent`
  - Model
  - Repository
  - Output
- `player`
  - Repository fuer list/show/activate/deactivate/delete/add/edit/bday/search/leader/away
  - Service fuer list/show/activate/deactivate/delete/add/edit/bday/search/leader/away
  - Output fuer list/detail/search/leader/absent/away
- `matchscore`
  - Model
  - Repository
  - Service
  - Output
- `donations`
  - Model
  - Repository
  - Service
  - Output
- `stats`
  - Repository-Slice fuer Season-/Performance-/TeamEvent-/Scatter-/Birthday-/Battle-/Player-Detail-Basisabfragen
  - Service-Slice fuer Performance-Deltas, Player-Trend/Medians und Player-Summary-/Donation-Aggregation
  - Output-Slice fuer Performance-/Score-/Points-/Absent-Tabellen, Scatter-/Birthday-/Battle-Plot und Player-Detailausgabe

## Wichtig fuer morgen

Noch uebrige Top-Level-Steps: 5 (`4. Sheet Import/Export` bis `8. Abschluss-Cleanup`).

Der naechste konkrete Einstieg ist Step 4 (`Sheet Import/Export weiter entkoppeln`):

- Step 1 ist inhaltlich erledigt: `modules/stats.py` enthaelt keine direkten SQL-Aufrufe mehr und `stats player` hat Summary/Donation-Aggregation im Service sowie Detailausgabe im Output.
- Step 2 ist fuer den dokumentierten Umfang erledigt:
  - `add_score(...)`: mehrdeutige Player-Namen
  - `delete_score(score_id)`: Not-found-Fall
  - `list_scores(...)`: `--season` und `--match` Filter im Service
  - `edit_score(...)`: Score-/Points-Grenzen und Abwesenheits-Recompute
- Step 3 ist vorbereitet: `modules/donations.py` wurde analysiert und Smoke-Tests fuer Add/Upsert/Edit/List/Show/Index wurden ergaenzt.
- Step 3 ist migriert: `modules/donations.py` enthaelt keine direkten SQL-Aufrufe mehr und nutzt `hcr2/models|repositories|services|output/donations.py`.
- Step 4 erste Slices sind erledigt:
  - Sheet-Dateinamen/Remote-Pfade/Web-URLs und Donation-k-Parsing liegen in `hcr2/services/sheets.py`.
  - Player-/Donation-Workbook-Erzeugung und Import-Reading liegen in `hcr2/exporters/excel.py`.
  - Player-Import-Diff/Update und Donation-Import-Upserts liegen in `hcr2/services/sheets.py`.
  - Donations-Import nutzt keinen Selbstaufruf per `python hcr2.py donations add` mehr.
  - Match-Sheet-Import nutzt keine Selbstaufrufe per `python hcr2.py player add`, `matchscore add` oder `match edit` mehr.
  - Match-Sheet-Workbook-Reading liegt in `hcr2/exporters/excel.py`.
  - Match-Sheet-Import-Parsing/Validierung liegt in `hcr2/services/sheets.py`.
  - Player-/Donation-Exportdaten werden in `hcr2/services/sheets.py` vorbereitet.
  - Tests fuer Pfade, netzwerkfreien Match-Sheet-Export, Workbook-Strukturen, Workbook-Reading, Import-Services, Exportdaten und Match-Sheet-Validierung sind ergaenzt.
- Naechster sinnvoller Einstieg: lokale Datei-/Upload-Orchestrierung in `modules/sheet.py` weiter ausduennen, besonders Match-Exportdaten/Ranking und Workbook-Speichern/Upload-Wrapper in Services/Integrationen vorbereiten.

Bitte mit folgendem Prompt weitermachen:

```text
Wir machen im hcr2-bot weiter. Noch uebrig: 5 Top-Level-Steps. Stand: Stats Step 1, der dokumentierte Matchscore-Teil aus Step 2 und Donations Step 3 sind erledigt. Step 4 hat erste Slices: `hcr2/services/sheets.py` fuer Sheet-Dateinamen/Remote-Pfade/Web-URLs, Donation-k-Parsing, Player-Import-Diff/Update, Donation-Import-Upserts, Match-Sheet-Anwendung ohne Selbstaufrufe, Match-Sheet-Import-Validierung und Player-/Donation-Exportdaten; `hcr2/exporters/excel.py` fuer Player-/Donation-Workbook-Erzeugung sowie Player-/Donation-/Match-Sheet-Workbook-Reading. `python3 -m unittest discover -v` ist mit 86 Tests gruen. Bitte mach als naechstes in Step 4 weiter: lokale Datei-/Upload-Orchestrierung in `modules/sheet.py` weiter ausduennen, besonders Match-Exportdaten/Ranking und Workbook-Speichern/Upload-Wrapper in Services/Integrationen vorbereiten.
```

## Naechste Schritte

### 1. Stats Domain migrieren

Ziel:

- `modules/stats.py` analysieren.
- Repository fuer SQL-Abfragen anlegen:
  - `hcr2/repositories/stats.py`
- Service fuer Berechnungen/Filter:
  - `hcr2/services/stats.py`
- Output fuer Tabellen:
  - `hcr2/output/stats.py`

Wichtig:

- Stats haben wahrscheinlich viele aggregierte SQL-Abfragen.
- Hier besonders vorsichtig refactoren und vorher Tests fuer Ist-Verhalten ergaenzen.
- Aktuell keine direkten SQL-Aufrufe mehr in `modules/stats.py`; diesen Zustand beibehalten.
- Erledigt: `stats player` Detailausgabe/Summary ist aus dem Adapter herausgezogen.

Empfohlene Reihenfolge:

1. Weitere Smoke-/Snapshot-Tests fuer bestehende Stats-Ausgaben ergaenzen:
   - Randfaelle fuer `scatter`, `bdayplot`, `battle`, `alias`
   - weitere `player`-Detailfaelle mit Donations
2. Weitere Berechnungen nach `hcr2/services/stats.py` extrahieren:
   - Battle-Plot-Daten
   - Player-Summary-Aggregation
3. Weitere Ausgabe nach `hcr2/output/stats.py` extrahieren:
   - `player` Detailausgabe

Bereits erledigt:

- Smoke-Tests fuer `score`, `points`, `rank`, `perf`, `te`, `absent`, `player`.
- Smoke-Tests fuer `alias`, `scatter`, `bdayplot`, `battle`.
- Repository-Slice fuer Season-Meta, Season-Rows, Min-Matches, aktive PLTE-Spieler, Absent und TeamEvent-Rows.
- Repository-Slice fuer Scatter Season-Averages, Birthday-Plot-Daten und Battle-Daten.
- Repository-Slice fuer `stats player`: Player-Meta, Last/Overall-Matches, Median-Rows, Donation-Daten.
- Service-Slice fuer `is_absent`, active-PLTE-Pruefung, scaled scores und Delta-Berechnung.
- Service-Slice fuer `stats player`: Trend-Slope/-Labels, unexcused absence, Match-Medians.
- Service-Slice fuer `stats player`: Player-Summary-/Donation-Aggregation.
- Output-Slice fuer Performance-Tabelle und `format_k`.
- Output-Slice fuer Scatter-Plot und Birthday-Plot.
- Output-Slice fuer `score`/`points` Tabellen und `absent` Tabelle.
- Output-Slice fuer `battle` Plot.
- Output-Slice fuer `stats player` Detailausgabe.
- Tests fuer Player-Summary-/Donation-Aggregation und Player-Detailausgabe.

Aktuell offen in Step 1:

- Keine offenen Punkte fuer den definierten Step-1-Abschluss.
- Optional spaeter: weitere Stats-CLI-Adapter ausduennen, z.B. Battle-/Rank-/Score-Aggregation noch staerker in Services verschieben.

### 2. Player und Matchscore weiter haerten

Erledigt:

- Player-Restlogik ist nach Repository/Service/Output migriert.
- `modules/player.py` enthaelt keine direkten SQL-Aufrufe mehr.
- Tests fuer Player add/edit/bday/search/leader/away und Output ergaenzt.
- Business-Logik aus `modules/matchscore.py` nach `hcr2/services/matchscores.py` verschoben.
- `modules/matchscore.py` enthaelt fuer Add/List/Delete/Edit nur noch Parsing, Service-Aufruf und Ausgabe.
- Tests fuer Add/Update/Delete, Default-Listenfilter und Edit-Clash ergaenzt.
- Ausgabeformatierung aus `modules/matchscore.py` nach `hcr2/output/matchscores.py` verschoben.
- Tests fuer Kurzliste, Detailgruppe mit Match-Result, Delete-Ausgabe und Edit-Ausgabe ergaenzt.
- Tests fuer mehrdeutige Player-Namen, Delete-not-found, Season-/Match-Filter und Edit-Grenzen/Recompute ergaenzt.

Weitere Kandidaten fuer spaeter:

- CLI-Ausgaben fuer Matchscore-Fehlerfaelle noch direkter testen, falls am Adapter weiter gearbeitet wird.
- Service-Tests in eigene Datei aus `tests/test_cli_smoke.py` herausziehen.

Wichtig:

- CLI-Ausgabe nicht versehentlich aendern.
- Bestehende Help-Ausgabe unveraendert lassen.

Pruefen:

```bash
python3 -m py_compile modules/matchscore.py hcr2/services/matchscores.py tests/test_cli_smoke.py
python3 -m py_compile hcr2/output/matchscores.py
python3 -m unittest discover -v
```

### 3. Donations Domain migrieren

Ziel:

- Erledigt: `modules/donations.py` in Model/Repository/Service/Output zerlegen.

Moegliche Dateien:

- `hcr2/models/donation.py`
- `hcr2/repositories/donations.py`
- `hcr2/services/donations.py`
- `hcr2/output/donations.py`

Wichtig:

- Vorher klaeren, welche DB-Tabellen und CLI-Kommandos betroffen sind.
- Tests fuer Listen, Filter und Grenzfaelle sind vorbereitet:
  - Add/Upsert/Edit
  - Donation-Dates und Entries fuer Datum
  - Player-Show und All-Stats
  - Donation-Index und Under-100-Ausgabe
- `modules/donations.py` enthaelt keine direkten SQL-Aufrufe mehr.

### 4. Sheet Import/Export weiter entkoppeln

Bereits erledigt:

- Nextcloud/WebDAV in `hcr2/integrations/nextcloud.py`.

Noch offen:

- Excel-/OpenPyXL-Logik aus `modules/sheet.py` extrahieren.
- Lokale Datei-Erzeugung, Remote-Pfade und Uploads weiter trennen.

Moegliche Zielstruktur:

- `hcr2/services/sheets.py`
- `hcr2/output/sheets.py`
- `hcr2/integrations/excel.py` oder `hcr2/exporters/excel.py`

Wichtig:

- Keine Netzwerkzugriffe in Tests.
- Nextcloud-Funktionen mocken.
- Export-Dateinamen und Remote-Pfade sind fuer Match-Sheets getestet.
- Donation-k-Parsing ist getestet.
- Player-/Donation-Workbook-Erzeugung und Workbook-Reading sind extrahiert und getestet.

### 5. CLI Adapter weiter ausduennen

Ziel:

- Dateien in `modules/*` bleiben vorerst bestehen, aber nur noch als Compatibility-CLI-Schicht.
- Jede Datei sollte langfristig nur noch:
  - Argumente parsen
  - Service aufrufen
  - Output-Funktion aufrufen
  - Help anzeigen

Prioritaet:

1. `modules/matchscore.py`
2. `modules/player.py`
3. `modules/stats.py`
4. `modules/donations.py`
5. `modules/sheet.py`

### 6. Tests ausbauen

Aktuell:

- Eine zentrale Smoke-Datei: `tests/test_cli_smoke.py`.

Spaeter sinnvoll:

- Tests nach Bereichen aufteilen:
  - `tests/test_cli_help.py`
  - `tests/test_repositories.py`
  - `tests/test_services.py`
  - `tests/test_output.py`
  - `tests/test_migrations.py`

Kurzfristig:

- Bei jedem Refactor-Schritt gezielt 2-5 Tests fuer die neue Schicht ergaenzen.
- Weiterhin immer komplette Suite laufen lassen:

```bash
python3 -m unittest discover -v
```

### 7. README und Completion final pruefen

Nach den groesseren Refactor-Schritten:

- README gegen aktuellen Stand pruefen.
- Bash Completion pruefen.
- Help-Ausgaben fuer alle Entities pruefen:

```bash
python3 hcr2.py --help
python3 hcr2.py vehicle --help
python3 hcr2.py player --help
python3 hcr2.py teamevent --help
python3 hcr2.py season --help
python3 hcr2.py match --help
python3 hcr2.py matchscore --help
python3 hcr2.py stats --help
python3 hcr2.py sheet --help
python3 hcr2.py donations --help
```

### 8. Abschluss-Cleanup

Wenn alle Domains migriert sind:

- Doppelte Helper in `modules/common.py` pruefen.
- Alte oder ungenutzte Funktionen entfernen.
- Imports bereinigen.
- README aktualisieren.
- `git status --short` pruefen.
- Kompletttest laufen lassen.

## Aktuelle Arbeitsregel

Bitte weiterhin schrittweise arbeiten:

1. Erst Kontext der betroffenen Datei lesen.
2. Kleine Zielschicht bauen.
3. Bestehendes Modul darauf umverdrahten.
4. Tests ergaenzen.
5. `python3 -m unittest discover -v` laufen lassen.
6. Erst danach naechsten Step starten.
