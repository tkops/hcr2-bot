from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import sqlite3
import yaml

from modules.common import (
    connect_db,
    parse_int,
    print_command_help,
    print_table_header,
    print_unknown_command,
)


USAGE_ADD = "Usage: vehicle add <name> <shortname> | --name <name> --short <shortname>"
USAGE_DELETE = "Usage: vehicle delete <id> | --id <id>"
USAGE_EDIT = "Usage: vehicle edit <id> [--name NAME] [--short SHORTNAME] | --id <id> [--name NAME] [--short SHORTNAME]"


def handle_command(cmd: str, args: list[str]) -> None:
    handlers: dict[str, Callable[[list[str]], None]] = {
        "list": _handle_list,
        "add": _handle_add,
        "edit": _handle_edit,
        "delete": _handle_delete,
        "import": _handle_import,
        "export": _handle_export,
        "drop": _handle_drop,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("vehicle", cmd)
        print_help()
        return
    handler(args)


def _handle_list(args: list[str]) -> None:
    if args:
        print("Usage: vehicle list")
        return
    list_vehicles()


def _handle_add(args: list[str]) -> None:
    if args and args[0].startswith("--"):
        name = None
        shortname = None
        i = 0
        while i < len(args):
            token = args[i]
            if token == "--name" and i + 1 < len(args):
                name = args[i + 1]
                i += 2
                continue
            if token == "--short" and i + 1 < len(args):
                shortname = args[i + 1]
                i += 2
                continue
            i += 1
        if not name or not shortname:
            print(USAGE_ADD)
            return
        add_vehicle(name, shortname)
        return
    if len(args) != 2:
        print(USAGE_ADD)
        return
    add_vehicle(args[0], args[1])


def _handle_edit(args: list[str]) -> None:
    edit_vehicle(args)


def _handle_delete(args: list[str]) -> None:
    vehicle_id = _extract_vehicle_id(args, USAGE_DELETE)
    if vehicle_id is None:
        print(USAGE_DELETE)
        return
    delete_vehicle(vehicle_id)


def _handle_import(args: list[str]) -> None:
    import_vehicles(args[0] if args else None)


def _handle_export(args: list[str]) -> None:
    export_vehicles(args[0] if args else None)


def _handle_drop(args: list[str]) -> None:
    if args:
        print("Usage: vehicle drop")
        return
    drop_table()


def _fetch_vehicle_rows() -> list[tuple[int, str, str]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, shortname FROM vehicle ORDER BY id")
        return cur.fetchall()


def _parse_edit_fields(args: list[str]) -> tuple[Optional[int], Optional[str], Optional[str], bool]:
    vehicle_id = _extract_vehicle_id(args, USAGE_EDIT)
    if vehicle_id is None:
        print(USAGE_EDIT)
        return None, None, None, False

    name = None
    shortname = None
    i = 2 if args and args[0] == "--id" else 1
    while i < len(args):
        token = args[i]
        if token == "--name":
            if i + 1 >= len(args):
                print(USAGE_EDIT)
                return None, None, None, False
            name = args[i + 1]
            i += 2
            continue
        if token == "--short":
            if i + 1 >= len(args):
                print(USAGE_EDIT)
                return None, None, None, False
            shortname = args[i + 1]
            i += 2
            continue
        i += 1

    return vehicle_id, name, shortname, True


def _extract_vehicle_id(args: list[str], usage: str) -> Optional[int]:
    if not args:
        print(usage)
        return None
    if args[0] == "--id":
        if len(args) < 2:
            print(usage)
            return None
        return parse_int(args[1])
    return parse_int(args[0])


def list_vehicles() -> None:
    rows = _fetch_vehicle_rows()
    print_table_header(columns=[f"{'ID':<2}", f"{'Name':<18}", "SN"], width=26)
    for vehicle_id, name, shortname in rows:
        print(f"{vehicle_id:>2}.  {name:<18} {shortname}")


def add_vehicle(name: str, shortname: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO vehicle (name, shortname) VALUES (?, ?)",
            (name, shortname),
        )
    print(f"✅ Added vehicle '{name}' as '{shortname}'.")


def edit_vehicle(args: list[str]) -> None:
    vehicle_id, name, shortname, ok = _parse_edit_fields(args)
    if not ok:
        return

    if not name and not shortname:
        print("⚠️  Nothing to update.")
        return

    fields = []
    values = []
    if name:
        fields.append("name = ?")
        values.append(name)
    if shortname:
        fields.append("shortname = ?")
        values.append(shortname)
    values.append(vehicle_id)

    with connect_db() as conn:
        conn.execute(f"UPDATE vehicle SET {', '.join(fields)} WHERE id = ?", values)

    print(f"✅ Vehicle {vehicle_id} updated.")


def delete_vehicle(vehicle_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM vehicle WHERE id = ?", (vehicle_id,))
    print(f"🗑️  Vehicle {vehicle_id} deleted.")


def import_vehicles(file: Optional[str]) -> None:
    if not file or not os.path.exists(file):
        print(f"❌ File not found: {file}")
        return

    with open(file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    count = 0
    with connect_db() as conn:
        for vehicle in data:
            try:
                conn.execute(
                    "INSERT INTO vehicle (name, shortname) VALUES (?, ?)",
                    (vehicle["name"], vehicle["shortname"]),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass

    print(f"✅ Imported {count} new vehicles.")


def export_vehicles(file: Optional[str] = None) -> None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, shortname FROM vehicle ORDER BY name COLLATE NOCASE")
        data = [{"name": name, "shortname": shortname} for name, shortname in cur.fetchall()]

    yaml_str = yaml.dump(data, sort_keys=False, allow_unicode=True)
    if file:
        output_path = Path(file)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        print(f"✅ Exported {len(data)} vehicles to '{file}'.")
        return

    print(yaml_str)


def drop_table() -> None:
    with connect_db() as conn:
        conn.execute("DROP TABLE IF EXISTS vehicle;")
    print("🗑️  Vehicle table dropped.")


def print_help() -> None:
    print_command_help(
        usage="python hcr2.py vehicle <command> [args]",
        commands=[
            ("list", "Show all vehicles"),
            ("add --name <name> --short <short>", "Add one vehicle"),
            ("edit --id <id> [--name NAME] [--short SHORTNAME]", "Edit one vehicle"),
            ("delete --id <id>", "Delete one vehicle"),
            ("import <file>", "Import vehicles from YAML"),
            ("export [file]", "Export vehicles to YAML or stdout"),
            ("drop", "Drop the vehicle table"),
        ],
        notes=["Legacy positional aliases are still accepted for add, edit and delete."],
    )
