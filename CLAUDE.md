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
3. **One-off maintenance scripts** at the root (`import_match.py`, `import_teamevent.py`,
   `import_player.py`, `import_matchscores.py`, `import_flags.py`, `find_teamevent.py`,
   `backup_schema.py`, `catxls.py`). These predate the package: they hardcode
   `DB_PATH = "../hcr2-db/hcr2.db"` and talk to sqlite3 directly. Do not treat them as part of the
   layered architecture.

### CLI dispatch

`hcr2/cli/registry.py` holds `ENTITY_SPECS` — the single list of top-level entities
(`vehicle`, `player`, `teamevent`, `season`, `match`, `matchscore`, `stats`, `sheet`, `video`,
`donations`, `version`), each mapping to a `modules/<entity>.py` that exposes `handle_command(cmd, args)`
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
**same Nextcloud folder as the match sheets** (`Power-Ladys-Scores/S<season>/`), found via
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

`apply_results` does not reuse `sheets.apply_match_sheet_entries` because `absent` may be omitted
in the JSON; it is then derived from the away dates instead of being forced to 0. Unlike
`sheet player import`, nothing on Nextcloud is deleted.

**ffmpeg is a runtime dependency of `video frames` only**, and it is not packaged as `ffmpeg` here:
CentOS Stream 9 has no such package, EPEL ships `ffmpeg-free`, and the recordings are **HEVC**
(`hvc1` + AAC) — the codec that build may drop. So `resolve_ffmpeg()` tries `$HCR2_FFMPEG`, then
`PATH`, then `imageio_ffmpeg.get_ffmpeg_exe()`; `pip3 install --user imageio-ffmpeg` bundles a
static full build (verified to decode HEVC) and needs no root. It is deliberately **not** in
`requirements.txt`: prod only runs the bot, which has no video command. `video frames` reports a
missing binary with that hint rather than failing obscurely.

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
