"""Facts for the team-chat recap of a finished match.

The text itself is written by the model, on purpose: it goes into the team channel
after every match, and a template would read the same every time - the fifth identical
post is not read any more. What the model must not do is invent the substance, so
everything it may claim is computed here and handed over as numbers with their
yardstick attached.

Three of those yardsticks are not free choices:

* **A podium only says something next to how often that player stands there.** Some drive into
  the top three practically every match; naming that as a surprise every two days
  devalues the praise for the one who got there for the first time in months. Hence
  `podiums_in_window` and `RARE_PODIUM_SHARE`.
* **Improvement is measured against the team's pace**, as in [[interim]]: inside one
  team event the later matches run systematically better (median 1.04x the first), so
  measured against a flat 1.0 half the roster "improved".
* **Score sums compare only inside one team event.** Different events have different
  tracks - 2.27M team total in one, 1.62M in the next, with the same people driving.
  That is why `event_matches` carries the sums and nothing outside the event does.
"""
from __future__ import annotations

import statistics

from hcr2.models.recap import (
    AbsentEntry,
    EventMatch,
    ImprovementEntry,
    MatchRecap,
    OpponentMeeting,
    PodiumEntry,
    RecordEntry,
)
from hcr2.repositories import matches as match_repo
from hcr2.repositories import recap as recap_repo


# How far back "how often is this player up there" looks. Roughly two team events at four
# matches each plus the ones around them - long enough to tell a regular from a
# one-off, short enough that a roster change does not dominate it.
PODIUM_WINDOW = 20
# At or below this share of the window a podium is worth its own sentence. A quarter
# means: not one of the usual suspects.
RARE_PODIUM_SHARE = 0.25
# Her own recent form, the same basis the interim report uses.
IMPROVEMENT_BASIS = 5
# Fewer than this and the average is one good or bad day, not a form.
MIN_HISTORY = 3
# Below this many drivers the median of the ratios is guesswork - then no ratio is
# reported at all rather than a made-up one.
MIN_PACE_DRIVERS = 5
# Above the team's pace by this much is a run worth naming.
IMPROVEMENT_RATIO = 1.10
# Three names, as everywhere else: the text has to stay readable on a phone.
IMPROVEMENT_LIMIT = 3
# A newcomer sets a "personal best" in every one of their first matches, which says
# nothing. From this many driven matches on it does.
MIN_MATCHES_FOR_RECORD = 5
# Under this many matches a podium is worth saying out loud as what it is - somebody
# who just arrived. The text names the exact number anyway; this only decides whether
# it is worth a mention at all.
NEWCOMER_MATCHES = 5
# Earlier meetings with the same opponent, newest kept.
OPPONENT_HISTORY_LIMIT = 4


def build_recap(match_id: int) -> MatchRecap:
    match = match_repo.get_match(match_id)
    if match is None:
        return MatchRecap(status="NO_MATCH", match_id=match_id)

    rows = recap_repo.fetch_match_rows(match_id)
    if not rows:
        return MatchRecap(status="NO_SCORES", match_id=match_id)

    notes: list[str] = []
    driven = [row for row in rows if row[2] > 0]
    if not driven:
        return MatchRecap(status="NO_SCORES", match_id=match_id)

    absent = [
        AbsentEntry(player_id=pid, name=name, reason=_absence_reason(absent_flag, checkin))
        for pid, name, score, _points, absent_flag, checkin in rows
        if score <= 0
    ]

    scores = [row[2] for row in driven]
    previous = recap_repo.previous_match_ids(match.start, match_id, PODIUM_WINDOW)
    median_score = int(statistics.median(scores))

    # One query for both the podium context and the personal bests.
    bests = recap_repo.personal_bests(match.start, match_id)

    podium = _podium(driven, previous, start=match.start, match_id=match_id, bests=bests)
    improvements, pace = _improvements(
        driven, start=match.start, match_id=match_id, median_score=median_score
    )
    if pace is None:
        notes.append(
            "no team pace could be measured (too few drivers with history) - "
            "improvements are left out rather than guessed"
        )
    records = _records(driven, bests=bests)

    event_rows = recap_repo.event_matches(match.teamevent_id)
    event_matches = [
        EventMatch(
            match_id=row[0],
            start=row[1],
            opponent=row[2],
            score_ladys=row[3],
            score_opponent=row[4],
            total_score=row[5],
            drivers=row[6],
            is_current=row[0] == match_id,
        )
        for row in event_rows
    ]
    position = next((i for i, m in enumerate(event_matches, start=1) if m.is_current), len(event_matches))

    history = recap_repo.opponent_history(match.opponent, match_id)
    opponent_history = [
        OpponentMeeting(match_id=row[0], start=row[1], score_ladys=row[2], score_opponent=row[3])
        for row in history[-OPPONENT_HISTORY_LIMIT:]
    ]
    wins, played = recap_repo.season_record(match.season_number, match.start, match_id)

    if match.score_ladys == 0 and match.score_opponent == 0:
        notes.append("the match has no team scores yet - result and margin are unusable")

    return MatchRecap(
        status="OK",
        match_id=match_id,
        start=match.start,
        season_number=match.season_number,
        event_name=match.event_name,
        tracks=recap_repo.get_event_tracks(match.teamevent_id),
        opponent=match.opponent,
        score_ladys=match.score_ladys,
        score_opponent=match.score_opponent,
        result=_result(match.score_ladys, match.score_opponent),
        margin=abs(match.score_ladys - match.score_opponent),
        position_in_event=position,
        matches_in_event=len(event_matches),
        total_score=sum(scores),
        median_score=median_score,
        best_score=max(scores),
        roster_rows=len(rows),
        drivers=len(driven),
        everyone_drove=len(driven) == len(rows),
        absent=absent,
        podium=podium,
        improvements=improvements,
        records=records,
        event_matches=event_matches,
        opponent_history=opponent_history,
        season_wins=wins,
        season_matches=played,
        notes=notes,
    )


def _result(ladys: int, opponent: int) -> str:
    if ladys > opponent:
        return "WIN"
    if ladys < opponent:
        return "LOSS"
    return "DRAW"


def _absence_reason(absent_flag: int, checkin: int) -> str:
    """A checked-in no-show is not the same thing as an absence, and neither is a
    holiday - the text must be able to tell them apart before it praises anybody."""
    if absent_flag:
        return "away"
    if checkin:
        return "checkin"
    return "no-show"


def _podium(driven, previous_ids: list[int], *, start: str, match_id: int, bests: dict) -> list[PodiumEntry]:
    top = driven[: recap_repo.PODIUM_PLACES]
    if not top:
        return []
    player_ids = [row[0] for row in top]
    history = recap_repo.podium_by_match(previous_ids)
    ever = recap_repo.count_podiums_ever(player_ids, start, match_id)
    window = len(previous_ids)

    entries: list[PodiumEntry] = []
    for place, (pid, name, score, points, _absent, _checkin) in enumerate(top, start=1):
        hits = [i for i, mid in enumerate(previous_ids, start=1) if pid in history.get(mid, [])]
        share = (len(hits) / window) if window else 1.0
        played = bests.get(pid, (0, 0))[1]
        entries.append(
            PodiumEntry(
                rank=place,
                player_id=pid,
                name=name,
                score=score,
                points=points,
                podiums_in_window=len(hits),
                window=window,
                matches_since_last=hits[0] if hits else None,
                first_ever=ever.get(pid, 0) == 0,
                matches_played=played,
                is_newcomer=played < NEWCOMER_MATCHES,
                notable=share <= RARE_PODIUM_SHARE,
            )
        )
    return entries


def _improvements(driven, *, start: str, match_id: int, median_score: int):
    previous = recap_repo.previous_scores(start, match_id, IMPROVEMENT_BASIS)
    ratios: dict[int, tuple[float, int, int]] = {}
    for pid, _name, score, _points, _absent, _checkin in driven:
        history = previous.get(pid, [])
        if len(history) < MIN_HISTORY:
            continue
        baseline = int(statistics.mean(history))
        if baseline <= 0:
            continue
        ratios[pid] = (score / baseline, baseline, len(history))

    if len(ratios) < MIN_PACE_DRIVERS:
        return [], None

    pace = statistics.median(value[0] for value in ratios.values())
    if pace <= 0:
        return [], None

    names = {row[0]: row[1] for row in driven}
    scores = {row[0]: row[2] for row in driven}
    entries = [
        ImprovementEntry(
            player_id=pid,
            name=names[pid],
            score=scores[pid],
            baseline=baseline,
            basis_matches=count,
            ratio=ratio / pace,
            vs_match_median=scores[pid] - median_score,
        )
        for pid, (ratio, baseline, count) in ratios.items()
        if ratio / pace >= IMPROVEMENT_RATIO
    ]
    entries.sort(key=lambda entry: entry.ratio, reverse=True)
    return entries[:IMPROVEMENT_LIMIT], pace


def _records(driven, *, bests: dict) -> list[RecordEntry]:
    entries: list[RecordEntry] = []
    for pid, name, score, _points, _absent, _checkin in driven:
        best, played = bests.get(pid, (0, 0))
        if played >= MIN_MATCHES_FOR_RECORD and score > best:
            entries.append(
                RecordEntry(
                    player_id=pid, name=name, score=score, previous_best=best, matches_played=played
                )
            )
    entries.sort(key=lambda entry: entry.score - entry.previous_best, reverse=True)
    return entries
