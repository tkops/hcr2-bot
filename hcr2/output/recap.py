"""The recap fact sheet.

English like the rest of `hcr2/output/`, and deliberately *not* post-ready: the German
team-chat text is written from this, not copied out of it.

**Nothing here says "she" or "he".** The team is called Power Ladys, but the roster is
mixed and the database records no gender - so every "her" in this sheet would be a guess
that the German text then repeats as fact, where article, pronoun and adjective all
carry it. `_print_wrapped`-style discipline is not enough for that; the wording has to
be neutral at the source, which is why the hints read "the player" and "their". Everything here is therefore
shown with its yardstick (20 of the last 20, 1.51x the team's pace), because a number
that arrives without one gets turned into prose that overstates it.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from hcr2.models.recap import MatchRecap
from hcr2.services import recap as recap_service


RESULT_LABELS = {"WIN": "WIN", "LOSS": "LOSS", "DRAW": "DRAW"}
REASON_LABELS = {
    "away": "away (excused)",
    "checkin": "checked in, did not drive",
    "no-show": "did not show up",
}


def print_no_match(match_id: int) -> None:
    print(f"❌ No match found for id {match_id}.")


def print_no_scores(match_id: int) -> None:
    print(f"❌ Match {match_id} has no results yet - nothing to recap.")
    print("   Read the video first: python3 hcr2.py video apply --match "f"{match_id}")


def print_json(recap: MatchRecap) -> None:
    print(json.dumps(asdict(recap), indent=2, ensure_ascii=False))


def print_recap(recap: MatchRecap) -> None:
    print(f"📋 Recap facts - match {recap.match_id}, season {recap.season_number}")
    event = f"{recap.event_name} ({recap.tracks} tracks)" if recap.tracks else recap.event_name
    print(f"   {event}, match {recap.position_in_event} of {recap.matches_in_event} in this event")
    verdict = RESULT_LABELS.get(recap.result, recap.result)
    print(
        f"   {recap.start} vs {recap.opponent}: "
        f"{recap.score_ladys} : {recap.score_opponent}  -> {verdict} by {recap.margin}"
    )
    print(f"   season so far: {recap.season_wins} wins in {recap.season_matches} matches")
    print()
    _print_participation(recap)
    _print_podium(recap)
    _print_improvements(recap)
    _print_records(recap)
    _print_event(recap)
    _print_opponent_history(recap)
    for note in recap.notes:
        print(f"⚠️  {note}")
    print()
    print("ℹ️  Facts, not a post: write the team-chat text from these, do not copy them.")


def _print_participation(recap: MatchRecap) -> None:
    print("👥 Participation")
    print(
        f"   {recap.drivers} of {recap.roster_rows} drove"
        + ("  - everybody drove" if recap.everyone_drove else "")
    )
    print(
        f"   team total {recap.total_score} | median {recap.median_score} | "
        f"best {recap.best_score}"
    )
    for reason in ("away", "checkin", "no-show"):
        names = [entry.name for entry in recap.absent if entry.reason == reason]
        if names:
            print(f"   {REASON_LABELS[reason]}: {', '.join(names)}")
    print()


def _print_podium(recap: MatchRecap) -> None:
    if not recap.podium:
        return
    print("🏆 Podium")
    for entry in recap.podium:
        line = f"   {entry.rank}. {entry.name:<18} {entry.score:>6} ({entry.points} pts)"
        print(line)
        print(f"      {_podium_context(entry)}")
        if entry.is_newcomer:
            print(
                f"      match {entry.matches_played + 1} for this player - say so, a podium this "
                f"early is the story"
            )
    print()


def _podium_context(entry) -> str:
    if entry.first_ever:
        return "first podium ever  <- say this"
    if not entry.window:
        return "no earlier matches to compare with"
    share = f"{entry.podiums_in_window} of the last {entry.window} matches"
    if entry.matches_since_last is None:
        return f"{share} - none in that window, the last one is further back  <- say this"
    gap = (
        "also on the podium in the match before"
        if entry.matches_since_last == 1
        else f"last time {entry.matches_since_last} matches ago"
    )
    # "Regular" is a fact about the list, never a label for the person: the name and
    # the score are the whole job, an epithet ("the usual two") reads as a dig.
    tail = "  <- say this" if entry.notable else "  (regular - name the player and the score, no label)"
    return f"{share}, {gap}{tail}"


def _print_improvements(recap: MatchRecap) -> None:
    print("📈 Improved on their own recent form (team pace already factored out)")
    if not recap.improvements:
        print("   nobody clearly above the team's pace this time")
        print()
        return
    for entry in recap.improvements:
        print(f"   {entry.name:<18} {entry.score:>6}  {entry.ratio:.2f}x team pace")
        place = (
            f"{entry.vs_match_median:+} vs this match's median"
            if entry.vs_match_median
            else "exactly at this match's median"
        )
        print(
            f"      averaged {entry.baseline} over the last {entry.basis_matches} matches, "
            f"{place}"
        )
    print()


def _print_records(recap: MatchRecap) -> None:
    if not recap.records:
        return
    print("🥇 Personal best")
    for entry in recap.records:
        print(
            f"   {entry.name:<18} {entry.score:>6}  beats the old best of {entry.previous_best} "
            f"({entry.matches_played} matches driven)"
        )
    print()


def _print_event(recap: MatchRecap) -> None:
    if len(recap.event_matches) < 2:
        return
    print("🗓  Same team event - the only place where score sums compare (same tracks)")
    for entry in recap.event_matches:
        verdict = "W" if entry.score_ladys > entry.score_opponent else (
            "L" if entry.score_ladys < entry.score_opponent else "D"
        )
        marker = "  <- this match" if entry.is_current else ""
        print(
            f"   {entry.match_id} {entry.start} {entry.opponent:<18} {verdict} "
            f"{entry.score_ladys:>4}:{entry.score_opponent:<4} sum {entry.total_score:>9} "
            f"{entry.drivers} drivers{marker}"
        )
    print()


def _print_opponent_history(recap: MatchRecap) -> None:
    if not recap.opponent_history:
        return
    print(f"🤝 Earlier meetings with {recap.opponent}")
    for entry in recap.opponent_history:
        verdict = "W" if entry.score_ladys > entry.score_opponent else (
            "L" if entry.score_ladys < entry.score_opponent else "D"
        )
        print(
            f"   {entry.start} {verdict} {entry.score_ladys}:{entry.score_opponent} "
            f"(match {entry.match_id})"
        )
    print()
