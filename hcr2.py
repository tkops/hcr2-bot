import sys
from modules import vehicle, player, teamevent, season, match, matchscore, stats, sheet, donations
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
    print("Usage: python hcr2.py <entity> <command> [args]")
    print("\nPreferred CLI style:")
    print("  use flags for ids and filters, e.g. --id, --season, --all, --team")
    print("  older positional forms still work as legacy aliases")
    print("\nAvailable entities:")
    print("  vehicle     Manage vehicles")
    print("  player      Manage players")
    print("  teamevent   Manage teamevents")
    print("  season      Manage seasons")
    print("  match       Manage matches")
    print("  matchscore  Manage matchscores")
    print("  stats       Show statistics")
    print("  sheet       Manage Excel files for matches")
    print("  donations   Manage Research Lab donations")
    print("  version     Print version")

def show_entity_help(entity):
    if entity == "version":
        print(version.get_version())
        return

    module = ENTITY_MODULES.get(entity)
    if module is None:
        print(f"❌ Unknown entity: {entity}")
        show_main_help()
        return

    module.print_help()

def main():
    if len(sys.argv) < 2:
        show_main_help()
        return

    entity = sys.argv[1]
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
        print(f"❌ Unknown entity: {entity}")
        show_main_help()
        return

    module.handle_command(command, args)

if __name__ == "__main__":
    main()
