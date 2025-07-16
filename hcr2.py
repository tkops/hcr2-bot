import sys
from modules import vehicle, player, teamevent, season, match, matchscore, stats


def show_main_help():
    print("Usage: python hcr2.py <entity> <command> [args]")
    print("\nAvailable entities:")
    print("  vehicle     Manage vehicles")
    print("  player      Manage players")
    print("  teamevent   Manage teamevents")
    print("  season      Manage seasons")
    print("  match       Manage matches")
    print("  matchscore  Manage matchscores")
    print("  stats       Show statistics")


def show_entity_help(entity):
    if entity == "vehicle":
        vehicle.print_help()
    elif entity == "player":
        player.print_help()
    elif entity == "teamevent":
        teamevent.print_help()
    elif entity == "season":
        season.print_help()
    elif entity == "match":
        match.print_help()
    elif entity == "matchscore":
        matchscore.print_help()
    elif entity == "stats":
        stats.print_help()
    else:
        print(f"❌ Unknown entity: {entity}")
        show_main_help()


def main():
    if len(sys.argv) < 2:
        show_main_help()
        return

    entity = sys.argv[1]
    if len(sys.argv) == 2:
        show_entity_help(entity)
        return

    command = sys.argv[2]
    args = sys.argv[3:]

    if entity == "vehicle":
        vehicle.handle_command(command, args)
    elif entity == "teamevent":
        teamevent.handle_command(command, args)
    elif entity == "player":
        player.handle_command(command, args)
    elif entity == "season":
        season.handle_command(command, args)
    elif entity == "match":
        match.handle_command(command, args)
    elif entity == "matchscore":
        matchscore.handle_command(command, args)
    elif entity == "stats":
        stats.handle_command(command, args)
    else:
        print(f"❌ Unknown entity: {entity}")
        show_main_help()


if __name__ == "__main__":
    main()
