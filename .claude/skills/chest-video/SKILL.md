---
name: chest-video
description: Wochenkilometer aus dem Video der Team-Distanztruhe auslesen und nach distance schreiben. Nutzen, wenn Kilometer, Wochenleistung oder die Truhe abgeglichen werden sollen, egal wie formuliert ("/chest-video 34", "w34 ist hochgeladen", "Kilometer eintragen", "Wochentruhe auswerten", "wer ist wieviel gefahren"). Nicht verwechseln mit [[match-video]] (Match-Ergebnisse) oder [[player-video]] (Kader und Garage Power).
---

# Wochen-Truhe auswerten

Liest die Mitgliederaktivität der Team-Distanztruhe und schreibt die Kilometer je
Spielerin und ISO-Woche nach `distance`.

Argument: die Kalenderwoche, optional mit Jahr (`/chest-video 34`, `/chest-video 2026 34`).
Fehlt sie, aus dem Dateinamen im Nextcloud-Ordner ableiten — **nicht** aus dem heutigen
Datum raten, die Aufnahme kann Tage alt sein.

## Ablauf

### 1. Frames erzeugen

```bash
python3 hcr2.py video chest frames --year 2026 --week 34
```

Holt `Wochen-Truhe/<Jahr>/w<KW>.mp4` nach `tmp/video/chest/<Jahr>/w<KW>/` und schneidet
mit 1 fps. Gesucht wird über die **Wochennummer**, nicht den exakten Dateinamen —
`W34.mp4`, `w34.mp4` und `w034.mp4` greifen alle.

### 2. Kader laden

```bash
python3 hcr2.py video roster
```

Ohne `--match` liefert das die aktiven PLTE-Spielerinnen mit ID, Name und Alias — die
Zuordnungstabelle für Schritt 4.

### 3. Frames lesen

Aufbau einer Zeile:

```
Platz | Punkt (online) | Flagge | Name | Kilometer
```

- Der grüne Punkt links neben der Flagge ist der Online-Status, eine Momentaufnahme —
  **nicht** übernehmen.
- Im Kopf steht die **Mitgliederzahl** (`Online: 9/49` → 49 Mitglieder) und rechts oben
  der **Truhenfortschritt** (`11031km / 11440km`). Beides notieren.
- **Die Restzeit unter dem Truhenfortschritt mitlesen** (`5h 15m`). Ist sie größer als
  null, war die Truhe beim Aufnehmen noch offen — die Kilometer sind dann ein
  Zwischenstand, nicht die Wochenleistung. Eintragen ist trotzdem in Ordnung, aber im
  Text sagen, wie viel Zeit noch offen war, damit der Wert einordbar bleibt. Für saubere
  Zahlen sollte die Aufnahme nach Ablauf der Truhe entstehen.
- Plätze lückenlos protokollieren. Die Liste zeigt 8–10 Zeilen und scrollt ~5 Plätze pro
  Frame; jeden Frame lesen ist hier meist nötig, jeden zweiten reicht selten.

### 4. Namen zuordnen

Dieselben Regeln wie bei [[match-video]]: über Kontext zuordnen, nicht über exakte
Textgleichheit. Häufige Fälle in diesem Team:

| Video | DB |
|---|---|
| `£@π` | `J@n` (675) |
| `PŁ\|J@n⟫` | `PL\|J@n` (486) |
| `PL💎Mr.Ĺ` | `PL Mr.L` (433) |
| `PL\|¹HP\|AL` | `PL\|1HP\|AL` (161) |
| `Tzóli🍀🦉` | `Tzoli` (453) |
| `SpeeÊd` | `SpeeEd` (702) |

**`J@n` (675) und `PL|J@n` (486) sind zwei verschiedene Personen** — beide erscheinen in
der Liste, beide getrennt zuordnen und beide Treffer prüfen.

Ist ein Name gar nicht im Kader, ist das ein Hinweis auf einen Kaderwechsel: erst
[[player-video]] laufen lassen, dann hier weitermachen.

### 5. Datei schreiben

`tmp/video/chest/<Jahr>/w<KW>/chest.json`:

```json
{
  "year": 2026,
  "week": 34,
  "team_total": 11031,
  "chest_goal": 11440,
  "member_count": 49,
  "players": [
    {"rank": 1, "name": "PL💎Mr.Ĺ", "km": 858, "pid": 433},
    {"rank": 49, "name": "Leo", "km": 13, "pid": 541}
  ]
}
```

`pid` ist Pflicht — die Zuordnung machst du, der Code rechnet nur. `name` dient der
Nachvollziehbarkeit und darf den Videonamen roh enthalten; anders als bei
[[player-video]] wird hier nichts umbenannt, also ist keine Transliteration nötig.

### 6. Übernehmen

```bash
python3 hcr2.py video chest apply --year 2026 --week 34 --dry-run
python3 hcr2.py video chest apply --year 2026 --week 34
```

Vorschau zeigen, **Bestätigung abwarten**, dann schreiben. Ein erneuter Lauf derselben
Woche überschreibt die Werte, verdoppelt sie also nicht.

## Die Vollständigkeitsprobe ist die Mitgliederzahl, nicht die Truhe

Das ist der wichtige Unterschied zu [[match-video]]:

- **Hart geprüft**: gelesene Zeilen == `member_count` aus dem Kopf. Stimmt das nicht,
  fehlt eine Zeile → zurück zu Schritt 3, **nicht** `--force`.
- **Nur gemeldet**: die Differenz zum Truhenfortschritt. Die Truhe zählt Kilometer von
  Spielerinnen weiter, die das Team seitdem verlassen haben, während die Liste nur
  aktuelle Mitglieder zeigt. In KW34 2026 waren das 207 km bei vollständig korrekt
  gelesenen Zeilen — eine Differenz ist also normal.

Wird die Differenz groß (grob: mehr als der größte Einzelwert), lohnt der Blick, ob
wirklich nur ein Abgang dahintersteckt.

## Danach

Prüfen lässt sich das Ergebnis mit:

```bash
python3 hcr2.py distance list --year 2026 --week 34
python3 hcr2.py distance weeks
```

Im Discord liest das Team es über `.km`, `.km <spielerin>` und `.km weeks`; der Schnitt
der letzten Wochen steht auch im Profil (`.profile`).

## Grenzen

- Schreibt in die DB dieses Checkouts. Vor dem Übernehmen einmal
  `python3 -c "from hcr2.db import connection; print(connection.DB_PATH)"` zeigen.
- Der Screen zeigt keinen Wochenbezug — welche Woche gemeint ist, steckt allein im
  Dateinamen. Bei Zweifeln nachfragen statt raten.
