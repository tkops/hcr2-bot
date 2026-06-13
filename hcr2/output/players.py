from __future__ import annotations

import textwrap
from datetime import datetime

from hcr2.models.player import PlayerAbsentRow, PlayerDetail, PlayerLeaderRow, PlayerListRow, PlayerSearchRow
from hcr2.services.players import AwayClearResult, AwaySetResult, PlayerAbsentListResult, PlayerListResult


def print_player_list(result: PlayerListResult, *, active_only: bool = False, team_filter: str | None = None) -> None:
    rows = result.rows

    if team_filter and active_only:
        print(f"{'#':<3} {'ID':<4} {'Name':<14} {'GP':>6}")
        for i, row in enumerate(rows, start=1):
            print(f"{i:<3} {row.id:<4} {row.name:<14} {int(row.garage_power):>6}")
        return

    if team_filter:
        print(f"{'#':<3} {'ID':<4} {'Name':<20} {'Alias':<15} {'Leader':<6} {'ABS':<3}")
        print("-" * 80)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i, row in enumerate(rows, start=1):
            abs_mark = "x" if row.away_until and row.away_until > now_str else ""
            print(f"{i:<3} {row.id:<4} {row.name:<20} {row.alias or '-':<15} {bool(row.is_leader):<6} {abs_mark:<3}")
        print("-" * 80)
        return

    print(f"{'ID':<4} {'Name':<20} {'Alias':<15} {'GP':>6} {'Act':<5} {'Lead':<5} {'Birthday':<10} {'Team':<7} {'Discord':<18} {'Created':<20} {'ABS':<3}")
    print("-" * 140)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        abs_mark = "x" if row.away_until and row.away_until > now else ""
        created = (row.created_at or "-")[:19]
        print(
            f"{row.id:<4} "
            f"{(row.name or '-'):<20} "
            f"{(row.alias or '-'):<15} "
            f"{int(row.garage_power):>6} "
            f"{str(bool(row.active)):<5} "
            f"{str(bool(row.is_leader)):<5} "
            f"{format_birthday(row.birthday):<10} "
            f"{(row.team or '-'):<7} "
            f"{(row.discord_name or '-'):<18} "
            f"{created:<20} "
            f"{abs_mark:<3}"
        )
    print("-" * 140)
    print(f"Active players: {result.active_count}")


def print_player_detail(player: PlayerDetail) -> None:
    print(f"{'ID':<15}: {player.id}")
    print(f"{'Name':<15}: {player.name}")
    print(f"{'Alias':<15}: {player.alias or '-'}")
    print(f"{'Garage Power':<15}: {player.garage_power}")
    print(f"{'Active':<15}: {bool(player.active)}")
    print(f"{'Leader':<15}: {bool(player.is_leader)}")
    print(f"{'Birthday':<15}: {format_birthday(player.birthday)}")
    print(f"{'Team':<15}: {player.team or '-'}")
    print(f"{'Discord':<15}: {player.discord_name or '-'}")
    print(f"{'Created':<15}: {player.created_at}")
    print(f"{'Last modified':<15}: {player.last_modified or '-'}")
    print(f"{'Active modified':<15}: {player.active_modified or '-'}")
    print(f"{'Away from':<15}: {player.away_from or '-'}")
    print(f"{'Away until':<15}: {player.away_until or '-'}")
    print(f"{'First Match':<15}: {player.first_match or '-'}")
    print(f"{'Last Match':<15}: {player.last_match or '-'}")
    print(f"{'Match Count':<15}: {player.match_count}")
    _print_wrapped("About", player.about)
    _print_wrapped("Vehicles", player.preferred_vehicles)
    _print_wrapped("Playstyle", player.playstyle)
    _print_wrapped("Language", player.language)
    _print_wrapped("Emoji", player.emoji)


def print_player_search_rows(rows: list[PlayerSearchRow]) -> None:
    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
    print("-" * 74)
    for row in rows:
        print(
            f"{row.id:<4} {row.name:<20} {row.alias or '':<15} "
            f"{row.discord_name or '':<22} {row.garage_power:>5} {str(bool(row.active))[:1]}"
        )
    print("-" * 74)


def print_player_leaders(rows: list[PlayerLeaderRow]) -> None:
    print(f"{'ID':<4} {'Name':<25} {'Discord':<30}")
    print("-" * 64)
    for row in rows:
        print(f"{row.id:<4} {row.name:<25} {row.discord_name:<30}")
    print("-" * 64)
    print(f"👑 Leaders: {len(rows)}")


def print_absent_players(result: PlayerAbsentListResult) -> None:
    print("🛫 Absent Ladies")
    print(f"{'ID':<4} {'NAME':<20} {'TEAM':<6} {'UNTIL':<19} {'DAYS':>4}")
    print("-" * 58)
    for days, row in result.rows:
        print(f"{row.id:<4} {row.name:<20} {row.team:<6} {row.away_until:<19} {days:>4}")
    print("-" * 58)
    print(f"Count: {len(result.rows)}")


def print_away_set(result: AwaySetResult) -> None:
    brief = result.brief
    if brief:
        print(
            "✅ Away set\n"
            f"Player       : ID {brief.id} | Name: {brief.name} | Alias: {brief.alias or '-'} | Discord: {brief.discord_name or '-'}\n"
            f"From → Until : {result.away_from}  →  {result.away_until}"
        )
    else:
        print(f"✅ Away set for player {result.player_id}\nfrom: {result.away_from}\nuntil: {result.away_until}")


def print_away_cleared(result: AwayClearResult) -> None:
    brief = result.brief
    if brief:
        print(
            "✅ Back: absence cleared\n"
            f"Player: ID {brief.id} | {brief.name} | alias: {brief.alias or '-'} | discord: {brief.discord_name or '-'}"
        )
    else:
        print(f"✅ Back: absence cleared for player {result.player_id}")


def format_birthday(stored: str | None) -> str:
    if not stored:
        return "-"
    try:
        dt = datetime.strptime(stored, "%m-%d")
        return dt.strftime("%d.%m.")
    except ValueError:
        return stored


def _print_wrapped(label: str, text: str | None, width: int = 60, indent: int = 15) -> None:
    if not text:
        text = "-"
    wrapper = textwrap.TextWrapper(width=width, subsequent_indent=" " * (indent + 2))
    wrapped = wrapper.fill(text)
    print(f"{label:<{indent}}: {wrapped}")
