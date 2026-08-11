"""Reading and writing stored timestamps.

Two conventions live in the database and must not be mixed up:

- `created_at`, `last_modified` and `active_modified` are written by SQLite
  (column DEFAULT and the players triggers) via CURRENT_TIMESTAMP, which is
  **UTC**. Show them through `to_local()`.
- `away_from` / `away_until` are written by Python in **local** time and are
  compared against local time in the absence logic. Leave them alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


LOCAL_ZONE = ZoneInfo("Europe/Berlin")
STORED_FORMAT = "%Y-%m-%d %H:%M:%S"
PLACEHOLDER = "-"


def to_local(value: str | None, *, placeholder: str = PLACEHOLDER) -> str:
    """Render a UTC timestamp from the DB in local time.

    Unparsable or empty values are passed through unchanged rather than hidden,
    so odd data stays visible instead of turning into a wrong-looking date.
    """
    if value is None or not str(value).strip():
        return placeholder

    text = str(value).strip()
    parsed = _parse_utc(text)
    if parsed is None:
        return text
    return parsed.astimezone(LOCAL_ZONE).strftime(STORED_FORMAT)


def utc_now() -> str:
    """Timestamp for writing to a CURRENT_TIMESTAMP column, same format as SQLite."""
    return datetime.now(timezone.utc).strftime(STORED_FORMAT)


def _parse_utc(text: str) -> datetime | None:
    candidate = text[:19].replace("T", " ")
    try:
        naive = datetime.strptime(candidate, STORED_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone.utc)
