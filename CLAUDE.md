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
   (`ID_LINE_RE`, `NAME_LINE_RE`, `BIRTHDAY_IDS_RE`). **Changing CLI output format can break the bot.**
   Bot commands are dot-prefixed (`.p`, `.m`, `.stats`); `PUBLIC_COMMANDS` gates what non-leaders may run.
3. **One-off maintenance scripts** at the root (`import_match.py`, `import_teamevent.py`,
   `import_player.py`, `import_matchscores.py`, `import_flags.py`, `find_teamevent.py`,
   `backup_schema.py`, `catxls.py`). These predate the package: they hardcode
   `DB_PATH = "../hcr2-db/hcr2.db"` and talk to sqlite3 directly. Do not treat them as part of the
   layered architecture.

### CLI dispatch

`hcr2/cli/registry.py` holds `ENTITY_SPECS` — the single list of top-level entities
(`vehicle`, `player`, `teamevent`, `season`, `match`, `matchscore`, `stats`, `sheet`, `donations`,
`version`), each mapping to a legacy `modules/<entity>.py` that exposes `handle_command(cmd, args)`
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
  idempotent-friendly (`CREATE TABLE IF NOT EXISTS` style).
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
`Restart=on-failure`), not as hand-started processes. The dev unit runs from this working directory,
so edits here do not take effect until it is restarted — and a long-running instance is serving
Discord the whole time:

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
