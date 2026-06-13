from __future__ import annotations

from hcr2.models.match import MatchDetail, MatchSummary
from hcr2.output.tables import print_table


def print_match_list(matches: list[MatchSummary], *, season_number: int | None, all_seasons: bool) -> None:
    print_table(
        headers=[f"{'ID':<5}", f"{'Start':<12}", f"{'Event':<30}", f"{'Opponent':<20}"],
        rows=[
            [f"{match.id:<5}", f"{match.start:<12}", f"{match.event_name:<30}", f"{match.opponent:<20}"]
            for match in matches
        ],
        width=75,
    )
    if not all_seasons:
        print(f"\n📊 {len(matches)} matches in Season {season_number}")


def print_match_detail(match: MatchDetail) -> None:
    print(f"📅 Match {match.id}")
    print(f"  Start:       {match.start}")
    print(f"  Season:      {match.season_number}")
    print(f"  Event:       {match.event_name}")
    print(f"  Opponent:    {match.opponent}")
    print(f"  Score Ladies: {match.score_ladys}")
    print(f"  Score Opp.:  {match.score_opponent}")

