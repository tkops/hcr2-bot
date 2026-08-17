---
name: match-video
description: Ergebnisse eines Team-Matches aus dem FINAL-STANDINGS-Video auslesen und als matchscore in die DB schreiben. Immer nutzen, wenn zu einem Match Ergebnisse eingetragen, ausgewertet oder importiert werden sollen und kein Excel-Sheet genannt ist - egal wie es formuliert ist ("/match-video 801", "Video auswerten", "Ergebnisse aus dem Video", "schreib die Daten für Match 801 in die DB", "trag Match 801 ein", "Match 801 auswerten", "neues Video ist hochgeladen").
---

# Match-Video auswerten

Liest den Endstand eines Team-Matches aus dem Video und schreibt Score und Points
direkt nach `matchscore` — ohne Excel-Umweg.

Argument: die Match-ID.

- **Fehlt sie**, `python3 hcr2.py match list` zeigen und nachfragen. Nicht raten — das
  Video landet sonst auf dem falschen Match.
- **Gibt es das Match noch nicht** (`❌ No match found.`), nicht selbst anlegen: melden
  und `python3 hcr2.py match add ...` vorschlagen. Der Gegnername und das Event stehen im
  Videokopf, das Datum aber nicht.
- Ist im Verzeichnis eine `results.json` von einem früheren Durchgang, wird sie bei
  Schritt 6 überschrieben — vorher kurz erwähnen, falls sie fremde Zahlen enthält.

## Ablauf

### 1. Frames erzeugen

```bash
python3 hcr2.py video frames --match <id>
```

Das lädt das Video aus `Power-Ladys-Scores/Team-Event/S<season>/` (dort liegen auch die
Match-Sheets) nach `tmp/video/<id>/` und schneidet es mit 1 fps in Frames.

- **⚠️ zum Dateinamen ernst nehmen.** Heißt die Datei nicht `<id>.mp4`, hat der Befehl
  nur geraten. Vor dem Weitermachen mit `python3 hcr2.py video list --match <id>`
  prüfen und ggf. `--file <name>` setzen.
- **❌ ffmpeg not found** → `pip3 install --user imageio-ffmpeg` (bringt ein statisches
  ffmpeg mit, kein root nötig). Ohne ffmpeg geht dieser Weg nicht.

### 2. Kader laden

```bash
python3 hcr2.py video roster --match <id>
```

Gibt ID, Name und Alias aller aktiven PLTE-Spielerinnen aus. Das ist die
Zuordnungstabelle für Schritt 3.

### 3. Frames lesen

Frames der Reihe nach mit dem Read-Tool ansehen (`tmp/video/<id>/frames/frame_*.jpg`),
mehrere pro Durchgang.

**Aufbau einer Zeile**, von links nach rechts:

```
Points | Platz | Flagge + Spielername | Pokal-Icon | Score
```

- **Points** = kleine Zahl ganz links (Turnierpunkte, z. B. 262)
- **Score** = große Zahl ganz rechts (Fahrpunkte, z. B. 43 635)
- **Zeilenfarbe ist maßgeblich, nicht die Flagge**: gelb = Power-Ladys, blau = Gegner.
  Unsere Leute haben Flaggen aus aller Welt, im Gegnerteam sind ebenfalls deutsche dabei.
- Im **Kopfbereich** stehen die beiden Teamsummen und **beide Teamnamen**: links
  Power-Ladys, rechts der Gegner. Summen als `score_ladys` / `score_opponent` notieren,
  den Gegnernamen als `opponent` — genau so, wie er im Video steht.
- Nur unsere Spielerinnen werden erfasst, Gegner nicht.

**Platznummern lückenlos protokollieren**, Platz 1 bis Ende. Fehlt ein Bereich, gezielt
nachschneiden statt raten:

```bash
python3 hcr2.py video frames --match <id> --start 00:00:42 --duration 6 --fps 3
```

Sind die letzten Frames identisch, ist das Listenende erreicht.

**Zu klein zum Lesen?** Ranglistenbereich zuschneiden und in voller Auflösung ziehen
(`--width 0` überspringt das Skalieren):

```bash
python3 hcr2.py video frames --match <id> --crop 1400:1600:1200:400 --width 0
```

### 4. Namen zuordnen — der fehleranfälligste Teil

Die Namen im Video weichen regelmäßig von der DB ab:

- **Umbenennungen sind normal.** Über Kontext zuordnen (Flagge, gelbe Zeile, plausibler
  Platz), nicht über exakte Textgleichheit.
- **Spieler-ID 50 („-7-")** benennt sich besonders oft um. Konstante: immer eine 7 im
  Namen, meist am Ende (z. B. „PAX - 7"). Diese Zuordnung ist verlässlich.
- **Sonderzeichen** sind in der DB durch Standardzeichen ersetzt, weil sie auf einer
  deutschen Tastatur eingebbar sein müssen. `@` bleibt, alles Exotischere ist
  transliteriert: £ → L/J, π → n, Ł → L, Ĺ → L. Ein Videoname „£@π" ist also der
  DB-Eintrag „J@n". Solche Namen im Vollauflösungs-Crop lesen, nicht im skalierten Frame.
- **Ähnliche Namen im selben Kader** (z. B. „J@n" ID 675 und „PL|J@n" ID 486) getrennt
  zuordnen und beide Treffer explizit prüfen.

Unsichere Zuordnungen in `note` festhalten — sie erscheinen in der Vorschautabelle.

### 5. Nicht gefahrene Spielerinnen

- **Gar nicht in der Rangliste**: `score` 0, `points` 0. Kommt regelmäßig vor, ist kein
  Fehler — nicht lange suchen, eintragen und in der Antwort erwähnen.
- **In der Liste, aber Score „--"**: eingeloggt, aber nicht gefahren → `score` 0,
  `points` 0, `checkin` 1.

`absent` weglassen, wenn es dafür keinen konkreten Beleg gibt: dann leitet
`matchscore` es aus den Abwesenheitsdaten der Spielerin ab. Nur setzen, wenn das Video
oder der Auftrag es hergibt.

### 6. Ergebnisse schreiben

`tmp/video/<id>/results.json`:

```json
{
  "match_id": 799,
  "event": "Nitro Strings Attached",
  "opponent": "TEAM CANADA",
  "score_ladys": 1508,
  "score_opponent": 3010,
  "entries": [
    {"pid": 89, "rank": 1, "name": "G|Turbo|PL", "score": 43635, "points": 262},
    {"pid": 50, "score": 0, "points": 0, "checkin": 1, "note": "hieß im Video PAX - 7"}
  ]
}
```

Alle Kaderspielerinnen aufnehmen, auch die mit 0/0.

**`name` ist wichtig und wird oft vergessen:** dort kommt der Name **wie im Video**
hinein, nicht der aus der DB — inklusive Sonderzeichen und Emoji. Genau aus dem
Vergleich der beiden baut `video apply` seine Umbenennungs-Vorschläge. Ohne `name`
fällt diese Prüfung still aus. `rank` ist optional, hilft aber beim Nachschlagen.

### 7. Gegenprobe und Übernahme

```bash
python3 hcr2.py video apply --match <id> --dry-run
```

`apply` schreibt nur, wenn **beide** Proben halten:

1. **Punktsumme** — die Summe der Points muss exakt der Power-Ladys-Teamsumme aus dem
   Videokopf entsprechen. Schlägt das fehl, ist eine Zeile übersehen oder falsch gelesen
   → zurück zu Schritt 3.
2. **Gegnername** — `opponent` aus dem Video muss zum Gegner des Matches passen.
   Groß-/Kleinschreibung, Leerzeichen, Akzente und Emoji werden dabei ignoriert, ein im
   Video abgeschnittener Name ebenfalls toleriert. Schlägt es trotzdem fehl, ist es das
   falsche Video oder die falsche Match-ID → **nicht** überschreiben, sondern klären.

`--force` degradiert beide Proben zu Warnungen. Nur benutzen, wenn Kopfsumme oder
Teamname wirklich unlesbar waren — und dann im Text sagen, welche Probe ausgefallen ist.

Die Vorschautabelle und alle ⚠️-Zeilen dem Nutzer zeigen, **auf Bestätigung warten**,
dann erst:

```bash
python3 hcr2.py video apply --match <id>
```

### 8. Auffälligkeiten durchgehen

Unter der Tabelle steht ein `🔎`-Block mit allem, was nicht zusammenpasst. Der blockiert
nichts — er ist die eigentliche Rückmeldung an den Nutzer. **Nie einfach durchwinken**,
sondern jeden Punkt einordnen:

| Art | Was er bedeutet | Was du tun sollst |
|---|---|---|
| `[Opponent]` / `[Name]` | Video und DB schreiben denselben Namen anders | Vorgeschlagenen Befehl zeigen, **nicht** selbst ausführen. Bei Sonderzeichen erst transliterieren (£ → J, π → n) und den Befehl entsprechend anpassen. |
| `[Not in standings]` | Kaderspielerin ist nicht gefahren und nicht als abwesend eingetragen | Hervorheben, besonders bei jemandem mit hohem letzten Score — das ist oft der Hinweis auf einen Kaderwechsel oder eine vergessene Abwesenheit. |
| `[Away]` | Nicht gefahren, aber als abwesend eingetragen | Nur erwähnen, das ist der Normalfall. |
| `[Joined late]` | Kaderspielerin kam erst nach dem Matchstart ins Team und konnte gar nicht teilnehmen | Als erklärt abhaken. **Keine** 0/0-Zeile für sie schreiben — ab dem Folgematch wird Teilnahme aber erwartet. |
| `[Score]` | Score weicht stark vom eigenen Schnitt ab, gemessen an der Verschiebung des ganzen Teams | Prüfen, ob du dich verlesen hast: die Zeile im Frame nochmal ansehen. Erst wenn die Zahl stimmt, ist es ein echter Einbruch. |

Was der Block **nicht** kann: eine Zeile finden, die du komplett übersehen hast — dafür
ist die Punktsummen-Probe da. Und eine falsche Zuordnung zwischen zwei Kaderspielerinnen
bemerkt er nur, wenn dabei ein Score-Ausreißer entsteht.

### 9. Rückmeldung

Kurz auflisten: unsichere Zuordnungen, 0/0-Fälle, und ob beide Gegenproben sauber waren.
Danach die Auffälligkeiten aus Schritt 8 mit deiner Einschätzung.

## Grenzen

- **Welche DB getroffen wird, hängt am Checkout.** `hcr2/db/connection.py` nimmt das
  Nachbarverzeichnis `../hcr2-db/hcr2.db`. Im dev-Checkout ist das die Spielwiese, im
  prod-Checkout (`/home/nextcloud/hcr2-bot`) die **echte Team-Datenbank**. Vor dem Schreiben
  einmal `python3 -c "from hcr2.db import connection; print(connection.DB_PATH)"` zeigen,
  damit der Nutzer sieht, wohin es geht.
- **dev-Daten sind flüchtig.** Der Owner spielt prod → dev zurück; alles, was in dev
  eingetragen wurde, ist danach weg. Eine Auswertung in dev ist deshalb nur dann etwas
  wert, wenn die `results.json` anschließend auch in prod angewandt wird — die Datei ist
  umgebungsunabhängig, `video apply --file <pfad>` braucht kein Modell mehr.
- Passen die Spieler-IDs nicht (dev älter als prod, neue Mitglieder fehlen), melden statt
  raten — dann ist der dev-Stand zu alt für diese Auswertung.
- Das Video bleibt in `tmp/video/<id>/` liegen (gitignored) und wird auf Nextcloud
  **nicht** gelöscht — anders als beim `sheet player import`.
