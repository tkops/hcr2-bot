# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from the repo root — nothing is pip-installed, and `hcr2/` imports the
top-level `modules` and `version` modules, so the repo root has to be on `sys.path` (i.e. be the CWD).

```bash
python3 -m unittest discover -v                      # full suite (~126 tests)
python3 -m unittest tests.test_players               # one test module
python3 -m unittest tests.test_players.PlayerTests.test_player_repository_adds_player_and_checks_aliases
python3 -m compileall -q modules hcr2 tests          # cheap syntax gate used during refactors

python3 -m hcr2 <entity> <command> [flags]           # preferred CLI entry point
python3 hcr2.py <entity> <command> [flags]           # legacy-compatible entry point
python3 migrate_db.py [--db /path/to/hcr2.db]        # apply SQL migrations
python3 bot.py dev | python3 bot.py prod             # Discord bot (needs secrets_config.py)
python3 scripts/bump_version.py patch "Changelog text"
python3 scripts/post_discord.py --mode prod --channel admin --file note.md  # manual post
source completions/hcr2.bash                         # bash completion
```

There is no linter or formatter configured.

## Architecture

Three consumers sit on top of one SQLite database:

1. **CLI** — `hcr2.py` / `python3 -m hcr2` → `hcr2/cli/app.py`.
2. **Discord bot** — `bot.py` does *not* import the package. It shells out with
   `subprocess.run(["python3", "hcr2.py", ...])` and parses the CLI's stdout with regexes
   (`ID_LINE_RE`, `NAME_LINE_RE`, `BIRTHDAY_IDS_RE`). **Changing CLI output format can break the bot** —
   `tests/test_bot_contract.py` pins the formats those regexes depend on, so run it after touching
   `hcr2/output/`. Bot commands are dot-prefixed (`.p`, `.m`, `.stats`); `PUBLIC_COMMANDS` gates what
   non-leaders may run. `run_hcr2` returns a `CliResult` — a `str` subclass carrying `ok` from the
   exit code — so the 52 call sites keep working unchanged while `_output_is_error` can trust the
   exit code instead of searching the text for words like "invalid".

   `scripts/post_discord.py` goes the other way: the bot only ever writes as a reaction to a
   command, so an announcement needs this. It reads `secrets_config.CONFIG` for token and channel
   ids, so `--channel user|admin|birthday` means exactly what it means in `bot.py`. `--mode` is
   required (dev and prod are different servers, and a post cannot be un-sent), `--dry-run` shows
   what would go out, `--split` cuts on line boundaries past the 2000-character limit. `birthday`
   is the one channel the bot posts to but takes **no** commands in — `on_message` listens only in
   `CHANNEL_IDS` and `ADMIN_CHANNEL_IDS`, so a leader command typed under such a post does nothing.

3. **One-off maintenance scripts** at the root (`import_match.py`, `import_teamevent.py`,
   `import_player.py`, `import_matchscores.py`, `import_flags.py`, `find_teamevent.py`,
   `backup_schema.py`, `catxls.py`). These predate the package: they hardcode
   `DB_PATH = "../hcr2-db/hcr2.db"` and talk to sqlite3 directly. Do not treat them as part of the
   layered architecture.

### CLI dispatch

`hcr2/cli/registry.py` holds `ENTITY_SPECS` — the single list of top-level entities
(`vehicle`, `player`, `teamevent`, `season`, `match`, `matchscore`, `stats`, `sheet`, `video`,
`distance`, `donations`, `version`), each mapping to a `modules/<entity>.py` that exposes `handle_command(cmd, args)`
and `print_help()`. `hcr2/cli/app.py` registers each spec both as a Typer command and in a hand-rolled
`CliApp.dispatch`; `_should_use_legacy_dispatch` routes bare/`help`/unknown argv to the hand-rolled
path and everything else through Typer with `allow_extra_args`/`ignore_unknown_options` — so Typer
provides only completion and the entity boundary, never per-command argument parsing.
Adding an entity means: new `modules/<entity>.py` + one `EntitySpec` entry.

### Layering (ongoing refactor)

An incremental migration is moving logic out of `modules/`:

```
modules/<entity>.py     CLI adapter: argv parsing, USAGE_* strings, Usage prints only
hcr2/services/          business logic, validation, orchestration; returns result dataclasses
hcr2/repositories/      all SQL; returns model dataclasses
hcr2/models/            frozen dataclasses per domain row/detail shape
hcr2/output/            every user-facing print (tables, statuses, errors, ASCII plots)
hcr2/exporters/excel.py openpyxl workbook creation and reading
hcr2/integrations/      Nextcloud/WebDAV
hcr2/db/                connection + migration runner
```

Cross-cutting conventions:

- **Errors are the ❌ prefix, and the exit code follows from it.** `main()` watches stdout and exits
  1 when any line starts with ❌ (`hcr2/output/status.py`); code failing without printing can call
  `status.mark_failure()`. So a new error path only needs to print like the others.
- **Timestamps have two conventions** (`hcr2/timestamps.py`): `created_at`, `last_modified` and
  `active_modified` are UTC, written by SQLite's `CURRENT_TIMESTAMP` via column default and the
  `players` triggers — display them through `to_local()`, write them with `utc_now()`. The
  `update_players_last_modified` trigger has no `WHEN` clause, so it overwrites whatever Python
  wrote on any update. `away_from` / `away_until` are local time and are compared against local
  time in the absence logic — leave those alone.
- **Report why something failed.** Import paths collect a message per failed row
  (`PlayerImportResult.messages`, `DonationImportResult.messages`, capped in the output);
  `integrations/nextcloud.py` reports the exception *type* to stderr, deliberately not the message,
  because request exceptions carry the URL including the Nextcloud account name.

Invariants the refactor established and that new code should preserve:

- `modules/*` contains **no SQL** and **no prints except Usage text** — everything else goes through
  a service and an `hcr2/output/` function. Services return status/result dataclasses; the module
  hands them to an output function rather than formatting inline.
- Services never shell out to the CLI (imports used to self-invoke `python hcr2.py ...`; they don't now).
- `NEXT_STEPS.md` is the refactor log (in German), including the step-wise working rule:
  read context → build the target layer → rewire the module → add tests → run the suite.

### Database

- `hcr2/db/connection.py` resolves `DB_PATH` at import time: the sibling directory
  `../hcr2-db/hcr2.db` if it exists, else `./hcr2.db`. In this checkout the sibling path exists, so
  every CLI command reads and writes `/home/tobias/sources/hcr2-db/hcr2.db` — the repo-root
  `hcr2.db` is an unused empty leftover. Tests override the path with
  `mock.patch.object(connection, "DB_PATH", ...)` — see `tests/support.py`.
- Schema changes go in `hcr2/db/migrations/NNNN_*.sql`; the runner (`hcr2/db/migrations.py`) tracks
  applied files in `schema_migrations` and runs with `PRAGMA foreign_keys=OFF`. Migrations must be
  idempotent-friendly (`CREATE TABLE IF NOT EXISTS` style). A migration that rewrites tables must
  wrap itself in `BEGIN; … COMMIT;` — `executescript` otherwise runs each statement in autocommit
  and a mid-script failure leaves the DB half migrated.
- **Deletes are guarded, not cascading.** `donation`, `match` and `matchscore` use
  `ON DELETE RESTRICT` (migration `0002`): a row holding result data cannot be deleted while
  dependents exist — move them first (`matchscore edit <id> --player <id>`). `teamevent_vehicle`
  keeps `CASCADE`, it is only a mapping. Enforcement needs both halves: `connect_path()` sets
  `PRAGMA foreign_keys=ON` per connection (SQLite defaults it to OFF, which made the clauses
  decorative), and `hcr2/services/deletions.py` checks dependents beforehand so the user gets a
  readable message instead of an `IntegrityError`. Add new delete paths to its `DEPENDENCIES` and
  `TARGETS` maps — `TARGETS` also makes a delete of an unknown id report `NOT_FOUND` rather than
  claiming success.
- The runner was never applied to the live databases (`schema_migrations` is absent there), so the
  first `migrate_db.py` run applies `0001` too — harmless, it is all `IF NOT EXISTS`.
- Pre-existing FK violations survive the switch; enforcement only covers new changes. Check with
  `sqlite3 <db> 'PRAGMA foreign_key_check'`.
- Root `schema.sql` is a **generated dump** of the live DB (`backup_schema.py`), not the source of
  truth — never edit it by hand to change schema.
- `create_db.py` is a thin wrapper around the same runner.

### Environments

dev and prod live on the same host as different users, with **separate databases**:

| | dev (this checkout) | prod |
|---|---|---|
| user | `tobias` | `nextcloud` |
| repo | `/home/tobias/sources/hcr2-bot`, branch `dev` | `/home/nextcloud/hcr2-bot`, branch `main` |
| DB | `/home/tobias/sources/hcr2-db/hcr2.db` | `/home/nextcloud/hcr2-db/hcr2.db` (not readable as `tobias`) |
| bot | `hcr2-bot-dev.service` → `bot.py dev` | `hcr2-bot-prod.service` → `bot.py prod` |

Both bots run as **enabled systemd units** (`/etc/systemd/system/hcr2-bot-{dev,prod}.service`,
`Restart=on-failure`), not as hand-started processes. Because the bot shells out per command, edits
under `hcr2/` and `modules/` take effect on the next Discord command without a restart; only changes
to `bot.py` itself need one — and a long-running instance is serving Discord the whole time:

```bash
sudo systemctl restart hcr2-bot-dev     # ask the owner; sudo is not available to Claude here
systemctl status hcr2-bot-dev
journalctl -u hcr2-bot-dev -n 50
```

Never start the bot in `prod` mode from here, and never write toward `/home/nextcloud/...`.

The owner refreshes dev with prod data by hand — a one-way copy, prod → dev:

```bash
sudo cp -v /home/nextcloud/hcr2-db/hcr2.db /home/tobias/sources/hcr2-db/hcr2.db
```

Don't run it unprompted: it needs `sudo` and it discards whatever is in the dev DB. Note that the
dev DB therefore holds real member data.

Host-level automation touches only the **prod** DB: `hcr2-db.path` watches
`/home/nextcloud/hcr2-db/hcr2.db` and triggers `hcr2-db-sync.service` (snapshot to pCloud via
`~nextcloud/.local/bin/hcr2-db-prod-sync.sh`), and `hcr2-backup.timer` runs `backup_hcr2db.sh` at
06:00 and 18:00. The dev DB has no such safety net — no automatic backup, no snapshot.

Deploy runs elsewhere: `.github/workflows/deploy-hcr2-bot.yml` executes on a self-hosted runner on a
**different host**. The paths it references (`/home/tobias/sources/homelab`,
`playbooks/setup-hcr2.yml`) exist there, not in this checkout — don't try to run or debug that
playbook locally.

### Sheets / Nextcloud

**The remote layout is one subfolder per source of truth**, and every remote path in the
codebase derives from the constants in `hcr2/integrations/nextcloud.py` — a hardcoded second
copy is how the two drift apart:

```
Power-Ladys-Scores/            share root, exposed to the team as /Scores
  Team-Event/S<season>/        match videos + match sheets (both, same folder)
  Ladys/                       Ladys.mp4 (team screen) + Ladys.xlsx
  Donations/                   Donations.xlsx
  Wochen-Truhe/                weekly chest, feature still to come
```

`season_subpath()` and `remote_path()` build the paths; `sheets.web_url()` maps a remote
subpath to the share link the bot posts, so `/Scores` mirrors `Power-Ladys-Scores` one to one.
`match_sheet_local_path` keeps the same shape locally, so the mirror in the repo root can be
compared with the remote by eye. The Excel route is deliberately kept working as the
Claude-free fallback for entering results by hand.

`sheet` commands export a match/player/donations workbook, upload it to Nextcloud (edited in
Collabora by users), then re-import and diff it back into the DB. Flow control lives in
`hcr2/services/sheets.py`, workbook I/O in `hcr2/exporters/excel.py`, remote paths and WebDAV in
`hcr2/integrations/nextcloud.py`, status output in `hcr2/output/sheets.py`.

**dev and prod share one Nextcloud target** (same `NEXTCLOUD_BASE`, same credentials), while their
databases are separate. So a `sheet` command run from dev acts on the files the prod team is actually
working in. `sheet player import` and `sheet donations import` call `cleanup_imported_workbook`,
which **deletes the remote workbook** after importing — running either from dev imports the team's
entries into the *dev* DB and removes their file. Match-sheet import (`sheet import <match_id>`)
deletes only the local temp copy. Never run `sheet` commands to try something out; the tests cover
these paths network-free by injecting a `workbook_reader` and patching the up/download helpers.

Match-sheet column C (`Player`) is a rename channel: on import, a changed non-empty name is written
to `players.name` via `player_service.edit_player` (alias untouched), reported per player in the
import output, and rejected renames keep the stored name. An empty cell never clears a name, and
names longer than `MAX_PLAYER_NAME_LEN` abort the import as a validation error. Rows using `a` in
column B create a player from column C as before.

### Match videos

`video` reads the final standings recording instead of a workbook. The video is dropped into the
**same Nextcloud folder as the match sheets** (`Power-Ladys-Scores/Team-Event/S<season>/`), found via
`nextcloud.list_directory` (PROPFIND, Depth 1), cached under `tmp/video/<match_id>/` and cut into
frames by ffmpeg. `hcr2/services/videos.py` holds the flow,
`hcr2/output/videos.py` the prints, `.claude/skills/match-video/SKILL.md` the reading instructions
(row layout, colour rule, transliteration, the known renamer at player id 50).

Two things are deliberate:

- **Two cross-checks are code, not prompt discipline.** `video apply` refuses to write unless the
  sum of the points column equals `score_ladys` from the video header (is the reading complete?)
  *and* the `opponent` read from the header matches `match.opponent` (is this the right recording?).
  `compare_opponent` normalises away case, spaces, accents, emoji and symbols and tolerates a name
  the video truncated, so only a genuinely different team trips it. `--force` downgrades both to
  warnings.
- **A video whose name does not carry the match id is flagged**, even when it is the only file in
  the folder — the wrong recording produces plausible but wrong scores.
- **Two structural checks catch a misread digit** where the sum cannot: the standings are ordered
  by score and points follow the rank, so a higher score with fewer points is impossible
  (`_check_monotonicity`); and the real ceiling is the event's `tracks × max_score_per_track`
  (60000 for a 4-track Nitro), not the flat 75000 the matchscore service allows.

Everything else is a **`ReviewNote`** — `build_notes` compares the reading against the database and
reports what does not fit *without* blocking: a video name that differs from the stored one (with a
ready-made `player edit`, but only when the video name is ASCII — otherwise it has to be
transliterated by hand first), a roster player who did not drive split by whether they are marked
away, and score outliers. Outliers are measured against the **median shift of the whole team**, not
against the player's own average alone: a hard track set drags everyone down and would otherwise
flag the entire roster. This is why `VideoEntry.name` carries what the *video* showed rather than
what the database holds — the model records, the code compares.

A roster player who joined **after the match started** could not take part at all, so she is
reported as `[Joined late]` rather than as a no-show, and gets **no matchscore row** — a 0/0 would
read as having ducked out and would drag her average down. Two conditions must both hold, and the
second is what makes it safe: `RosterPlayer.joined_at` (from `active_modified`, falling back to
`created_at`) is **strictly after** `match.start`, *and* `matchscores.has_ever_driven` is false.
The date alone is not evidence — `created_at` is one bulk seed timestamp for every player imported
at once (`2025-07-20` in prod), so on any match older than that it would excuse the entire roster;
measured against the live DB that is 48 players versus the 1 the guard actually lets through. A join
**on** the start date stays a no-show, because day granularity cannot place it either side of the
start and a wrong excuse hides a real absence.

`apply_results` does not reuse `sheets.apply_match_sheet_entries` because `absent` may be omitted
in the JSON; it is then derived from the away dates instead of being forced to 0. Unlike
`sheet player import`, nothing on Nextcloud is deleted.

### Zwischenstand eines laufenden Matches

`video interim --match <id>` liest dieselbe Aufnahme wie `video apply`, aber aus einem
laufenden Match (`<id>-tmp.mp4` neben der späteren Endaufnahme) und **schreibt nie**.
`hcr2/services/interim.py` hält das Modell, `hcr2/output/interim.py` die deutsche,
postfertige Ausgabe, der Skill-Abschnitt „Modus Zwischenstand" in
`.claude/skills/match-video/SKILL.md` die Leseanleitung. Es gibt **zwei Einstiege in
dieselbe Anleitung**: `match-video` (entscheidet am Countdown selbst) und das dünne
Skill `zwischenstand`, das nur die Weiche stellt und dorthin verweist — die
Leseanleitung (Zeilenaufbau, gelb/blau, Transliteration, ähnliche Namen) steht
absichtlich nur einmal, weil eine zweite Kopie von der ersten wegdriftet. Zweck ist Eingreifen statt
Protokollieren: wer ist noch nicht gefahren, wer hängt weit zurück, wen kann man loben.

- **Der Countdown ist der Beweis, nicht die Absicht.** Die Lesung trägt ihn als
  `VideoResults.time_left`, und `validate_results` **verweigert** eine Lesung mit
  `time_left` als Endergebnis (`--force` degradiert das zur Warnung). Ohne diese Sperre
  wäre der teuerste Fehler ein einziger Tippfehler im Kommando: `video apply` schriebe
  für jede noch nicht Gefahrene eine 0/0-Zeile, `absent` würde aus den Urlaubsdaten zu 0
  abgeleitet — und damit steht sie in jedem Schnitt und in `stats broom` als
  **unentschuldigtes Fehlen**, was dort bedingungslos in den Topf führt.
- **Ab Match 2 eines Events ist der Maßstab der eigene Score aus Match 1 desselben
  Events** (`matchscores.scores_in_teamevent`) — gleiche Strecken, also der einzige
  faire Vergleich; der eventübergreifende Schnitt aus `recent_scores` misst andere
  Strecken. Im ersten Match des Events gibt es diesen Maßstab nicht, dann fällt der
  Bericht auf den Schnitt zurück (`reference == "history"`) und sinnvoll sind dort nur
  „nicht gefahren" und „wirkt abgebrochen".
- **Alles wird gegen das Tempo des Teams geteilt** (Median aus `score/base`), sonst
  misst der Bericht nur, wie weit das Match ist. Zwei Zahlen dahinter sind an der
  echten DB gemessen, nicht gewählt: innerhalb eines Events sind die späteren Matches
  **systematisch besser** (Median 1,04× des ersten, Match-Mediane 0,99–1,14 über 8837
  Zeilen seit 2025) — gegen glatte 100 % gemessen wäre „hat sich gesteigert" die halbe
  Mannschaft. Und gegen dieses Tempo fällt ein vollständiger Lauf praktisch nie unter
  0,6 (1,2 % von 1152 Zeilen, p1 = 0,58), also ist `ABORT_RATIO` dort die Grenze
  zwischen „schwach" und „abgebrochen".
- **Ein Riesensprung über eine kaputte Basis ist keine Steigerung.** Am echten Video
  stand eine Spielerin mit +274 % oben — ihr Vergleichswert aus Match 809 war selbst ein
  Abbruch (6.034). Sie hätte damit die beiden echten Steigerungen (+56 %, +33 %)
  verdrängt und wäre gleichzeitig mit 22.584 in die „Luft nach oben"-Liste gehört.
  `_base_was_broken` hält solche Fälle deshalb aus der Lobliste heraus.
- **Der Bericht ist auf Handlungsfähigkeit getrimmt, nicht auf Vollständigkeit.** Je
  Wertungsliste `TOP_LIMIT` (3) Namen — bei „wirkt abgebrochen" mit Restzähler
  (`aborted_more`), bei „Steigerungen" ohne —, absolute Scores statt Prozenten,
  keine Erklärzeilen — ~800 Zeichen. Das ist Vorgabe der Teamleitung („die Leader sollen
  nicht überfordert werden"), und deshalb steht die Kürzung im Service (`aborted_more`),
  nicht in der Ausgabe: sie ist Teil des Modells, nicht Kosmetik. **„Luft nach oben"
  weicht ab** (`BEHIND_LIMIT` = 5, **kein** Restzähler): das ist die Liste, auf die die
  Leitung im laufenden Match zugeht, drei Namen waren dafür zu wenig. Weil der Rest dort
  nicht gemeldet wird, hat das Modell auch kein `behind_more` — ein Feld ohne Abnehmer
  wäre nur eine Behauptung über die Ausgabe.
- **Neuzugänge stehen immer im Bericht** (`_newcomers`, `NEWCOMER_MATCHES` = 3),
  gefahren oder nicht. Sie ist keine Wertung, sondern eine Beobachtungsliste: eine Neue
  hat im laufenden Event meist gar keinen Vergleichswert, käme also in keinem anderen
  Block vor. `matchscores.driven_counts` holt die Zahlen für den ganzen Kader in einer
  Abfrage.
- **Eine Zeile, die sich nicht zuordnen lässt, gehört mit `"pid": 0` in die Lesung.**
  Sie wird als Warnung gemeldet; ließe man sie weg, stünde die Spielerin, zu der sie
  gehört, unter „noch nicht gefahren". Genau so fiel im ersten echten Lauf auf, dass
  eine Neue („Elias18") im Video stand und eine Gekickte noch im Kader.
- **`--season` an `list`/`pull`/`frames` löst das Ei-Henne-Problem**: der Gegner steht
  erst im Videokopf, die Match-Zeile kann also noch fehlen. Ordner ist die Saison, nicht
  das Match. Das Match wird danach mit `match add` angelegt — **ohne Ergebnisse**.
- `--cleanup` löscht die `-tmp`-Aufnahme auf Nextcloud und die lokalen Frames wieder,
  verweigert das aber bei einer Datei, die exakt `<id>.mp4` heißt: das ist die
  Endstandsaufnahme, die einzige Kopie eines nicht wiederholbaren Ergebnisses.
  **Bericht und Aufräumen sind zwei unabhängige Schritte** (`_print_interim_report`,
  `_cleanup_interim`): das Aufräumen wird typisch später nachgeholt, wenn die Lesung
  nicht mehr im Standardpfad liegt, und hing es am Lesen, brach `--cleanup` mit
  `❌ results file not found` ab, ohne die Datei anzufassen. Eine fehlende Lesung ist bei
  reinem Aufräumen deshalb still — ein ❌ würde über `status.py` den Exit-Code auf 1
  setzen und ein geglücktes Löschen als Fehlschlag melden. Eine mit `--file` benannte oder
  eine vorhandene, aber kaputte Lesung wird weiter gemeldet und hält das Löschen nicht auf.

Die Punktsumme stimmt auch mitten im Match mit der Kopfsumme (an einem echten
Zwischenstand geprüft: 46 Zeilen, exakt 589), taugt hier also weiter als
Vollständigkeitsprobe — nur ist sie im Bericht eine Warnung, weil nichts geschrieben wird.

### Team screen video (player-video)

`video player frames` / `video player apply` read `Ladys.mp4` from `Power-Ladys-Scores/Ladys/`
(next to `Ladys.xlsx`, it is not season-bound) and reconcile the active PLTE list:
garage power, names, joiners, leavers. `hcr2/services/rosters.py` holds the diff,
`.claude/skills/player-video/SKILL.md` the reading instructions.

The problem this flow exists to solve is not OCR, it is identity: an unknown name may be a
new member or one of 600+ former players under a changed name. So `build_plan` never
resolves an addition on its own — the plan stops at `PENDING` until the row carries `new`
or `reactivate: <id>`. `find_candidates` puts the players *missing from the video* at the
top of every candidate list unconditionally, because one leaver plus one arrival is what a
rename looks like from outside; below them come fuzzy matches, where containment
(`Bisa` inside `BisaTheWise`) outranks the raw ratio — short leftover names score
deceptively high on `SequenceMatcher` alone. `reactivate` pointing at an *active* player is
the normal rename case and turns into RENAME + GP instead of REACTIVATE, and removes that
player from the leavers.

Two rails mirror the match flow: the member count in the screen header must equal the rows
read, and more than `MAX_LEAVER_SHARE` of the roster leaving is treated as an incomplete
reading. A third is specific here — `untypeable_characters` rejects any stored name the
team could not enter on a German keyboard (umlauts and ß pass, `£ π Ł` and emoji do not),
so the transliteration convention is enforced rather than merely documented.

**ffmpeg is a runtime dependency of `video frames` only**, and it is not packaged as `ffmpeg` here:
CentOS Stream 9 has no such package, EPEL ships `ffmpeg-free`, and the recordings are **HEVC**
(`hvc1` + AAC) — the codec that build may drop. So `resolve_ffmpeg()` tries `$HCR2_FFMPEG`, then
`PATH`, then `imageio_ffmpeg.get_ffmpeg_exe()`; `pip3 install --user imageio-ffmpeg` bundles a
static full build (verified to decode HEVC) and needs no root. It is deliberately **not** in
`requirements.txt`: prod only runs the bot, which has no video command. `video frames` reports a
missing binary with that hint rather than failing obscurely.

### Weekly distance

`distance` holds the kilometres from the team distance chest — **one row per player and ISO
week, holding that week's distance**, not a running total like `donation`. The chest resets
every period, so the number in the video already is the week's performance and there is
nothing to subtract. Migration `0003`, `ON DELETE RESTRICT` like the other result data, and
`deletions.DEPENDENCIES["player"]` lists it so a delete reports it instead of failing.

The averages in `player show` and in the ranking are deliberately the **same** window
(`distances.AVERAGE_WINDOW`, imported into the players repository as
`DISTANCE_AVERAGE_WINDOW`): two different definitions of "average" in two places is how a
number stops meaning anything. It looks at recent weeks rather than all time, so it describes
current form and survives one missed week.

`import_week` takes the chest progress from the video header as `team_total` and refuses to
write when the kilometres do not add up to it — the same role the points sum plays for a
match. The videos live in `Wochen-Truhe/<year>/w<week>.mp4`; `video chest frames --year --week`
fetches and cuts them, matching the week number rather than the exact filename so `W34.mp4`
and `w034.mp4` both work; `video chest apply` writes a reading, and
`.claude/skills/chest-video/SKILL.md` holds the reading instructions.

**The completeness proof here is the member count, not the chest total** — and that is a
correction, not a preference. The first design blocked on the chest progress the way the
match flow blocks on the points sum. Measured against a real recording (2026 W34) the 49
rows added up to 10824 km while the chest showed 11031: the chest keeps counting kilometres
of players who left mid-period, the list only shows current members. So `member_count` from
the header is the hard check and the chest difference is reported without blocking.

Bot: `.km` (last week's ranking), `.km <player>` (that player's weeks), `.km weeks` (team
totals). It is in `PUBLIC_COMMANDS`.

**Discord drops any message over 2000 characters** (`MAX_DISCORD_MSG_LEN` is 1990), and
`send_codeblock` used to answer that with "Output too long to display" — a 49-player `.km`
came to 2154 characters and produced an empty reply. It now splits on line boundaries via
`codeblock_chunks`, capped at `CODEBLOCK_MAX_MESSAGES` with a warning naming how many would
have been needed; output that already fits takes the unchanged single-message path.

**Do not judge a bot command's size from the `COMMANDS` dict at the top of `bot.py`.** It is
a fallback table, and the dispatch below overrides it: `.p` is listed there as
`player list` (82k characters) but the handler actually runs
`player list-active --team PLTE` — 1551 characters, which always fitted. Measure what the
handler runs.

Independently, the kilometre ranking is sized so a full roster stays inside one message
(1691 characters for 49 players) — a test pins that, because widening a column later would
otherwise silently start splitting the weekly ranking in two. As of now no bot command
exceeds the limit, so the splitting is a net for lists that grow, not a live fix.

### Leistungsrangliste (`stats perf`)

`perf` ist die **einzige** Leistungsrangliste. `avg` und `rank` gab es daneben und sind
entfernt: `avg` rief dieselbe Funktion mit denselben Argumenten auf wie `perf` (die
Ausgaben waren byte-identisch), und `rank` war `perf --active` plus der Auffüllung, die
jetzt `--no-skip` heißt. Drei Namen für eine Rechnung sind der Weg, auf dem zwei
Wahrheiten entstehen — dieselbe Spielerin stand in `perf 64` mit 14,7k und in `rank 64`
mit 14,3k, weil der Median einmal über 54 und einmal über 49 Spielerinnen lief.

Die Rechnung ist überall dieselbe: mittlerer Abstand zum Match-Median, auf 4 Strecken
normiert. Was die Flags ändern, ist **wer in die Liste kommt** — und damit auch, über
wen der Median gebildet wird:

- **Default: der aktive PLTE-Kader**, jede mit mindestens einem gefahrenen Match. Das
  war bis 1.13.1 andersherum, und die Umkehr kam aus einer Beobachtung am Bot: der
  schickte **nie** ein `--active`, also zeigte `.stats` im Discord immer die Liste
  samt Ausgetretener — gefragt ist im laufenden Betrieb aber der Kader.
- **`--inactive`**: nimmt alle anderen mit einer Zeile in der Saison dazu, inzwischen
  Ausgetretene eingeschlossen. Nur so bleibt eine alte Saison lesbar, denn das damalige
  Feld ist das, woraus der Median gebildet wurde. **Die 20%-Hürde hängt an diesem Flag**,
  nicht mehr am Default: die Ein-Match-Einträge, gegen die sie gebaut ist, kommen genau
  aus dieser Gruppe. `score`/`points` können das gar nicht, die filtern immer auf den
  aktiven Kader. `--active` wird weiter angenommen und ist ein No-op, damit ein
  getipptes Kommando nicht mit einer Usage-Zeile antwortet.
- **`--no-skip`**: füllt die Liste mit den Spielerinnen des **heutigen** Kaders auf, die
  in der Saison keine Wertung haben (`-`, 0 Matches). Grundmenge ist
  `list_active_plte_players()`, also der Kader und nicht die Saison — deshalb
  **schließt es `--inactive` aus**: sonst stünden Ausgetretene *mit* Wertung und
  Neuzugänge *ohne* in einer Tabelle, zwei Grundmengen nebeneinander. In diesem Modus
  gibt es kein
  `PERF_TABLE_LIMIT`, denn abschneiden hieße genau die weglassen, für die das Flag da
  ist. Der Name führt in die Irre: „skip" meint übersprungene *Spielerinnen* in der
  Anzeige, nicht übersprungene *Matches* in der Rechnung, und hat mit
  entschuldigt/unentschuldigt nichts zu tun.
- **`--driven-only`**: lässt unentschuldigtes Fehlen aus der Rechnung. Ohne das Flag
  zählt es als 0-Score, **und das ist Absicht** — nicht zu erscheinen soll die
  Leistungszahl drücken. Das Flag beantwortet die andere Frage: wie fährt sie, wenn sie
  fährt. An Saison 64 sind das bis zu +5,6k (Bisa, 3× unentschuldigt), und im unteren
  Ende der Tabelle tauscht es Plätze.

Der Bot übersetzt die Flags in Wortformen (`.stats perf 64 noskip inactive driven`), weil
in Discord niemand `--` tippt. Vor der Konsolidierung schickte er ein `--no-skip`, das
`perf` gar nicht kannte — die Antwort war die Usage-Zeile, mit Exit-Code 0.

**`broom` rechnet die Leistung bewusst anders** als `stats perf`: dort sind die
unentschuldigten Nullen draußen (`if row.score > 0`), weil das Fehlen in broom schon
über die Zuverlässigkeit eingeht und sonst doppelt zählen würde. „Perf" in `stats` und
„Leistung" in `broom` sind daher zwei verschiedene Zahlen, und das ist gewollt.

### Broom (Rauswurf-Kandidaten)

`stats broom` rankt Kandidatinnen für einen Rauswurf über **die aktuelle Saison** und
begründet jede Zeile. `hcr2/services/broom.py` hält das Modell,
`hcr2/output/broom.py` die Ausgabe, `hcr2/repositories/broom.py` das SQL. Im Bot gibt
es zwei Einstiege, `.B` und `.stats broom`, die sich `bot.broom_call()` teilen — dort
werden Discord-Argumente auf Flags übersetzt (`.B 10` → `--top 10`, `s63` →
`--season 63`, `leader` → `--include-leaders`), weil in Discord niemand Flags tippt.
Eine Ziffer direkt hinter einem Flag ist dessen Wert und nicht das Top-Limit, sonst wird
`.B --last 80` zu `--last --top 80`.

**Unbekannte Argumente werden abgelehnt** (`_unknown_broom_args`), statt still zu
verschwinden. Ohne die Prüfung liefert ein getipptes `--seson 64` kommentarlos die
laufende Saison — ein Aufruf, der etwas anderes tut als das, was dasteht, ist in einer
Rauswurfliste das Letzte, was man brauchen kann. `--all` und `.B all` sind damit
**weggefallen**: das Flag steuerte, wie viele Begründungsblöcke gedruckt werden, und die
gibt es nicht mehr — die Tabelle zeigt ohnehin den ganzen Topf. Ein Wort, das
stillschweigend nichts tut, ist schlechter als keins.

**`--include-leaders` steht in der Kopfzeile** (`· mit Leadern`). `leaders_skipped == 0`
beantwortet die Frage nicht, denn das ist es auch ohne Leader im Kader; deshalb trägt
`BroomResult.include_leaders` das Flag selbst. Ohne die Anzeige tut das Flag sichtbar
nichts, solange kein Leader schwach genug für den Topf ist — an Saison 65 wächst
`all_rated` von 41 auf 50, und die Tabelle bleibt Zeile für Zeile dieselbe.

**Zwei Schritte, und bewusst nicht mehr als zwei** — Vorgabe der Teamleitung, und der
Grund ist das Gespräch danach: ein Rauswurf muss in einem Satz begründbar sein.

1. **Der Topf.** Wer in der Saison **einmal unentschuldigt gefehlt** hat, ist drin —
   bedingungslos, egal wie gut sie fährt. Der Rest wird mit den Leistungsschwächsten auf
   `SHORTLIST_SIZE` (10) aufgefüllt; Leistung ist der schlichte Abstand zum Match-Median
   über die **tatsächlich gefahrenen** Matches. Die Zahl ist eine **Zielgröße fürs
   Auffüllen, keine Obergrenze**: fehlen mehr als zehn unentschuldigt, wächst der Topf.
2. **Die Reihung darin: Besenpunkte.** Ganze Zahlen, viele sind schlecht, und **jede
   davon kann eine Spielerin selbst nachsehen** — das ist der ganze Zweck. Vier Achsen,
   die sich zur Gesamtzahl addieren:

   | Achse | Punkte | woher |
   |---|---|---|
   | `km/W` | 3 / 2 / 1 / 0 | Schnitt pro Woche über `KM_WINDOW_WEEKS` (5), Stufen bei 50 / 150 / 300 |
   | `Perf` | 10 … 1 | Platz **im Topf**: Schwächste 10, Beste 1, jeder Wert genau einmal |
   | `Fehlt` | +3 je Mal | gar nicht aufgetaucht, ohne Obergrenze |
   | `Slot` | +5 je Mal | eingeloggt und nicht gefahren, ohne Obergrenze |
   | `Matches` | 0 / −1 / −2 / −3 | gefahrene Matches, Stufen bei 15 / 50 / 150 |

   **`Fehlt` und `Slot` sind zwei disjunkte Spalten.** Wer sich einloggt und nicht
   fährt, steht in der DB als unentschuldigter Fehltermin *und* als Check-in — an der
   echten DB ausnahmslos (31 von 31). In einer gemeinsamen Zelle sah das aus wie zwei
   Vorfälle (`1+1`), obwohl es einer ist. Getrennt zählt jede Zeile genau einmal: unter
   `Fehlt` stehen nur die Male, bei denen sie gar nicht aufgetaucht ist, unter `Slot`
   die mit Check-in. Die 2 Punkte fürs Fehlen hängen dabei **an der Zeile, nicht an der
   Spalte** und wandern deshalb mit in die Slot-Spalte — sonst addierten sich die beiden
   nicht mehr zur Gesamtzahl. Ein Test pinnt genau das.

   **Die Höhe ist an der echten Liste kalibriert, nicht geraten.** Die Perf-Achse
   spannt 9 Punkte und ist damit breiter als der ganze beobachtete Topf von Saison 64
   (3 bis 9) — bei den ursprünglichen 2 Punkten verpuffte das Fehlen darin: `Bisa` stand
   dort mit **drei** unentschuldigten Fehlterminen auf derselben 9 wie `tina` und
   `Dommas`, die nie gefehlt hatten. Sechs Punkte Strafe, durch fünf Plätze besseres
   Fahren wieder hereingeholt — das Gegenteil der Vorgabe „der eine Fehler, über den
   nicht verhandelt wird". Bei 3 wiegen **drei Fehltermine genau die volle
   Leistungsspanne auf** (3 × 3 = 9). Das ist ein Satz, den man im Gespräch sagen kann,
   und zufällig genau die Zahl, die im alten Modell als `UNEXCUSED_CAP` stand. Ein Test
   pinnt die Gleichung gegen die Konstanten.

   **Vorfälle werden nicht mehr zu Episoden zusammengefasst.** `BLOCKER_EPISODE_DAYS`
   fasste zwei Check-in-No-Shows innerhalb weniger Tage zu einem zusammen, damit die
   Veto-Stufe nicht bei einem einzigen Wochenende zuschlägt. Die Stufe ist weg, und mit
   flachen Punkten je Spalte kehrte die Regel sich ins Gegenteil: zwei belegte Slots an
   einem Wochenende hätten 5 gekostet, zwei schlichte Fehltermine aber 6 — wer da war
   und nicht gefahren ist, käme billiger weg als wer gar nicht kam. Jetzt zählt jede
   Zeile, und `blocker_rows` ist das einzige Feld. (An der echten DB betraf das
   Zusammenfassen zwei Fälle in der gesamten Historie.)

   **Das ersetzt seit 1.21 ein Risiko von 0-100 aus gewichteten Perzentilen.** Das war
   genau und unbrauchbar: mit einer 53,4 kann in einem Rauswurfgespräch niemand etwas
   anfangen, mit „du hast zwölf Besenpunkte, hier kommt jeder einzelne her" schon.
   Gegengerechnet an S64 und S65 reiht das Punktemodell **fast identisch** zum
   Risiko (Rangkorrelation ρ = 0,93–0,95), die Verständlichkeit kostet also nichts.
   Mit den Perzentilen sind `_percentile`, die Kohorten-Verteilungen und die
   MIN_COHORT-Warnung weggefallen.

**Die Skala darf unter null gehen**, und das ist Absicht: wer viel fährt und lange
dabei ist, steht im Minus (am echten Kader bis −2). Das alte Risiko schnitt bei null ab
und warf damit die beste Nachricht weg, die diese Liste zu vergeben hat.

**Die Treue bleibt ein Minus, sie wird nie ein Plus.** Gedreht reihte sie identisch —
beide Formen unterscheiden sich nur um eine Konstante — aber der Satz im Gespräch
kippt von „deine 777 Matches ziehen drei Punkte ab" zu „du hast nur 27 Matches, das
sind drei Punkte gegen dich". Die Matchzahl ist fast dasselbe wie die Zugehörigkeitsdauer
(7 bei der Neuesten, 797 bei der Ältesten), also hätte sie als Strafposten immer die
Jüngsten nach oben gesetzt. Ein Test pinnt, dass `treue_points()` nie positiv wird.

**Der Slot wiegt schwerer als das Fernbleiben** (`BLOCKER_POINTS` 3 > `UNEXCUSED_POINTS`
2) — Vorgabe der Teamleitung: wer sich einloggt, hat gezeigt, dass er Zeit hatte, und
greift die Event-Belohnung ab, ohne dafür zu fahren. **Außer sie ist abgemeldet**: dann
zählt die Zeile gar nicht. An der echten DB ist der Fall noch nie eingetreten (31
Check-in-No-Shows, keiner davon abgemeldet), die Regel steht trotzdem im Code, weil sie
sonst beim ersten Mal falsch entscheidet.

**Gleichstände löst die Saisonpunktzahl auf** (`points_total`, 0–300 pro Match). Ganze
Zahlen erzeugen Gleichstände, wo das Risiko mit Nachkommastellen eine Trennung
vortäuschte — an S64 standen sieben Ladys auf demselben Wert. Die Saisonpunkte machen
daraus sechs Gruppen und trennen an der Schnittlinie in beiden gemessenen Saisons
sauber. Sie stehen als **eigene Spalte** in der Tabelle, obwohl sie nicht mitreihen:
bei Gleichstand entscheiden sie den Platz, und dann muss man sie sehen können, ohne
die Liste zu verlassen. Der Spaltenkopf heißt `Punkte`, weil sie im Team so heißen —
die Besen-Spalte daneben heißt `Besen` und nicht `Besenpunkte`, also stehen sich die
beiden Wörter nicht im Weg.

**Drei Achsen sind absolut, nur `Perf` ist eine Rangliste** — und das darf sie sein,
weil der Bot die Zahl nach jedem Match öffentlich postet (`.stats` steht in
`PUBLIC_COMMANDS`), jede also ihren Platz kennt. Die festen Schwellen halten, weil die
Verteilungen über Saisons hinweg kaum wandern (km/Woche-Quartile S64 87/152/294, S65
91/172/294).

**`Perf` misst am Topf, nicht am Kader**: zehn Plätze, zehn Punktwerte, **jeder genau
einmal**. Vorgabe der Teamleitung, und der Grund ist wieder das Gespräch danach — „du
bist die Schwächste von den zehn" ist eine Aussage, „du liegst im 38. Perzentil des
Kaders" ist keine. Deshalb stehen die Perf-Punkte im Code **nach** der Topf-Auswahl:
vorher kann der Maßstab nicht feststehen. Der Preis ist bekannt und in Kauf genommen —
die Skala ist damit **relativ zur Liste**, also verschiebt jede, die in den Topf kommt,
die Punkte aller anderen darin (`--include-leaders` ändert sie, eine Neue, die sich
hineinfährt, auch). Das geht nicht anders, wenn jede Zahl genau einmal vorkommen soll,
und zwei Tests pinnen beide Hälften: dass die Werte 1…10 vollständig vergeben werden,
und dass die drei absoluten Achsen dabei stehen bleiben. Gleichauf heißt gleiche Punkte
— gezählt wird, wie viele im Topf *echt* schwächer fahren, nicht ein laufender Index,
der je nach Sortierstabilität zwei gleiche Fahrerinnen verschieden bewertet hätte; bei
echtem Gleichstand fällt ein Wert deshalb aus. Wächst der Topf über zehn hinaus, wird
dieselbe Gerade über die größere Liste gelegt, dann wiederholen sich Werte.

Wer **nicht** im Topf steht, bekommt `PERF_POINTS_MIN`: sie fährt per Konstruktion
besser als die Schwächsten, über die geredet wird, und ihr Punktestand ist ohnehin keine
Ranglistenzahl — er taucht nur in `all_rated` und im JSON auf, nie in der Liste.

**Keine Zahl ist kein Freifahrtschein.** Fehlt die Kilometerwoche, kostet die Achse den
Höchstsatz. Früher fiel sie als „unbewertet" heraus und ihr Gewicht wurde umgelegt — in
einem Punktesystem gibt es nichts umzulegen.

**Die Ausgabe ist Tabelle plus Punktesystem, sonst nichts** — keine Begründungsblöcke
pro Person mehr, keine Kopfzeile mit Teamquote und Leaderzahl, keine Kadergröße und
keine Zahl der zu schaffenden Plätze. Die Titelzeile trägt nur noch den Namen und den
Zeitraum (`🧹 Besenliste – Saison 65 (5 Matches)`), weil eine Rangliste ohne ihren
Zeitraum nicht überprüfbar ist und alles andere die Tabelle sagt. Die Ausgabe ist damit
von ~3900 auf **~1550 Zeichen** gefallen und passt in **eine** Discord-Nachricht statt
zwei; ein Test pinnt das.

**Die Tabelle zeigt den echten Wert, die Punkte stehen in Klammern daneben.** Mit „124
km/Woche" kann eine Leitung in ein Gespräch gehen, mit einer 2 nicht — deshalb führt der
Wert. Die Klammer sorgt dafür, dass sich die Gesamtzahl trotzdem nachaddieren lässt
(`2 +7 +5 -1 = 13`, zwei Tests pinnen es). Eine Achse ohne Wert und ohne Punkte zeigt
nur `-`; `- (0)` wäre zehnmal dieselbe Null. `--top <n>` kürzt seit dem Wegfall der
Blöcke die **Tabelle** (vorher die Blöcke) — die Lesart, die `.B 5` im Bot ohnehin
nahelegt.

`BroomFactor` trägt die Zahl weiter **zweimal**: `value` kurz für die Zelle (`124`,
`-4.4k`, `1+1`), `detail` ausgeschrieben. `detail` und `_with_reasons()` werden nicht
mehr gedruckt, aber weiter gerechnet und über `--json` ausgegeben — dort steht, was
keine Achse abdeckt (Quote gegen den Teamschnitt, Vorfälle vor dem Fenster, Einbrüche,
Gleichstand). Im Gespräch trägt die Zeile, für alles andere gibt es `--json`.

**Der Ton ist sachlich, nicht wertend** — Vorgabe der Teamleitung, und der Grund ist
wieder das Gespräch danach: die Liste geht in eine Unterhaltung, in der jemand erfährt,
dass sie gehen soll. Wörter wie „die Schwächsten" kommen dort nicht an, und sie sind
auch gar nicht gemeint — bewertet wird eine Fahrleistung in einem Zeitraum, kein Mensch.
Deshalb steht in der Legende „+10 für die geringste Fahrleistung" statt „schwächste",
„aufgefüllt nach der Fahrleistung der Saison" statt „mit den Schwächsten", und der
Gleichstand wird von unten erklärt („wer mehr eingebracht hat, steht weiter unten")
statt von oben. Ein Test hält eine Liste von Wörtern von der Ausgabe fern.

**Die Ausgabe sagt „Ladys", nicht „Spielerinnen".** Das Team heißt Power Ladys, aber es
fahren auch Männer mit — die weibliche Form wäre schlicht falsch, und „SpielerInnen"
liest sich in einer Tabellenspalte wie ein Tippfehler. „Ladys" ist die Kurzform des
Teamnamens und meint alle; so redet die Leitung auch im Channel.
`pool_reason` (`"immediate"` / `"unexcused"` / `"performance"`) trägt den Eintrittsgrund,
und die Ausgabe nennt ihn über der Tabelle — ohne ihn liest sich die Liste als
Leistungsrangliste, und die guten Fahrerinnen darin wirken wie ein Fehler.

**Die Legende am Ende ist eine Nachschlagetabelle, kein Fließtext** — vier Zeilen, eine
je Achse, in derselben Reihenfolge wie die Spalten, damit man von einer Zelle geradeaus
nach unten schauen kann. Vorher standen dort neunundzwanzig Zeilen Prosa, die dasselbe
sagten. Jede Staffelgrenze und jeder Punktwert steht trotzdem da, weil die Ansage
„rechne nach" sonst nicht einlösbar ist; ein Test pinnt jede einzelne Schwelle gegen die
Konstanten — **mitsamt ihrem Vergleichszeichen**, denn die beiden Staffeln meinen es
verschieden (Kilometer greifen bei `<=`, Matches bei `<`), und eine Legende, die das
verwischt, ist genau an der Grenze falsch, an der jemand nachschaut.

**Nichts unterhalb der Tabelle ist breiter als sie** (`_print_wrapped`, gegen `WIDTH`).
Der Umbruch wird gerechnet und nicht von Hand gesetzt — sonst reicht ein Wort mehr in
einer Schwelle, und die Erklärung steht über die Liste hinaus; in einem Discord-Codeblock
heißt das, dass die Zeile seitlich wegläuft, während die Tabelle daneben ordentlich
endet. Bei den Achsenzeilen rücken die Folgezeilen unter den Textanfang ein, damit eine
Erklärung als Block stehen bleibt. Zeilen mit Emoji bekommen die Breite um eins
reduziert: `textwrap` zählt Zeichen, ein Emoji belegt aber zwei Anzeigespalten. Ein Test
misst **jede** Zeile in Anzeigebreite, über mehrere Ausgabeformen hinweg — und die
Inhaltstests prüfen seitdem gegen den geglätteten Text (`_flat`), weil eine Phrase nach
dem Umbruch mitten im Satz eine Zeilengrenze überqueren kann.

Die Legende trägt außerdem, **wie viele Kilometerwochen tatsächlich eingetragen sind**,
wenn das vom Fenster abweicht („letzten 5 Wochen (4 davon in der Truhe eingetragen)").
Das stand früher in der Kopfzeile; die ist weg, die Einschränkung musste bleiben —
„Schnitt aus fünf Wochen" wäre sonst eine Behauptung über Zahlen, die niemand
eingetragen hat.

**Es gibt keine Sofortfall-Stufe mehr, und auch keine Probezeit.** Beide sind mit dem
Umstieg auf Besenpunkte weggefallen. Der Sofortfall stand erst *neben* dem Topf (und fiel
damit samt seines unentschuldigten Fehlens aus der Rangliste, weil der Vorfilter vor der
Fehlen-Regel lief), dann *im* Topf mit einer `!`-Markierung. Beides brauchte eine zweite
Sprache auf der Seite, um zu erklären, warum über jemanden nicht mehr abgewogen wird —
und die Punkte sagen dasselbe: eine Neue mit belegtem Slot zahlt 5 Punkte und bekommt
null Treueabzug, steht also von allein oben, nach derselben Arithmetik wie alle anderen.
`PROBATION_MATCHES` und `NEWCOMER_MATCHES` gibt es nicht mehr; die Treueachse steht
unterhalb ihrer ersten Stufe (15 Matches) ohnehin auf null. Mit der Kopfzeile sind auch
`slots_to_free`, `TEAM_CAPACITY` und `TARGET_FREE_SLOTS` weggefallen: die Zielzahl stand
nur dort, und eine Zahl, die nirgends mehr auftaucht, ist nur noch Pflege. Wie viele
gehen sollen, entscheidet die Leitung, nicht die Liste.

**Der Zeitraum ist die Saison, weil die Saison die Einheit ist, in der entschieden
wird.** Am Saisonende verabschiedet sich die Leitung von einer Handvoll
Spielerinnen — Belege aus der Saison davor gehören nicht in diese Entscheidung.
`broom_repo.current_season()` nimmt die Saison nach Datum (damit `broom` und der Rest
von `stats` dasselbe unter „aktuell" verstehen) und fällt auf die Saison des neuesten
Matches zurück, wenn die kalendarisch laufende noch kein Match hat. `--season <n>`
liest eine abgeschlossene Saison, `--last <n>` ersetzt die Saison durch ein festes
Matchfenster (`WINDOW_MATCHES` = 40 ist dessen Voreinstellung und die einzige
verbliebene Rolle der Konstante) — beides zusammen wird **abgelehnt** statt still
eines gewinnen zu lassen, denn welches gewonnen hätte, stünde nur im Kopf der Ausgabe.

**Die Kohortenschwelle hängt am Fenster, nicht an einer festen Zahl**
(`cohort_threshold()`): `MIN_MATCHES` = 10 ist auf eine volle Saison gemünzt, und in
einer **laufenden** kann das niemand erreichen — nach vier Matches wäre die Kohorte
leer. Deshalb ist die Schwelle `COHORT_SHARE` (70 %) des Fensters, gedeckelt auf
`MIN_MATCHES`: bei 15 Matches bleibt es bei 10 wie bisher, bei 4 sind es 3. Seit dem
Umstieg auf Besenpunkte trägt die Kohorte nur noch zwei Dinge: den Maßstab der
`Perf`-Achse und die Teamquote im Kopf. Ist sie leer, kostet `Perf` für alle den
Höchstsatz — ehrlicher als ein Maßstab aus dem Nichts, und die drei anderen Achsen
reihen weiter.

**Die Kilometer kommen aus den letzten `KM_WINDOW_WEEKS` (5) Wochen, nicht aus den
Wochen der Saison** (`last_weeks()`) — und das ist seit 1.21 umgedreht. Der Grund ist
die absolute Punktschwelle: die Saisonwochen sind zwischen einer und dreizehn breit,
und an einer festen Stufe gemessen hieße derselbe Punktwert dann in jeder Saison etwas
anderes. Fünf Wochen sind dabei **grob eine Saison** — die läuft im Schnitt 4,3 Wochen
(S64 4,4, S63 4,4, S62 4,3) —, aber immer gleich breit.

Der Stichtag ist das **Ende des Wertungszeitraums, nicht heute**: `--season 63` liest
die letzten fünf Wochen *jener* Saison, sonst zöge eine abgeschlossene Saison die
Kilometer von heute herein und wäre morgen nicht mehr reproduzierbar. Den Zeitraum
liefert im Saisonmodus die `season`-Tabelle (eine laufende Saison endet heute), im
`--last`-Modus das älteste bis neueste Match. Der Preis ist bekannt und in Kauf
genommen: in der ersten Woche einer Saison stammen vier der fünf Wochen aus der
Vorsaison — vertretbar, weil Kilometer eine Gewohnheit sind und keine
Saisoneigenschaft.

Weiterhin **nicht** der gleitende `DISTANCE_AVERAGE_WINDOW` (8 Wochen) von `player
show` und der Kilometer-Rangliste: der folgt dem Tag, an dem er aufgerufen wird.
`BroomResult.km_weeks` ist die Zahl der Wochen, für die es **Zahlen gibt**, nicht die
Fensterbreite, und der Kopf nennt sie — eine fehlende Woche heißt, dass die Truhe nicht
gelesen wurde, nicht dass jemand nichts gefahren ist. Gibt es gar keine, kostet die
km-Achse den Höchstsatz und die Ausgabe sagt, dass die Zahlen fehlen.

**Beide Einstiege sind leader-only, kommen aber unterschiedlich dahin.** `.B` steht
einfach nicht in `PUBLIC_COMMANDS`, also greift die Kanal- und Rollenprüfung in
`on_message`. `.stats` **ist** öffentlich, deshalb braucht das Subkommando ein
**eigenes Gate** (`leader and in_admin_channel`) — fällt das weg, kann jedes Mitglied
im User-Channel die Liste abrufen. Ein Test in `tests/test_bot_contract.py` pinnt
beide Hälften. `.b` ist bewusst frei geblieben: nach der Konvention (klein listet,
groß zeigt Details) wäre das der Platz für eine Einzelansicht.

Entscheidungen, die gegen die echte DB gemessen sind und nicht aus Geschmack stammen:

- **Zugehörigkeit zieht feste Punkte ab, keinen Prozentsatz** (`TREUE_TIERS`, Maximum
  `TREUE_MAX` = −3). Vorher war es ein Multiplikator, und das war schon damals eine
  Korrektur: ein Faktor wirkt prozentual, also hing der Bonus daran, wie schlecht jemand
  dasteht, statt daran, wie lange sie dabei ist. An der echten Liste bekam eine
  Spielerin mit 304 Matches 16,4 Punkte geschenkt und eine mit **493** nur 14,8, weil
  deren Rohrisiko niedriger war; und die in allen drei Achsen Schwächste kassierte den
  größten Bonus überhaupt und landete damit auf Platz 6 statt 1. Feste Punkte hängen
  allein an der Zugehörigkeit — und sind ein Satz, den man im Gespräch sagen kann.
- **Die Probezeit braucht keine eigene Regel mehr.** Die Treueachse steht unterhalb der
  ersten Stufe (15 Matches) ohnehin auf null: nichts verdient, also nichts abgezogen —
  kein Schutz, aber auch keine Strafe. `PROBATION_MATCHES` und `PROBATION_DISCOUNT` sind
  damit weggefallen, und die Schärfe, die sie hatten, entsteht jetzt aus der Rechnung
  selbst: eine Neue mit einem Fehltermin zahlt dieselben Punkte wie eine Etablierte,
  bekommt aber keinen Abzug dagegen.
- **Der Rückkehrbonus ist weggefallen**, und mit ihm `RETURNER_BONUS` und
  `is_returner`. Er gab −1 extra, denn zurückzukommen *ist* Loyalität, und erkannte
  Rückkehrerinnen an gefahrenen Matches **außerhalb** des Fensters (≥ `MIN_MATCHES`)
  plus einer echten Lücke darin (`rows <= window - MIN_MATCHES`). Die zweite Bedingung
  war die eigentliche Arbeit — die Historie einer Veteranin ist ebenso groß, sie war nur
  das ganze Fenster über im Kader. **Sie konnte aber nicht mehr zutreffen:**
  `MIN_MATCHES` = 10 stammt aus der Zeit, als das Fenster 40 Matches breit war; seit der
  Wertungszeitraum die Saison ist (5 bis 15 Matches), ist die Schwelle größer als ihr
  eigenes Fenster. An Saison 65 hieß die Bedingung `window_rows <= −5`, und niemand hat
  weniger als null Kaderzeilen — in beiden gemessenen Saisons griff die Regel bei 0 von
  41 beziehungsweise 0 von 40. Die Legende versprach also etwas, das nie eintrat. Die
  Matchzahl allein sagt dasselbe: eine Rückkehrerin hat mehr Matches als eine Neue und
  bekommt darüber den größeren Abzug.
- **Die Garage Power spielt keine Rolle.** Bis 1.12.x wurde die Leistungsdelta um sie
  bereinigt; für einen freien Platz zählt aber, was eine Spielerin einfährt, nicht ob
  ihre Ausrüstung mehr hergegeben hätte. An Saison 64 verschob die Korrektur ohnehin
  nur eine von zehn Personen im Topf.
- **Wer im Zeitraum gar nicht gefahren ist, steht vorn — außer sie war durchgehend
  entschuldigt abgemeldet** (`_fills_the_pool`). Sonst käme entschuldigtes Fehlen über
  die Topfauswahl als schwerster Vorwurf zurück, obwohl es im ganzen Modell keiner ist.
- **Entschuldigte Abwesenheit ist kein Faktor.** Sie korreliert mit nichts (r = −0,03
  gegen die Kilometer), sagt also nichts über Einsatz, sondern ist echtes Leben. Sie
  erscheint als Kontextzeile mit „zählt nicht"; ein Test pinnt, dass sie die
  Besenpunkte nicht bewegt.

Die Begründungszeilen sind **deterministische Vorlagen**, kein Modelltext: gleiche
Datenlage, gleiche Sätze. Sie können auch entlasten („überdurchschnittlich"), und
`--json` gibt dasselbe maschinenlesbar aus. Die Rechnung bleibt Code, weil der Bot kein
Claude aufrufen kann und weil eine Liste, die sich zwischen zwei Läufen ändert, in
einem Rauswurfgespräch nichts wert ist.

**Die Ausgabe ist deutsch**, als einziges Modul unter `hcr2/output/` — der Text geht
direkt an die Teamleitung. Die Legende steht **am Ende**: in die erste
Discord-Nachricht gehört die Rangliste mit ihren Begründungen, nicht das Regelwerk.

Für die Kilometer trägt `fetch_km_for_weeks` **drei** Werte: Schnitt (daraus entstehen
die Punkte, und er bleibt fair, wenn eine Spielerin weniger Wochen auf dem Konto hat),
Wochenzahl (der Kopf muss sagen können, worauf der Schnitt ruht) und Summe (weil „495
km in vier Wochen" greifbarer ist als ein Schnitt). Der **Teamschnitt steht nur im
Kopf**, nicht in jedem Block — dort wäre er zehnmal dieselbe Zahl; das Verhältnis zu
ihm überlebt als „überdurchschnittlich".

**Die Spaltenköpfe sind Wörter, keine Emoji** (`Besen / km/W / Perf / Fehlt / Matches`),
und sie tragen die **Einheit des echten Werts**, nicht den Namen der Achse: in der Zelle
steht `124`, und `km/W` sagt, dass das Kilometer pro Woche sind. Ein Emoji ist *zwei*
Anzeigespalten breit, für `len()` aber ein Zeichen, und ZWJ-Sequenzen, Variation
Selectors und Skin-Tones rendern je nach Client ein oder zwei Spalten breit — eine
Tabelle, die nur manchmal ausgerichtet ist, ist schlechter als eine ohne Symbole. Zwei
Tests halten das: einer prüft, dass Kopf, Trennlinie und Datenzeilen identische Breite
haben (`WIDTH`), der zweite, dass die Kopfzeile reines ASCII ist.

### Secrets

`secrets_config.py` is gitignored and exports `CONFIG` (per-mode Discord token, channel and role IDs)
and `NEXTCLOUD_AUTH` (`(user, password)`). `bot.py` and `hcr2/integrations/nextcloud.py` import it at
module load, so those two fail on a fresh checkout without it. Tests avoid importing them.

## Conventions

- **CLI style** (see README): flags for filters and optional values (`--all`, `--season`, `--team`,
  `--id`); `--id <id>` is the preferred single-record selector; `delete --id <id>`; help text is
  `Usage` + `Commands` via `modules/common.print_command_help`. Bare positional forms still work as
  legacy aliases — keep them, but don't add new ones.
- **Versioning**: user-visible changes get a `python3 scripts/bump_version.py <level> "text"` bump;
  `version.py` holds `VERSION` plus a prepended `HISTORY` list. Pushing to `main` is *meant* to
  trigger `.github/workflows/deploy-hcr2-bot.yml` (Ansible playbook from a sibling `homelab` repo on
  a self-hosted runner) — see the deploy caveat under Environments.
- Comments and docs are a mix of German and English; match the file you're editing.
