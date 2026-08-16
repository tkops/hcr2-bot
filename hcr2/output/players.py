from __future__ import annotations

import textwrap
from datetime import datetime

from hcr2.models.player import PlayerAbsentRow, PlayerDetail, PlayerLeaderRow, PlayerListRow, PlayerSearchRow
from hcr2.timestamps import to_local
from hcr2.services.players import (
    AddPlayerResult,
    AwayClearResult,
    AwaySetResult,
    EditPlayerResult,
    ExplicitPlayerResolutionResult,
    PlayerAbsentListResult,
    PlayerBirthdayListResult,
    PlayerListResult,
    PlayerResolutionResult,
)


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
        created = to_local(row.created_at)
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
    # These three are UTC in the DB; away_* are already local. See hcr2/timestamps.py.
    print(f"{'Created':<15}: {to_local(player.created_at)}")
    print(f"{'Last modified':<15}: {to_local(player.last_modified)}")
    print(f"{'Active modified':<15}: {to_local(player.active_modified)}")
    print(f"{'Away from':<15}: {player.away_from or '-'}")
    print(f"{'Away until':<15}: {player.away_until or '-'}")
    print(f"{'First Match':<15}: {player.first_match or '-'}")
    print(f"{'Last Match':<15}: {player.last_match or '-'}")
    print(f"{'Match Count':<15}: {player.match_count}")
    print(f"{'Avg km/week':<15}: {_avg_km(player)}")
    _print_wrapped("About", player.about)
    _print_wrapped("Vehicles", player.preferred_vehicles)
    _print_wrapped("Playstyle", player.playstyle)
    _print_wrapped("Language", player.language)
    _print_wrapped("Emoji", player.emoji)


def _avg_km(player: PlayerDetail) -> str:
    if not player.km_weeks:
        return "-"
    return f"{player.avg_km:.0f} ({player.km_weeks} weeks)"


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
    if not rows:
        print("❌ No leaders found.")
        return

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


def print_birthday_ids(player_ids: list[int]) -> None:
    if player_ids:
        print("BIRTHDAY_IDS: " + ",".join(str(player_id) for player_id in player_ids))


def print_birthday_list(result: PlayerBirthdayListResult) -> None:
    print(f"{'ID':<4} {'Name':<20} {'Birthday':<10} {'Emoji'}")
    print("-" * 43)
    for _days_until, row in result.rows:
        print(f"{row.id:<4} {row.name:<20} {format_birthday(row.birthday):<10} {row.emoji}")
    print("-" * 43)
    scope = "(active only)" if result.active_only else "(all)"
    print(f"Count: {len(result.rows)} {scope}")


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


def print_add_player_result(result: AddPlayerResult, player_name: str) -> None:
    if result.status == "INVALID_TEAM":
        print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
        return
    if result.status == "ALIAS_GENERATION_FAILED":
        print(f"❌ Could not generate unique alias for base '{result.alias_base}' (1..9 all taken).")
        return
    if result.status == "ALIAS_CONFLICT":
        print(f"❌ Alias conflict in PLTE: '{result.alias}' already exists.")
        return

    alias_info = f" | Alias: {result.alias}" if result.alias else ""
    gen_info = " (generated)" if result.alias_generated else ""
    print(f"✅ Player '{player_name}' added. ID: {result.player_id}{alias_info}{gen_info} | Team: {result.team}")


def print_edit_player_result(result: EditPlayerResult, player_id: int) -> bool:
    if result.status == "NOT_FOUND":
        print(f"❌ Player ID {player_id} not found.")
        return False
    if result.status == "ALIAS_REQUIRED":
        print("❌ Alias is required for team PLTE.")
        return False
    if result.status == "ALIAS_CONFLICT":
        print(f"❌ Alias conflict: '{result.alias}' vs '{result.conflict_alias}' (ID {result.conflict_player_id})")
        return False
    if result.status == "NOTHING_TO_UPDATE":
        print("⚠️  Nothing to update.")
        return False

    print(f"✅ Player {player_id} updated.")
    return True


def print_player_deactivated(player_id: int) -> None:
    print(f"🟡 Player {player_id} deactivated.")


def print_player_deleted(player_id: int) -> None:
    print(f"🗑️  Player {player_id} deleted.")


def print_player_activated(player_id: int) -> None:
    print(f"🟢 Player {player_id} activated.")


def print_invalid_id() -> None:
    print("❌ Invalid ID.")


def print_no_matching_player() -> None:
    print("❌ No matching player found.")


def print_player_id_not_found(player_id: int) -> None:
    print(f"❌ Player ID {player_id} not found.")


def print_single_selector_required() -> None:
    print("❌ Provide exactly one of --id, --name or --discord.")


def print_gp_requires_integer() -> None:
    print("❌ --gp expects an integer.")


def print_num_requires_integer() -> None:
    print("❌ --num expects an integer")


def print_name_required() -> None:
    print("❌ Name is required.")


def print_invalid_team_name() -> None:
    print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")


def print_invalid_team_value(team: str) -> None:
    print(f"❌ Invalid team name: {team} (allowed: PLTE or PL1–PL9)")


def print_invalid_birthday_format(raw: str) -> None:
    print(f"❌ Invalid birthday format: {raw} (use DD.MM.)")


def print_active_requires_bool() -> None:
    print("❌ --active expects true|false")


def print_leader_requires_bool() -> None:
    print("❌ --leader expects true|false")


def print_away_selector_required() -> None:
    print("❌ Provide one of --id, --name, --discord or use the short form with a term.")


def print_value_error(error: ValueError) -> None:
    print(f"❌ {error}")


def print_player_resolution_result(result: PlayerResolutionResult, term: str, *, print_when_ambiguous: bool = True) -> None:
    if result.status == "NOT_FOUND":
        print(f"❌ No players found matching '{term}'")
        return
    if result.status == "AMBIGUOUS" and print_when_ambiguous:
        print(f"⚠️  Term '{term}' is not unique. Matching players:")
        print_player_search_rows(result.matches or [])


def print_explicit_player_resolution_result(
    result: ExplicitPlayerResolutionResult,
    *,
    player_name: str | None = None,
    discord_name: str | None = None,
) -> None:
    if result.status == "INVALID_ID":
        print("❌ Invalid --id value")
        return
    if result.status == "DISCORD_NOT_FOUND":
        print(f"❌ No player found for discord_name='{discord_name}'")
        return
    if result.status == "DISCORD_AMBIGUOUS":
        print(f"⚠️ Multiple players match '{discord_name}'.")
        return
    if result.status == "NAME_AMBIGUOUS":
        print(f"⚠️ Multiple players match '{player_name}'.")
        return
    if result.status == "NOT_FOUND":
        print(f"❌ No players found matching '{player_name}'")
        return
    print("❌ Provide one of --id, --name, or --discord")


def print_grep_result(term: str, rows: list[PlayerSearchRow]) -> None:
    if not rows:
        print(f"❌ No players found matching '{term}'")
        return
    print_player_search_rows(rows)


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
