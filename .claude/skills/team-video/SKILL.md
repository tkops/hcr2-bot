---
name: team-video
description: Die PLTE-Spielerliste aus dem Team-Infos-Video (Ladys.mp4) aktualisieren - Garage Power, Namen, Zu- und Abgänge. Nutzen, wenn der Kader abgeglichen werden soll, egal wie formuliert ("/team-video", "Ladys.mp4 ist hochgeladen", "Kader aktualisieren", "neue Spielerliste", "Garage Power aktualisieren", "wer ist neu im Team"). Nicht verwechseln mit [[match-video]], das die Ergebnisse eines einzelnen Matches einträgt.
---

# Kader aus dem Team-Video aktualisieren

Liest den Team-Infos-Screen aus `Ladys.mp4` und gleicht die aktive PLTE-Liste damit ab:
Garage Power, Namen, neue Mitglieder, Abgänge.

Die eine Sache, die du **nie allein entscheidest**: ob ein unbekannter Name eine neue
Spielerin ist oder jemand, der schon einmal da war. In der DB stehen über 600 ehemalige
Spielerinnen. Bei jedem Zugang fragst du nach — siehe Schritt 5.

## Ablauf

### 1. Frames erzeugen

```bash
python3 hcr2.py video player frames
```

Holt `Ladys.mp4` aus dem Nextcloud-Basisordner (dort, wo auch `Ladys.xlsx` liegt) nach
`tmp/video/team/` und schneidet mit 1 fps. Bei `❌ ffmpeg not found` gilt derselbe
Hinweis wie bei [[match-video]]: `pip3 install --user imageio-ffmpeg`.

### 2. Frames lesen

`tmp/video/team/frames/frame_*.jpg` der Reihe nach. Aufbau einer Zeile:

```
Platz | Avatar | Flagge + Name | Online-Status | Rolle | Helm | ⚡ Garage Power
```

- **Garage Power** ist die Zahl hinter dem gelben Blitz, rechts außen (z. B. `15 354`).
- **Rolle**: `ANFÜHRER` oder `2. ANFÜHRER`, sonst leer.
- Der Online-Status (`OFFLINE`, `HAUPTMENÜ`, `TEAM-EVENT`) ist eine Momentaufnahme und
  wird **nicht** übernommen.
- Im Kopf steht die **Mitgliederzahl** (`49/50`). Die ist die Vollständigkeitsprobe.

Plätze lückenlos protokollieren. Der Screen zeigt 5–7 Zeilen, die Liste scrollt ~2,7
Plätze pro Frame — jeden zweiten Frame lesen reicht meist, aber die Platznummern
müssen am Ende ohne Lücke von 1 bis zum letzten durchlaufen.

### 3. Namen transliterieren

Namen kommen **so in die Datei, wie sie in der DB stehen sollen** — auf einer deutschen
Tastatur eingebbar. Umlaute und ß bleiben, alles andere wird ersetzt:

| Video | Datei |
|---|---|
| `£@π` | `J@n` |
| `PŁ\|J@n⟫` | `PL\|J@n` |
| `PL💎Mr.Ĺ` | `PL Mr.L` |
| `Tzóli🍀🦉` | `Tzoli` |
| `Fox 🦊` | `Fox` |
| `Chris🇺🇦` | `Chris` |
| `PL\|¹HP\|AL` | `PL\|1HP\|AL` |

Den rohen Videonamen in `video_name` mitschreiben. `video player apply` **weist die
Datei ab**, wenn ein Name nicht tippbare Zeichen enthält — das ist kein Vorschlag,
sondern eine Abbruchbedingung.

Orientiere dich beim Transliterieren am bestehenden DB-Namen: steht dort schon `Tzoli`,
ist das die richtige Schreibweise, nicht deine eigene Erfindung.

### 4. Datei schreiben

`tmp/video/team/roster.json`:

```json
{
  "team": "Power-Ladys💎TE",
  "member_count": 49,
  "players": [
    {"rank": 1, "name": "G|Turbo|PL", "garage_power": 15354, "leader": 1},
    {"rank": 39, "name": "J@n", "video_name": "£@π", "garage_power": 10933, "pid": 675}
  ]
}
```

`pid` nur setzen, wenn der Name so weit vom DB-Namen weg ist, dass der Abgleich ihn
nicht findet. Sonst weglassen — der Code ordnet über den normalisierten Namen zu.

### 5. Zugänge klären — hier fragst du

```bash
python3 hcr2.py video player apply --dry-run
```

Bleibt ein Name übrig, meldet der Befehl ihn als offene Entscheidung und zeigt
Kandidaten. **Ganz oben stehen immer die Spielerinnen, die im Video fehlen** — ein
Abgang plus ein Zugang ist meistens dieselbe Person unter neuem Namen, und nicht zwei
unabhängige Vorgänge.

Für **jeden** Zugang den Nutzer fragen, mit dem, was du weißt:

- der neue Name und seine Garage Power,
- wer im Video fehlt (Name, ID, GP) — der wahrscheinlichste Treffer,
- die Namensähnlichkeit und ob die Garage Power zusammenpasst,
- dein eigener Verdacht, aber als Frage, nicht als Feststellung.

Der Nutzer kennt die Leute; du kennst nur die Zahlen. Bei Unsicherheit hilft
`python3 hcr2.py player grep <name>`. Ist eine Zuordnung geklärt, in die Zeile
schreiben:

```json
{"name": "Bisa", "garage_power": 10401, "reactivate": 542}   // war schon da
{"name": "Mischa", "garage_power": 10891, "new": true}       // wirklich neu
```

`reactivate` auf eine **aktive** Spielerin ist erlaubt und der Normalfall bei einer
Umbenennung: daraus wird eine Umbenennung plus GP-Update, und die Deaktivierung
entfällt.

### 6. Übernehmen

Erst wenn keine Entscheidung mehr offen ist:

```bash
python3 hcr2.py video player apply --dry-run    # Plan zeigen
python3 hcr2.py video player apply              # nach Bestätigung
```

Der Plan zeigt `ADD`, `REACTIVATE`, `DEACTIVATE`, `RENAME`, `GP`. **Immer erst zeigen,
Bestätigung abwarten, dann schreiben.** Besonders die Deaktivierungen vorlesen — das
sind die Änderungen, die jemand aus dem Team nehmen.

## Was der Code abfängt

| Prüfung | Wirkung |
|---|---|
| Mitgliederzahl aus dem Kopf ≠ gelesene Zeilen | Abbruch — eine Zeile fehlt |
| Name mit nicht tippbaren Zeichen | Abbruch — erst transliterieren |
| Garage Power ≤ 0 oder > 50000 | Abbruch |
| Mehr als ein Viertel des Kaders würde deaktiviert | Abbruch — das ist eine unvollständige Lesung, kein Massenaustritt |
| Offener Zugang ohne `new`/`reactivate` | Abbruch |
| Garage Power gesunken | nur Hinweis — GP wächst normalerweise |
| Anführer-Rolle weicht ab | nur Hinweis, wird **nicht** geschrieben (`player edit --leader`) |

`--force` hebt die ersten Abbrüche zu Warnungen herab. Nur benutzen, wenn der Kopf
wirklich unlesbar war — nie, um eine unvollständige Lesung durchzudrücken.

## Grenzen

- Schreibt in die DB dieses Checkouts. Vor dem Übernehmen einmal
  `python3 -c "from hcr2.db import connection; print(connection.DB_PATH)"` zeigen.
- Der Screen zeigt keine Geburtstage, Discord-Namen oder Fahrzeuge — die bleiben
  unangetastet, dafür ist weiterhin `sheet player import` da.
- Ein Alias wird für neue Spielerinnen automatisch erzeugt; er steht danach im Ergebnis.
