from __future__ import annotations

import sqlite3
import textwrap
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
PRIMARY_DB_PATH = REPO_ROOT.parent / "hcr2-db" / "hcr2.db"
FALLBACK_DB_PATH = REPO_ROOT / "hcr2.db"
DB_PATH = PRIMARY_DB_PATH if PRIMARY_DB_PATH.exists() else FALLBACK_DB_PATH

STATUS_PREFIXES = {
    "success": "✅",
    "warning": "⚠️ ",
    "error": "❌",
    "info": "ℹ️ ",
    "delete": "🗑️ ",
    "update": "✏️ ",
}


def connect_db(*, row_factory=None) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


def connect_dict_db() -> sqlite3.Connection:
    return connect_db(
        row_factory=lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    )


def parse_flag_map(args: list[str]) -> dict[str, str]:
    flags: dict[str, str] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if not token.startswith("--"):
            i += 1
            continue

        if "=" in token:
            flag, value = token.split("=", 1)
            flags[flag.lstrip("-").lower()] = value
            i += 1
            continue

        flag = token.lstrip("-").lower()
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            flags[flag] = args[i + 1]
            i += 2
            continue

        flags[flag] = "true"
        i += 1

    return flags


def get_arg_value(args: list[str], key: str) -> Optional[str]:
    flags = parse_flag_map(args)
    return flags.get(key.lstrip("-").lower())


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "y", "on", "ja", "j"):
        return True
    if normalized in ("0", "false", "no", "n", "off", "nein", ""):
        return False
    return default


def parse_bool01(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None and default is not None:
        return default
    return 1 if parse_bool(value, default=False) else 0


def parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_ymd(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_date_or_none(value: Any) -> Optional[date]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    for parser in (datetime.fromisoformat,):
        try:
            return parser(text).date()
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    return None


def is_absent_on(match_day: date, from_str: Any, until_str: Any) -> bool:
    from_date = parse_date_or_none(from_str)
    until_date = parse_date_or_none(until_str)
    if from_date and until_date:
        return from_date <= match_day <= until_date
    if from_date and not until_date:
        return from_date <= match_day
    if not from_date and until_date:
        return match_day <= until_date
    return False


def print_rule(width: int) -> None:
    print("-" * width)


def print_table_header(*, columns: list[str], width: int) -> None:
    print(" ".join(columns))
    print_rule(width)


def print_status(level: str, message: str) -> None:
    prefix = STATUS_PREFIXES.get(level, STATUS_PREFIXES["info"])
    print(f"{prefix} {message}")


def print_error(message: str) -> None:
    print_status("error", message)


def print_warning(message: str) -> None:
    print_status("warning", message)


def print_info(message: str) -> None:
    print_status("info", message)


def print_success(message: str) -> None:
    print_status("success", message)


def print_unknown_command(entity: str, command: str) -> None:
    print_error(f"Unknown {entity} command: {command}")


def print_unknown_entity(entity: str) -> None:
    print_error(f"Unknown entity: {entity}")


HELP_FLAGS = {"-h", "--help"}


def is_help_request(*values: Any) -> bool:
    return any(str(value) in HELP_FLAGS for value in values if value is not None)


def print_command_help(
    *,
    usage: str,
    commands: list[tuple[str, str]],
    examples: Optional[list[str]] = None,
    notes: Optional[list[str]] = None,
) -> None:
    usage = usage.removeprefix("Usage:").strip()
    print("Usage:")
    print(f"  {usage}")
    print()
    print("Commands:")
    left_width = max((len(command) for command, _ in commands), default=0)
    left_width = min(max(left_width, 32), 56)
    for command, description in commands:
        wrapped_command = textwrap.wrap(command, width=left_width) or [""]
        if len(wrapped_command) == 1:
            print(f"  {wrapped_command[0]:<{left_width}}  {description}")
            continue
        for index, line in enumerate(wrapped_command):
            prefix = "  " if index == 0 else "    "
            print(f"{prefix}{line}")
        print(f"  {'':<{left_width}}  {description}")

    print()
    print("Options:")
    print("  -h, --help                      Show this help and exit")

    if notes:
        print()
        print("Notes:")
        for note in notes:
            print(f"  {note}")

    if examples:
        print()
        print("Examples:")
        for example in examples:
            print(f"  {example}")
