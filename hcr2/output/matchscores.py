from __future__ import annotations

from collections.abc import Callable

from hcr2.models.matchscore import MatchScoreDetail, MatchScoreListRow


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
