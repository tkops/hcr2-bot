"""Team screen video -> the PLTE player list.

The hard part is not reading the names, it is deciding what an unknown name means:
a genuinely new member, or someone who was in the team before under a name that has
since changed. With 600+ former players that is not a judgement to make silently, so
every addition has to carry an explicit decision (``new`` or ``reactivate``) before
anything is written - the service only proposes candidates.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path

from hcr2.models.roster import (
    PendingAddition,
    RosterCandidate,
    RosterChange,
    RosterPlan,
    RosterReading,
    RosterVideo,
)
from hcr2.repositories import players as player_repo
from hcr2.services import players as player_service
from hcr2.services.videos import TEAM_LOCAL_DIR, normalize_team_name


ROSTER_FILE = TEAM_LOCAL_DIR / "roster.json"

# Two names count as the same player above this, but only when no one else is that close.
NAME_MATCH_SIMILARITY = 0.7
# Candidates offered for an unknown name.
CANDIDATE_LIMIT = 5
CANDIDATE_MIN_SIMILARITY = 0.4
# One name fully inside the other - a shortened or extended name, not a coincidence.
CONTAINMENT_MIN_STEM = 4
CONTAINMENT_SCORE = 0.85
# Garage power moves by a few hundred between updates; this window makes a former
# player worth showing even when the name says nothing.
GP_CANDIDATE_WINDOW = 0.03

# Stored names have to be typeable on the German keyboard the team enters them with,
# so the reader transliterates before writing the file: £ -> J, π -> n, Ł -> L. Emoji
# and box drawing are dropped. Enforced here so the rule cannot quietly lapse.
TYPEABLE_EXTRA = "äöüÄÖÜßẞ€§°µ"

MAX_GARAGE_POWER = 50000
# A team does not lose a quarter of its members between two recordings - that is a
# misread list, not a mass exodus.
MAX_LEAVER_SHARE = 0.25


def untypeable_characters(name: str) -> list[str]:
    """Which characters of a name the team could not enter by hand."""
    return sorted({
        char for char in (name or "")
        if not (char.isascii() and char.isprintable()) and char not in TYPEABLE_EXTRA
    })


def roster_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else ROSTER_FILE


# -------------------- Reading the file --------------------

def load_readings(path: str | Path) -> tuple[RosterVideo | None, list[str]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"roster file not found: {path}"]
    except json.JSONDecodeError as e:
        return None, [f"roster file is not valid JSON: {e}"]
    except OSError as e:
        return None, [f"roster file unreadable: {type(e).__name__}: {e}"]

    if not isinstance(payload, dict):
        return None, ["roster file must contain one JSON object"]

    errors: list[str] = []
    raw_players = payload.get("players")
    if not isinstance(raw_players, list) or not raw_players:
        return None, ["players must be a non-empty list"]

    readings: list[RosterReading] = []
    for index, raw in enumerate(raw_players, start=1):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: not an object")
            continue
        name = str(raw.get("name") or "").strip()
        garage_power = _as_int(raw.get("garage_power"))
        if not name or garage_power is None:
            errors.append(f"row {index}: name and garage_power are required")
            continue
        readings.append(
            RosterReading(
                name=name,
                garage_power=garage_power,
                rank=_as_int(raw.get("rank")),
                leader=_as_int(raw.get("leader")),
                pid=_as_int(raw.get("pid")),
                reactivate=_as_int(raw.get("reactivate")),
                new=bool(raw.get("new")),
                note=str(raw.get("note") or ""),
            )
        )

    video = RosterVideo(
        players=readings,
        team=str(payload.get("team") or "").strip(),
        member_count=_as_int(payload.get("member_count")),
    )
    return video, errors


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace(".", "").replace(",", "").replace("_", "")
        if text.lstrip("-").isdigit():
            return int(text)
    return None


# -------------------- Matching --------------------

def _similarity(left: str, right: str) -> float:
    left_key, right_key = normalize_team_name(left), normalize_team_name(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return difflib.SequenceMatcher(None, left_key, right_key).ratio()


def match_reading(reading: RosterReading, players) -> tuple[object | None, str]:
    """Returns (player, how) - how in EXPLICIT / EXACT / FUZZY / AMBIGUOUS / NONE."""
    if reading.pid is not None:
        return next((p for p in players if p.id == reading.pid), None), "EXPLICIT"

    scored = [(_similarity(reading.name, player.name), player) for player in players]
    exact = [player for score, player in scored if score == 1.0]
    if len(exact) == 1:
        return exact[0], "EXACT"
    if len(exact) > 1:
        return None, "AMBIGUOUS"

    close = [(score, player) for score, player in scored if score >= NAME_MATCH_SIMILARITY]
    if len(close) == 1:
        return close[0][1], "FUZZY"
    if len(close) > 1:
        return None, "AMBIGUOUS"
    return None, "NONE"


def candidate_score(reading_name: str, player_name: str) -> float:
    """Containment beats the raw ratio: 'Bisa' inside 'BisaTheWise' is a shortened name,
    while three-letter leftovers score deceptively high on the ratio alone."""
    similarity = _similarity(reading_name, player_name)
    shorter, longer = sorted((normalize_team_name(reading_name), normalize_team_name(player_name)), key=len)
    if len(shorter) >= CONTAINMENT_MIN_STEM and shorter and shorter in longer:
        return max(similarity, CONTAINMENT_SCORE)
    return similarity


def find_candidates(reading: RosterReading, leaving=()) -> list[RosterCandidate]:
    """Everyone who could be this person.

    The players who vanished from the video come first and unconditionally: one leaver
    plus one arrival is what a rename looks like from the outside, and that pairing is
    far more likely than a random return out of 600 former members.
    """
    leaving_ids = {player.id for player in leaving}
    candidates = [
        RosterCandidate(
            player_id=player.id,
            name=player.name,
            team=player.team,
            active=player.active,
            garage_power=player.garage_power,
            similarity=candidate_score(reading.name, player.name),
        )
        for player in leaving
    ]
    candidates.sort(key=lambda c: (-c.similarity, abs(c.garage_power - reading.garage_power)))

    scored: list[RosterCandidate] = []
    for player in player_repo.list_players(sort_by="name"):
        if player.id in leaving_ids:
            continue
        similarity = candidate_score(reading.name, player.name)
        close_gp = (
            reading.garage_power > 0
            and player.garage_power > 0
            and abs(player.garage_power - reading.garage_power) <= reading.garage_power * GP_CANDIDATE_WINDOW
        )
        if similarity < CANDIDATE_MIN_SIMILARITY and not close_gp:
            continue
        scored.append(
            RosterCandidate(
                player_id=player.id,
                name=player.name,
                team=player.team,
                active=player.active,
                garage_power=player.garage_power,
                similarity=similarity,
            )
        )

    scored.sort(key=lambda c: (-c.similarity, abs(c.garage_power - reading.garage_power)))
    return candidates + scored[:CANDIDATE_LIMIT]


# -------------------- Plan --------------------

def build_plan(video: RosterVideo, *, force: bool = False) -> RosterPlan:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    readings = video.players
    if video.member_count is not None and video.member_count != len(readings):
        message = (
            f"the team screen says {video.member_count} members, but {len(readings)} rows were read "
            "- a row was missed"
        )
        (warnings if force else errors).append(message + (" [forced]" if force else ""))

    for reading in readings:
        if not 0 < reading.garage_power <= MAX_GARAGE_POWER:
            errors.append(f"{reading.name}: garage power {reading.garage_power} is not plausible")
        untypeable = untypeable_characters(reading.name)
        if untypeable:
            errors.append(
                f"'{reading.name}': {' '.join(untypeable)} cannot be typed on a German keyboard "
                "- transliterate the name before importing it"
            )

    active = list(player_repo.list_players(active_only=True, team_filter="PLTE", sort_by="name"))
    by_id = {player.id: player for player in active}

    changes: list[RosterChange] = []
    unmatched: list[RosterReading] = []
    matched_ids: set[int] = set()
    unchanged = 0

    for reading in readings:
        player, how = match_reading(reading, active)
        if how == "AMBIGUOUS":
            errors.append(f"{reading.name}: matches more than one active player - set \"pid\" explicitly")
            continue
        if how == "EXPLICIT" and player is None:
            errors.append(f"{reading.name}: pid {reading.pid} is not an active PLTE player")
            continue

        if player is None:
            unmatched.append(reading)
            continue

        if player.id in matched_ids:
            errors.append(f"{reading.name}: player {player.id} is claimed by two rows")
            continue
        matched_ids.add(player.id)

        touched = False
        if player.garage_power != reading.garage_power:
            if 0 < reading.garage_power < player.garage_power:
                notes.append(
                    f"{player.name} ({player.id}): garage power dropped "
                    f"{player.garage_power} → {reading.garage_power} - garage power normally only grows"
                )
            changes.append(RosterChange(
                kind="GP",
                name=player.name,
                player_id=player.id,
                detail=f"{player.garage_power} → {reading.garage_power}",
                reading_name=reading.name,
            ))
            touched = True

        if normalize_team_name(reading.name) != normalize_team_name(player.name):
            changes.append(RosterChange(
                kind="RENAME",
                name=player.name,
                player_id=player.id,
                detail=f"'{player.name}' → '{reading.name}'",
                reading_name=reading.name,
            ))
            touched = True

        if reading.leader is not None and int(bool(reading.leader)) != int(bool(player.is_leader)):
            notes.append(
                f"{player.name} ({player.id}): video shows "
                f"{'a leader role' if reading.leader else 'no leader role'}, database says the opposite "
                "- not changed here, use player edit --leader"
            )

        if not touched:
            unchanged += 1

    # Leavers first, then the candidate lists - who vanished is the best hint for who appeared.
    claimed = matched_ids | {r.reactivate for r in unmatched if r.reactivate is not None}
    leavers = [player for player in active if player.id not in claimed]
    pending = [_plan_addition(reading, leavers) for reading in unmatched]
    if leavers and len(leavers) > max(1, int(len(active) * MAX_LEAVER_SHARE)):
        message = (
            f"{len(leavers)} of {len(active)} active players are missing from the video "
            "- that looks like an incomplete reading, not a mass exit"
        )
        (warnings if force else errors).append(message + (" [forced]" if force else ""))

    for player in leavers:
        changes.append(RosterChange(
            kind="DEACTIVATE",
            name=player.name,
            player_id=player.id,
            detail=f"not in the video, garage power {player.garage_power}",
        ))

    for addition in pending:
        reading = addition.reading
        if reading.reactivate is not None:
            target = by_id.get(reading.reactivate)
            if target is not None:
                # Already in the team - the name simply moved too far for the matcher.
                changes.extend(_changes_for_renamed(target, reading))
                continue
            changes.append(RosterChange(
                kind="REACTIVATE",
                name=reading.name,
                player_id=reading.reactivate,
                detail=f"back in the team with garage power {reading.garage_power}",
                reading_name=reading.name,
            ))
        elif reading.new:
            changes.append(RosterChange(
                kind="ADD",
                name=reading.name,
                detail=f"new member with garage power {reading.garage_power}",
                reading_name=reading.name,
            ))

    undecided = [a for a in pending if a.reading.reactivate is None and not a.reading.new]
    if undecided:
        warnings.append(
            f"{len(undecided)} addition(s) still need a decision - new member or a returning one?"
        )

    status = "ERRORS" if errors else ("PENDING" if undecided else "READY")
    return RosterPlan(
        status=status,
        changes=changes,
        pending=undecided,
        errors=errors,
        warnings=warnings,
        notes=notes,
        unchanged=unchanged,
    )


def _plan_addition(reading: RosterReading, leavers=()) -> PendingAddition:
    if reading.reactivate is not None or reading.new:
        return PendingAddition(reading=reading, candidates=[])
    return PendingAddition(reading=reading, candidates=find_candidates(reading, leavers))


def _changes_for_renamed(player, reading: RosterReading) -> list[RosterChange]:
    changes = [RosterChange(
        kind="RENAME",
        name=player.name,
        player_id=player.id,
        detail=f"'{player.name}' → '{reading.name}'",
        reading_name=reading.name,
    )]
    if player.garage_power != reading.garage_power:
        changes.append(RosterChange(
            kind="GP",
            name=player.name,
            player_id=player.id,
            detail=f"{player.garage_power} → {reading.garage_power}",
            reading_name=reading.name,
        ))
    return changes


# -------------------- Apply --------------------

def apply_plan(plan: RosterPlan, video: RosterVideo) -> RosterPlan:
    """Only runs on a READY plan - a pending decision is a hard stop, by design."""
    if plan.status != "READY":
        return plan

    by_name = {normalize_team_name(reading.name): reading for reading in video.players}
    applied: list[RosterChange] = []

    for change in plan.changes:
        reading = by_name.get(normalize_team_name(change.reading_name or change.name))
        applied.append(_apply_change(change, reading))

    return RosterPlan(
        status="APPLIED",
        changes=applied,
        pending=[],
        errors=[c.detail for c in applied if c.status not in ("OK", "")],
        warnings=plan.warnings,
        notes=plan.notes,
        unchanged=plan.unchanged,
    )


def _apply_change(change: RosterChange, reading: RosterReading | None) -> RosterChange:
    def done(status: str, detail: str | None = None) -> RosterChange:
        return RosterChange(
            kind=change.kind,
            name=change.name,
            player_id=change.player_id,
            detail=detail if detail is not None else change.detail,
            status=status,
            reading_name=change.reading_name,
        )

    if change.kind == "GP" and reading is not None:
        result = player_service.edit_player(change.player_id, gp=reading.garage_power)
        return done("OK" if result.status == "UPDATED" else result.status)

    if change.kind == "RENAME" and reading is not None:
        result = player_service.edit_player(change.player_id, name=reading.name)
        return done("OK" if result.status == "UPDATED" else result.status)

    if change.kind == "DEACTIVATE":
        player_service.deactivate_player(change.player_id)
        return done("OK")

    if change.kind == "REACTIVATE" and reading is not None:
        player_service.activate_player(change.player_id)
        result = player_service.edit_player(
            change.player_id, name=reading.name, gp=reading.garage_power, team="PLTE"
        )
        return done("OK" if result.status in ("UPDATED", "NOTHING_TO_UPDATE") else result.status)

    if change.kind == "ADD" and reading is not None:
        result = player_service.add_player(name=reading.name, gp=reading.garage_power, team="PLTE")
        if result.status != "ADDED":
            return done(result.status)
        return RosterChange(
            kind="ADD",
            name=change.name,
            player_id=result.player_id,
            detail=f"{change.detail}, alias {result.alias}",
            status="OK",
        )

    return done("NO_READING", f"{change.detail} (no matching row in the roster file)")
