"""Interim standings of a running match -> a report, never a database write.

The final-standings flow (``hcr2/services/videos.py``) exists to *record* a match. This
one exists to *act on it while it can still be changed*: who has not driven yet, who is
clearly stuck halfway, and - from the second match of a team event on - who improved and
who is still short of her own earlier run.

Nothing here writes. A 0/0 row from a running match would read as an unexcused no-show
everywhere afterwards (averages, `stats broom`), and the match totals in the header are
provisional. The countdown in the video header is carried through the reading as
``VideoResults.time_left`` so that `video apply` can refuse such a file as a final result.

Two numbers are measured against the live database, not chosen:

* Within one team event the later matches are *systematically better* - the median score
  of a player's second, third or fourth match is 1.04x her first, per-match medians run
  0.99..1.14 (8837 rows since 2025). So improvement has to be measured against the
  team's own pace; against a flat 1.0, "improved" would be half the roster.
* Against that pace, a completed run practically never falls below 0.6 (1.2 % of 1152
  rows, p1 = 0.58). Below that, something is wrong: a run broken off halfway, or - in a
  match still running - somebody who has barely started. Hence `ABORT_RATIO`.
"""
from __future__ import annotations

import statistics

from hcr2.models.video import InterimPlayer, InterimReport, VideoResults
from hcr2.repositories import matches as match_repo
from hcr2.repositories import matchscores as matchscore_repo
from hcr2.repositories import players as player_repo
from hcr2.services import matchscores as matchscore_service
from hcr2.services import videos as video_service


# A run that is going normally sits at the team's pace. 0.6 of it is the first value the
# live data calls unusual rather than merely weak.
ABORT_RATIO = 0.6
# Behind the team's pace, but not broken off - the "could still push" list.
BEHIND_RATIO = 0.9
# Below this many drivers the median pace is guesswork, so no ratio is reported at all.
MIN_PACE_DRIVERS = 5
# How many earlier scores a cross-event average needs to mean anything.
MIN_HISTORY = 3
# Der Bericht geht an die Teamleitung, nicht in ein Archiv: drei Namen pro Liste sind
# handhabbar, der Rest wird nur gezählt.
TOP_LIMIT = 3
# "Luft nach oben" ist die Liste, auf die die Leitung tatsächlich zugeht - deshalb nach
# Vorgabe der Teamleitung fünf Namen statt drei, und ohne Restzähler: wer hier noch nicht
# steht, ist ohnehin nicht der nächste Anruf, und die Zeile hat nur Platz gekostet.
BEHIND_LIMIT = 5
# Wer so wenige Matches gefahren hat, steht immer im Bericht - egal wie sie fährt.
NEWCOMER_MATCHES = 3


def build_report(results: VideoResults, *, match_id: int) -> InterimReport:
    match = match_repo.get_match(match_id)
    if match is None:
        return InterimReport(status="NO_MATCH", match_id=match_id)

    roster = video_service.get_roster(match_id) or []
    event_matches = match_repo.matches_in_teamevent(match.teamevent_id)
    position = next((i for i, m in enumerate(event_matches, start=1) if m.id == match_id), len(event_matches))

    warnings: list[str] = []
    errors: list[str] = []
    if results.match_id and results.match_id != match_id:
        errors.append(f"results file is for match {results.match_id}, not {match_id}")
    if not results.time_left:
        warnings.append(
            "no time_left in the reading - is this the final standings? then use 'video apply'"
        )

    verdict, _ = video_service.compare_opponent(results.opponent, match.opponent) if results.opponent else ("MATCH", 1.0)
    if verdict == "MISMATCH":
        errors.append(
            f"opponent '{results.opponent}' from the video is not match {match_id}'s opponent "
            f"'{match.opponent}' - wrong recording or wrong match id"
        )

    entries = {}
    for entry in results.entries:
        if entry.pid <= 0:
            # A row that could not be assigned: the video shows a name the roster does not
            # have. Dropping it silently would put the player it belongs to on the
            # "has not driven" list, so it is reported instead.
            warnings.append(
                f"unassigned row: '{entry.name or '?'}' with {entry.score} / {entry.points} points "
                "- rename or new member? Check with 'video player frames'"
            )
            continue
        if entry.pid in entries:
            warnings.append(f"player {entry.pid} appears more than once in the reading")
            continue
        entries[entry.pid] = entry

    history = matchscore_repo.scores_in_teamevent(match.teamevent_id, exclude_match_id=match_id)
    reference = "event" if position > 1 and history else "history"

    known = {player.id for player in roster}
    for pid in entries:
        if pid not in known:
            brief = player_repo.get_player_brief(pid)
            label = brief.name if brief is not None else "unknown player"
            warnings.append(f"{label} ({pid}) is in the reading but not on the active PLTE roster")

    measured: list[tuple[float, InterimPlayer]] = []
    not_driven: list[InterimPlayer] = []

    for player in roster:
        entry = entries.get(player.id)
        score = entry.score if entry is not None else 0
        if score <= 0:
            not_driven.append(InterimPlayer(
                pid=player.id,
                name=player.name,
                state=_state_of(player, match_id, match.start, checkin=bool(entry and entry.checkin)),
            ))
            continue

        base, label = _reference_for(player.id, history=history, reference=reference, match_id=match_id)
        if not base:
            measured.append((0.0, InterimPlayer(pid=player.id, name=player.name, score=score, state="driving")))
            continue
        measured.append((score / base, InterimPlayer(
            pid=player.id,
            name=player.name,
            score=score,
            base=base,
            base_label=label,
            state="driving",
        )))

    rated = [(raw, player) for raw, player in measured if raw > 0]
    pace = statistics.median(raw for raw, _ in rated) if len(rated) >= MIN_PACE_DRIVERS else None
    if pace is None and rated:
        warnings.append(
            f"only {len(rated)} of {len(measured)} drivers have a comparable earlier score - "
            "too few for a team pace, so no ratios are shown"
        )

    aborted: list[InterimPlayer] = []
    behind: list[InterimPlayer] = []
    improved: list[InterimPlayer] = []

    if pace:
        for raw, player in rated:
            ratio = raw / pace
            scored = InterimPlayer(
                pid=player.pid,
                name=player.name,
                score=player.score,
                base=player.base,
                base_label=player.base_label,
                ratio=ratio,
                state=player.state,
            )
            if ratio < ABORT_RATIO:
                aborted.append(scored)
            elif ratio < BEHIND_RATIO:
                behind.append(scored)
            elif reference == "event" and raw >= 1.0 and ratio > 1.0:
                # A huge gain over a base that was itself a broken-off run says "back to
                # normal", not "improved" - measured live, that is where a +274 % comes
                # from, from a base of 6.034. Praising that above someone who went
                # 48k -> 59k would be wrong, so it does not enter the list at all.
                if not _base_was_broken(player.pid, base=player.base, match_id=match_id):
                    improved.append(scored)

    aborted.sort(key=lambda p: p.ratio or 0)
    behind.sort(key=lambda p: p.ratio or 0)
    improved.sort(key=lambda p: p.ratio or 0, reverse=True)

    return InterimReport(
        status="OK",
        match_id=match_id,
        opponent=match.opponent,
        event_name=match.event_name,
        position=position,
        event_matches=len(event_matches),
        time_left=results.time_left,
        reference=reference,
        pace=pace,
        roster_size=len(roster),
        driven=len(measured),
        points_total=sum(entry.points for entry in results.entries),
        score_ladys=results.score_ladys,
        not_driven=not_driven,
        aborted=aborted[:TOP_LIMIT],
        aborted_more=max(0, len(aborted) - TOP_LIMIT),
        improved=improved[:TOP_LIMIT],
        behind=behind[:BEHIND_LIMIT],
        newcomers=_newcomers(roster, entries, match_id=match_id),
        warnings=warnings,
        errors=errors,
    )


def _newcomers(roster, entries: dict, *, match_id: int) -> list[InterimPlayer]:
    """Everybody inside her first `NEWCOMER_MATCHES` matches, driven or not.

    Not a judgement, a watch list: a new member is the one case where the leaders want
    to see the number even when nothing about it is unusual. She also has no score in
    this event to be measured against, so no other block would ever mention her.
    """
    counts = matchscore_repo.driven_counts(exclude_match_id=match_id)
    newcomers = []
    for player in roster:
        driven = counts.get(player.id, 0)
        if driven >= NEWCOMER_MATCHES:
            continue
        entry = entries.get(player.id)
        newcomers.append(InterimPlayer(
            pid=player.id,
            name=player.name,
            score=entry.score if entry is not None else 0,
            note=f"{driven + 1}. Match",
        ))
    return sorted(newcomers, key=lambda p: (-p.score, p.name))


def _base_was_broken(pid: int, *, base: int, match_id: int) -> bool:
    """Was the reference score itself far below what she usually drives?"""
    history = matchscore_repo.recent_scores(pid, exclude_match_id=match_id)
    if len(history) < MIN_HISTORY:
        return False
    average = sum(history) / len(history)
    return bool(average) and base < ABORT_RATIO * average


def _state_of(player, match_id: int, match_start: str, *, checkin: bool) -> str:
    """Why she has no score yet - and 'not yet' is the point: mid-match this is a
    reminder, not the no-show it would be in the final standings."""
    if video_service.joined_after_start(player.joined_at, match_start) and \
            not matchscore_repo.has_ever_driven(player.id):
        return "joined"
    if matchscore_service.compute_absent(match_id, player.id):
        return "away"
    if checkin:
        return "checkin"
    return "open"


def _reference_for(
    pid: int,
    *,
    history: dict[int, list[tuple[int, int]]],
    reference: str,
    match_id: int,
) -> tuple[int, str]:
    """Her own yardstick: the first match of this event she drove, or - in the event's
    first match - her recent cross-event average."""
    if reference == "event":
        rows = history.get(pid) or []
        if rows:
            match_id, score = rows[0]
            return score, f"Match {match_id}"
        return 0, ""

    scores = matchscore_repo.recent_scores(pid, exclude_match_id=match_id)
    if len(scores) < MIN_HISTORY:
        return 0, ""
    return round(sum(scores) / len(scores)), f"Schnitt aus {len(scores)}"
