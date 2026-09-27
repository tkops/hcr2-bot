---
name: match-video
description: Ergebnisse eines Team-Matches aus dem Standings-Video auslesen - beim Endstand als matchscore in die DB, beim Zwischenstand (Uhr läuft noch) als Bericht ohne Schreiben; danach das Siegerpodest-Bild und den Recap-Text nach Discord posten. Immer nutzen, wenn zu einem Match Ergebnisse eingetragen, ausgewertet oder importiert werden sollen und kein Excel-Sheet genannt ist - egal wie es formuliert ist ("/match-video 801", "Video auswerten", "Ergebnisse aus dem Video", "schreib die Daten für Match 801 in die DB", "trag Match 801 ein", "Match 801 auswerten", "neues Video ist hochgeladen", "Zwischenstand", "wer ist noch nicht gefahren", "wer kann sich noch steigern") - und ebenso, wenn nur gepostet werden soll ("Podest posten", "Siegerpodest", "Recap", "schreib was in den Teamchat", "Ergebnis ins Team posten").
---

# Match-Video auswerten

Liest den Stand eines Team-Matches aus dem Video und schreibt Score und Points
direkt nach `matchscore` — ohne Excel-Umweg.

Argument: die Match-ID.

**Zuerst entscheiden, welcher der beiden Modi gilt** — das steht im Videokopf, nicht im
Auftrag: läuft dort noch ein Countdown (`16 h 07 m`), ist es ein **Zwischenstand** →
[Modus Zwischenstand](#modus-zwischenstand-die-uhr-läuft-noch), Schritte 1–5 gelten
gleich, Schritt 6 und 7 sind andere. Kein Countdown = Endstand = der Ablauf unten.
Im Zweifel nachfragen: eine Zwischenlesung als Endergebnis zu schreiben, macht aus
„noch nicht gefahren" ein „unentschuldigt gefehlt".

- **Fehlt sie**, `python3 hcr2.py match list` zeigen und nachfragen. Nicht raten — das
  Video landet sonst auf dem falschen Match.
- **Gibt es das Match noch nicht** (`❌ No match found.`), nicht selbst anlegen: melden
  und `python3 hcr2.py match add ...` vorschlagen. Gegnername und Event stehen im
  Videokopf. **Nach dem Datum nicht fragen** — ohne `--start` leitet `match add` es selbst
  ab (letztes Match des Monats + 2 Tage, sonst Monatserster), und das ist das richtige.
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

### 10. Siegerpodest posten

Nach jedem eingetragenen Match geht das Siegerpodest in den Podest-Kanal. Das ist ein
**eigener Bildschirm** in derselben Aufnahme, nicht der Endergebnis-Screen: oben Event,
beide Teamnamen mit Summen und das `WINNER!`-Abzeichen, darunter die Top 3 **beider**
Mannschaften nebeneinander, unten die Figuren auf ihren Podesten und
`TOUCH TO CONTINUE`.

Er steht **zwischen** dem ersten Aufschlagen der Endergebnisliste und den
Belohnungsbildschirmen und ist nur wenige Sekunden lang zu sehen. Ihn im Kontaktbogen
zu suchen ist billiger, als Frames einzeln zu öffnen:

```bash
ffmpeg -i "tmp/video/<id>/frames/frame_%04d.jpg" -vf "scale=320:-2,tile=5x8" -frames:v 1 kontakt.jpg
```

(Pfad zu ffmpeg über `resolve_ffmpeg()`, siehe Schritt 1.) Der Podest-Frame ist im
Kontaktbogen sofort zu erkennen. Dann genau diesen Zeitpunkt in voller Auflösung
nachschneiden — die Frames aus Schritt 1 sind zum Lesen heruntergerechnet und für
einen Post zu grob:

```bash
python3 hcr2.py video frames --match <id> --start 00:00:09 --duration 1 --fps 1 --width 0
```

Das **überschreibt die Frames aus Schritt 1**, also erst machen, wenn die Lesung steht.

- **Das Bild vor dem Posten mit dem Read-Tool ansehen.** Baut sich das Podest noch auf
  (Figuren fehlen, Countdown statt `TOUCH TO CONTINUE`), ist es eine Sekunde zu früh.
- **Nicht zuschneiden, außer der Nutzer will es.** `--crop` rechnet in den Pixeln der
  Aufnahme, und die hängen am Gerät (hier 1170×2532, hochkant gedreht). Ein fester
  Crop stimmt beim nächsten Handy nicht mehr.

Posten:

```bash
python3 scripts/post_discord.py --mode <dev|prod> --channel podium \
    --image tmp/video/<id>/frames/frame_0001.jpg \
    --skip-if-image-since <matchende> --dry-run
```

(Nach dem Nachschneiden oben liegt dort genau ein Frame, deshalb `frame_0001.jpg`.)

**`--skip-if-image-since` gehört immer dazu.** Das Podest postet meistens schon von
Hand, wer die Aufnahme gemacht hat; ein zweites Bild ist nur Rauschen. Mit dem
Matchende schaut das Skript vorher in den Kanal und meldet
`⏭️ … already posted a picture …`, wenn dort seit dem Ende schon eines liegt — dann
wird **nichts** gesendet, und das ist kein Fehler. **Sieh dir das gefundene Bild
trotzdem an** (`scripts/read_discord.py --channel <podium-id> --json` liefert die
Anhang-URL): stehen dort Event und Gegner dieses Matches?

**Matchende = `Start` aus `match show --id <id>` + 2 Tage**, nicht das Startdatum. Ein
Match läuft zwei Tage, das Podest entsteht erst am Ende — und das Ende des
*vorigen* Matches ist genau der Start dieses. Mit dem Startdatum fällt das Podest
des Vormatchs ins Fenster und dieses wird fälschlich übersprungen (so geschehen bei
Match 822: das Bild vom 25.09. war Thrust Issues/Match 821). Die Beschriftung der
Hand-Posts („25. September 2026") ist der Tag des Endes, nicht des Starts. Kann es den Verlauf nicht lesen
(fehlende Berechtigung), bricht es mit ❌ ab statt zu posten: „konnte nicht nachsehen"
ist kein „da ist keins".

**`--mode` muss zum Checkout passen**, in dem du gerade arbeitest — dev-Checkout →
`--mode dev`. dev und prod sind verschiedene Server, und ein Post lässt sich nicht
zurückholen. Erst `--dry-run` zeigen, das Bild zeigen, **auf Bestätigung warten**, dann
ohne `--dry-run` senden. Eine Bildunterschrift ist optional (`--text`), üblich ist keine
— der Recap-Text aus Schritt 11 steht ohnehin woanders.

### 11. Recap in den Teamchat

In den internen Teamchat geht ein kurzer, **positiver** Text zum Match. Die Zahlen dafür
kommen aus der DB, nicht aus dem Video und nicht aus dem Gedächtnis:

```bash
python3 hcr2.py match recap --id <id>
```

Das Faktenblatt (englisch) liefert Ergebnis und Abstand, Teilnahme, das Treppchen samt
der Angabe **wie oft die drei sonst dort stehen**, Steigerungen gegen die eigene Form
(das Tempo des ganzen Teams ist herausgerechnet), persönliche Bestleistungen, den
Verlauf des Team-Events und frühere Begegnungen mit dem Gegner. `--json` gibt dasselbe
maschinenlesbar.

**Den Text schreibst du, nicht der Befehl** — er soll sich jedes Mal anders lesen. Was
dabei gilt:

- **Nur was im Faktenblatt steht.** Keine Zahl schätzen, keine Steigerung behaupten, die
  dort nicht auftaucht. „Alle sind gefahren" nur, wenn das Blatt es sagt.
- **Keine Namen von Fehlenden, keine Kritik, kein „leider".** Der Kanal ist der
  Teamchat; wer nicht gefahren ist, wird dort nicht benannt — dafür gibt es
  `stats broom` im Leader-Channel. Auch bei einer Niederlage bleibt der Ton positiv:
  knapper Ausgang, starke Einzelleistungen, der Verlauf im Event.
- **Das Treppchen kommt vor, aber gewichtet.** Wer selten oder zum ersten Mal oben
  steht (`<- say this`), bekommt den eigenen Satz — steht dabei `match N for her`, ist
  *das* die Geschichte („Platz 3 in ihrem vierten Match"). Die anderen beiden werden mit
  Namen und Score genannt, mehr nicht. Das ist der Kern des Postings: Lob wird wertlos,
  wenn es jedes Mal dieselbe Person trifft.
- **Kein Geschlecht zuschreiben.** Das Team heißt Power Ladys, es fahren aber auch
  Männer mit, und in der DB steht dazu nichts — jedes „sie" und jedes „ihr" wäre
  geraten. Das Faktenblatt sagt deshalb „the player" und „their", und im Deutschen
  hängt es an drei Stellen:
  - **Possessivpronomen**: nicht „ihren Schnitt", sondern „den eigenen Schnitt"; nicht
    „in ihrem vierten Match", sondern „erst das vierte Match".
  - **Personalpronomen**: den Namen wiederholen oder den Satz umbauen — „Der Moment des
    Abends gehört X" statt „sie hat …".
  - **Bezeichnungen**: kein „die Neue", „der Neuzugang", „die Fahrerin"; „neu im Team"
    oder „ganz vorne" sagt dasselbe.

  „Ladys" bleibt als Kurzform des **Teamnamens** erlaubt und meint alle — so redet die
  Leitung auch im Channel (dieselbe Regel wie in `stats broom`).
- **Keine Etiketten für Personen.** „Das vertraute Duo", „die üblichen Verdächtigen",
  „wie immer ganz oben" — solche Wendungen beschreiben nicht die Leistung, sondern
  hängen jemandem ein Schild um, und das kann im Teamchat als Spitze ankommen. `regular`
  im Faktenblatt ist eine Aussage über die *Liste*, keine Vokabel für den Text: Name,
  Zahl, fertig. Dasselbe gilt für Vergleiche zwischen zwei Ladys.
- **Eine bis drei Steigerungen**, mit absoluten Scores statt Prozenten. Steht bei einer
  ein großer Abstand unter dem Match-Median dabei, ist es eine Erholung und keine
  Spitzenleistung — dann entsprechend formulieren.
- **Alte Zahlen nur, wenn sie etwas sagen.** Eine Bestleistung, eine Serie im Event, ein
  Gegner, gegen den man zuletzt verloren hatte. Sonst weglassen. Score-**Summen** nur
  innerhalb desselben Team-Events vergleichen — andere Strecken, andere Größenordnung.
- **Kurz und abwechselnd.** Vier bis acht Sätze, unter 1200 Zeichen, kein Codeblock
  (wird am Handy gelesen). Nicht jedes Mal mit dem Ergebnis anfangen — mal mit einer
  Person, mal mit dem Event, mal mit dem Endspurt.

Text in eine Datei schreiben und von dort posten, damit der Nutzer ihn vorher liest:

```bash
python3 scripts/post_discord.py --mode <dev|prod> --channel teamchat \
    --file tmp/video/<id>/recap.md --dry-run
```

Wieder: Text zeigen, **auf Bestätigung warten**, dann ohne `--dry-run`. Wenn der Nutzer
etwas anders haben will, wird der Text geändert und nicht nachträglich ein zweiter Post
hinterhergeschickt.

## Modus Zwischenstand (die Uhr läuft noch)

Einstieg auch direkt über [[zwischenstand]] — das Skill enthält nur die Weiche und
verweist für alles Weitere hierher.

Zweck: **jetzt** noch etwas bewegen können — wer ist noch nicht gefahren, wer hängt
weit hinter ihrem eigenen Score aus einem früheren Match desselben Events, und wen kann
man loben. Es wird **nichts** in die DB geschrieben.

Schritte 1–5 sind identisch (Frames, Kader, Lesen, Zuordnen, Nicht-Gefahrene). Dazu:

- Das Video heißt hier üblicherweise `<id>-tmp.mp4` und liegt im selben S-Ordner.
  `--file` setzen, sonst greift der Kandidat, den `select_candidate` für den neuesten
  hält.
- **Gibt es das Match noch nicht**, geht `video frames` trotzdem: `--season <n>` sagt,
  in welchem Ordner gesucht wird. Erst aus dem Videokopf kommen Event und Gegner, dann
  `match add` vorschlagen — nur Match, **keine Ergebnisse**, und **ohne `--start`**:
  das Datum leitet sich selbst ab, eine Rückfrage danach ist überflüssig.
- Eine Zeile, die sich **nicht** zuordnen lässt (Name im Video, nicht im Kader), mit
  `"pid": 0` und `name` aufnehmen statt weglassen. Sie erscheint dann als Warnung; wird
  sie weggelassen, landet die Spielerin, zu der sie gehört, fälschlich unter „noch nicht
  gefahren". Ob Umbenennung oder Neuzugang, klärt [[player-video]] oder die Teamleitung.

### 6b. Lesung schreiben

Gleiche Datei wie beim Endstand, nach `tmp/video/<id>/interim.json`, plus **ein Feld
mehr**:

```json
{"match_id": 810, "time_left": "16h07m", "score_ladys": 589, "...": "..."}
```

`time_left` ist der Countdown aus dem Kopf und **Pflicht**: er ist der Beweis, dass das
Match noch lief. `video apply` verweigert eine Lesung mit `time_left` als Ergebnis, und
`video interim` fragt ohne ihn nach, ob das nicht doch der Endstand war.

Die Punktsumme muss auch hier der Kopfsumme entsprechen — an einem echten Zwischenstand
geprüft: 46 gefahrene Zeilen ergaben exakt die 589 aus dem Kopf. Stimmt sie nicht, fehlt
eine Zeile.

### 7b. Bericht erzeugen

```bash
python3 hcr2.py video interim --match <id> --file tmp/video/<id>/interim.json
```

Der Bericht ist deutsch, postfertig und **bewusst kurz** (~800 Zeichen): noch nicht
gefahren, „wirkt abgebrochen", „Luft nach oben", „Steigerungen", „Neu im Team". Die
Wertungslisten zeigen **absolute Scores** statt Prozenten — die Leitung soll handeln,
nicht rechnen — und sind gekürzt: „wirkt abgebrochen" auf **drei Namen** plus Restzähler,
„Steigerungen" auf drei ohne, **„Luft nach oben" auf fünf und ohne Restzähler**, weil das
die Liste ist, auf die die Leitung tatsächlich zugeht. „Neu im Team" listet **alle**
in ihren ersten drei Matches, gefahren oder nicht.

- **Ab dem zweiten Match eines Events** ist der Maßstab der eigene Score aus dem ersten
  Match des Events — gleiche Strecken. Im ersten Match gibt es den nicht, dann zählt der
  eigene Schnitt, und sinnvoll sind dort nur „nicht gefahren" und „wirkt abgebrochen".
- Jede Prozentzahl ist **gegen das Tempo des Teams** gerechnet, nicht gegen 100 %.
  Deshalb heißt „67 %" nicht „schlechter als früher", sondern „weiter zurück als der
  Rest gerade steht" — mitten im Match kann das auch heißen: sie fährt noch.
- **Nicht als Vorwurf weitergeben.** „Noch nicht gefahren" ist eine Erinnerung, solange
  die Uhr läuft.

Mit `--out <pfad>` landet derselbe Text in einer Datei; posten mit
`scripts/post_discord.py --mode prod --channel birthday --file <pfad>` (Leader-Chat).

### 8b. Video wieder wegräumen

Die `-tmp`-Aufnahme ist Wegwerfware:

```bash
python3 hcr2.py video interim --match <id> --cleanup [--video <name>]
```

Löscht sie auf Nextcloud und die lokalen Frames. Eine Datei, die exakt `<id>.mp4` heißt,
wird **nicht** gelöscht — das ist die Endstandsaufnahme.

Das Aufräumen hängt **nicht** am Lesen: der Befehl geht auch ohne `interim.json` durch,
also auch dann, wenn du es Tage später nachholst. Nur wenn du eine Lesung mit `--file`
benennst, muss sie da sein.

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
