#!/usr/bin/env python3

import sys
from modules import vehicle, player, teamevent, season, match, matchscore, stats, sheet, donations
from modules.common import is_help_request, print_command_help, print_unknown_entity
import version


ENTITY_MODULES = {
    "vehicle": vehicle,
    "player": player,
    "teamevent": teamevent,
    "season": season,
    "match": match,
    "matchscore": matchscore,
    "stats": stats,
    "sheet": sheet,
    "donations": donations,
}

def show_main_help():
    print_command_help(
        usage="hcr2.py <entity> <command> [options]",
        commands=[
            ("vehicle", "Manage vehicles"),
            ("player", "Manage players"),
            ("teamevent", "Manage team events"),
            ("season", "Manage seasons"),
            ("match", "Manage matches"),
            ("matchscore", "Manage match scores"),
            ("stats", "Show statistics"),
            ("sheet", "Manage Excel files for matches"),
            ("donations", "Manage Research Lab donations"),
            ("version", "Print version"),
        ],
        notes=[
            "Prefer flags for IDs, filters and optional values, e.g. --id, --season, --all, --team.",
            "Older positional forms still work as legacy aliases.",
        ],
    )

def show_entity_help(entity):
    if entity == "version":
        print(version.get_version())
        return

    module = ENTITY_MODULES.get(entity)
    if module is None:
        print_unknown_entity(entity)
        show_main_help()
        return

    module.print_help()

def main():
    if len(sys.argv) < 2:
        show_main_help()
        return

    entity = sys.argv[1]
    if is_help_request(entity):
        show_main_help()
        return

    if entity == "version":
        print(version.get_version())
        return

    if len(sys.argv) == 2:
        show_entity_help(entity)
        return

    command = sys.argv[2]
    args = sys.argv[3:]

    module = ENTITY_MODULES.get(entity)
    if module is None:
        print_unknown_entity(entity)
        show_main_help()
        return

    if is_help_request(command):
        module.print_help()
        return

    module.handle_command(command, args)

if __name__ == "__main__":
    main()
