from __future__ import annotations

from collections.abc import Callable

from hcr2.models.matchscore import MatchScoreDetail, MatchScoreListRow
from hcr2.services.matchscores import AddScoreResult, DeleteScoreResult, EditScoreResult


MatchResultLoader = Callable[[int], tuple[int, int]]


def print_grouped_rows(
    rows: list[MatchScoreListRow],
    *,
    show_all: bool,
    match_filter: int | None,
    short: bool,
    match_result_loader: MatchResultLoader,
) -> None:
    if show_all or match_filter:
        group: list[MatchScoreListRow] = []
        current = None
        for row in rows:
            if current is None:
                current = row.match_id
            if row.match_id != current:
                print_score_block(group, include_pid=not short, include_result=not short, short=short, match_result_loader=match_result_loader)
                group = []
                current = row.match_id
            group.append(row)
        if group:
            print_score_block(group, include_pid=not short, include_result=not short, short=short, match_result_loader=match_result_loader)
        return
    print_score_block(rows, include_pid=not short, include_result=not short, short=short, match_result_loader=match_result_loader)


def print_score_block(
    block: list[MatchScoreListRow],
    *,
    include_pid: bool = False,
    include_result: bool = False,
    short: bool = False,
    match_result_loader: MatchResultLoader,
) -> None:
    match_id = block[0].match_id
    match_date = block[0].match_start
    opponent = block[0].opponent
    season_name = block[0].season_name

    if short:
        print(f"Match {match_id} – {opponent} | {match_date}")
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 34)
        for row in block:
            print(f"{row.id:<6} {row.player_name:<16.16} {row.score:>5} {row.points:>3}")
        print()
        return

    score_ladys = 0
    score_opponent = 0
    if include_result:
        score_ladys, score_opponent = match_result_loader(match_id)

    print(f"📊 Match {match_id} – {opponent} | {match_date} | Season {season_name}")
    if include_result and (score_ladys or score_opponent):
        emoji = "🏆" if score_ladys > score_opponent else ("😢" if score_ladys < score_opponent else "🤝")
        print(f"Result: {score_ladys} : {score_opponent} {emoji}")
    print()
    if include_pid:
        print(f"{'ID':<6} {'PID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 41)
        for row in block:
            print(f"{row.id:<6} {row.player_id:<6} {row.player_name:<16.16} {row.score:>5} {row.points:>3}")
    else:
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 34)
        for row in block:
            print(f"{row.id:<6} {row.player_name:<16.16} {row.score:>5} {row.points:>3}")
    print()


def print_deleted_score(row: MatchScoreDetail) -> None:
    print("OK DELETED:")
    print(
        f"ID={row.id} match={row.match_id} date={row.match_start} opp={row.opponent} "
        f"player={row.player_name} score={row.score} points={row.points} absent={int(row.absent or 0)} checkin={int(row.checkin or 0)}"
    )


def print_delete_result(result: DeleteScoreResult) -> None:
    if not result.row:
        print("⚠️ Not found.")
        return
    print_deleted_score(result.row)


def print_updated_score(row: MatchScoreDetail | None) -> None:
    if not row:
        print("OK UPDATED")
        return

    print("\nOK UPDATED:")
    print(f"Match {row.match_id} – {row.opponent} | {row.match_start}")
    print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3} {'Abs':>3} {'Cin':>3}")
    print("-" * 46)
    print(
        f"{row.id:<6} {row.player_name:<16.16} {row.score:>5} {row.points:>3} "
        f"{int(row.absent or 0):>3} {int(row.checkin or 0):>3}"
    )
    print()


def print_add_result(result: AddScoreResult, player_input: str) -> None:
    if result.status == "INVALID_RANGE":
        print("❌ Score or points out of valid range.")
        return
    if result.status == "PLAYER_NOT_FOUND":
        print(f"❌ No player found matching: {player_input}")
        return
    if result.status == "PLAYER_AMBIGUOUS":
        print(f"⚠️ Multiple players found for '{player_input}':")
        for player in result.player_resolution.matches:
            print(f"  ID {player.id}: {player.name} (alias: {player.alias})")
        return
    print(result.status)


def print_no_scores_found() -> None:
    print("⚠️ No scores found.")


def print_invalid_score_or_points() -> None:
    print("❌ Score or points out of valid range.")


def print_pid_requires_numeric() -> None:
    print("❌ --pid requires a numeric player_id.")


def print_edit_result(result: EditScoreResult) -> None:
    if result.status == "NOTHING_TO_UPDATE":
        print("⚠️ Nothing to update.")
        return
    if result.status == "NOT_FOUND":
        print("⚠️ Not found.")
        return
    if result.status == "PLAYER_NOT_FOUND":
        print(f"❌ Player id {result.player_id} does not exist.")
        return
    if result.status == "PLAYER_CLASH":
        print(
            f"❌ Cannot change player: entry already exists for match {result.match_id} and player {result.player_id} "
            f"(matchscore.id={result.clash_id})."
        )
        print("   Tip: delete or edit the existing entry first.")
        return
    if result.status == "SCORE_OUT_OF_RANGE":
        print("❌ Score out of range.")
        return
    if result.status == "POINTS_OUT_OF_RANGE":
        print("❌ Points out of range.")
        return

    print_updated_score(result.row)
