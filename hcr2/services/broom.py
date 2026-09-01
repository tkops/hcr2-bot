"""Candidates for removal from the team, ranked.

The command computes, it does not decide - every number carries a readable reason
so the ranking can be argued with instead of merely believed.

Four ideas hold the model together:

- **Tenure protects at the top and accuses at the bottom.** Match count is almost the
  same thing as tenure here, so a plain penalty would put the five newest members on
  top of every list regardless of how they drive. Above ``PROBATION_MATCHES`` it is
  therefore a multiplier below 1 that can only ever lower a risk. Inside the first
  matches it is the opposite: a member still on probation has not earned any leeway,
  so the multiplier goes above 1 and a single unexcused absence is a veto. The window
  is deliberately short - at 13 driven matches a player is already out of it, so the
  failure mode of "the newest are always on top" cannot return.
- **Rates are shrunk toward the team rate - except on probation.** One unexcused
  absence out of seven matches is 14% and would beat every veteran; with ``SHRINKAGE``
  pseudo-observations it lands near the team average, which is what a sample that
  small actually tells us. For a player on probation that reasoning is inverted on
  purpose: over-reacting to the small sample *is* the policy, so she is measured raw.
- **A check-in no-show vetoes a newcomer and maxes out everybody else.** Logging into
  the event and not driving occupies a slot. It happens ~2.5 times a month across the
  whole roster, so as a purely weighted axis it would be zero for nearly everyone.
  Below ``NEWCOMER_MATCHES`` a single episode therefore ends the discussion. For an
  established player it does not: ``BLOCKER_FLOOR_EPISODES`` episodes force the
  reliability factor to its maximum, and the rest of the model - her contribution,
  her tenure shield - decides where that leaves her. A veteran who carries the team
  in points is not removed over two of these, and the model has to be able to say so.
- **Absolute contribution counts, not only the per-match comparison.** Measured on
  the live roster one player earned 56 event points from 38 driven matches (1.4 per
  match) while another brought 2682 from 32 (67.0) - driving every match badly is
  worth less to the team than driving well now and then. It is points per *roster*
  match rather than a plain sum, so a member who joined mid-window is not punished
  for the matches she could not be in, while absences still count as zero. The weight
  is deliberately modest: ``corr(points, perf) = 0.78``, so it largely restates the
  performance factor and must not count the same thing twice.
- **Performance is corrected for garage power, by the roster's own regression.**
  The slope is measured on every run rather than hardcoded, and it is small on its
  own (GP explains under 10% of the spread) - which is exactly the small share the
  correction should have, given that only *current* GP is known.
"""
from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import date

from hcr2.models.broom import (
    BroomCandidate,
    BroomFactor,
    BroomResult,
    BroomUnrated,
    BroomWindowRow,
    RosterMember,
)
from hcr2.repositories import broom as broom_repo
from hcr2.services.stats import is_unexcused_absence, linreg_slope, scaled_score


# --- window ----------------------------------------------------------------
WINDOW_MATCHES = 40          # ~10 weeks: enough for a trend, current enough for a kick
MIN_MATCHES = 10             # driven matches needed to be rated at all
MIN_TREND_MATCHES = 12       # a slope over fewer points is noise, not a trend
MIN_CONTRIBUTION_ROWS = 5    # fewer roster rows make the per-match figure noise

# --- rates -----------------------------------------------------------------
SHRINKAGE = 10               # pseudo-observations pulling small samples to the team rate
UNEXCUSED_SCALE = 0.10       # unexcused share that maxes the reliability factor
TREND_SCALE = 300.0          # slope (score per match) that maxes the trend factor
STALE_SCALE = 8              # own matches missed in a row that max the recency factor
DROP_THRESHOLD = 1000        # dip below one's own average that counts as a drop

# --- check-in no-shows -----------------------------------------------------
BLOCKER_WEIGHT = 2           # counts double inside the reliability factor
BLOCKER_EPISODE_DAYS = 4     # two events this close are one incident, not two
BLOCKER_FLOOR_EPISODES = 2   # this many max out reliability - but do not veto
NEWCOMER_MATCHES = 30        # below this, a single episode is an immediate case

# --- probation --------------------------------------------------------------
# The first matches for the team. Nothing has been earned yet, so nothing is
# forgiven: rated even below MIN_MATCHES, measured without shrinkage, and a single
# unexcused absence is a veto. A player who misses her very first match is out.
PROBATION_MATCHES = 10
PROBATION_PENALTY = 1.3

# --- returners ---------------------------------------------------------------
# Somebody who left and came back is loyal by the act of coming back, and she must
# not be read as a newcomer just because her window is thin. Told apart by history
# rather than by dates: matches driven *outside* the window. Measured on the live
# roster that separates the two groups perfectly - every newcomer has zero, every
# returner at least nineteen.
RETURNER_BONUS = 0.9

# --- weights ---------------------------------------------------------------
# Excused absence deliberately carries no weight: measured against the live roster it
# correlates with nothing (r = -0.03 against kilometres), so it says nothing about
# commitment - it is real life. It is still reported as context, marked as not counted.
# Every icon is a single codepoint with emoji presentation by default - no variation
# selectors, no ZWJ sequences, no skin tones. Those render inconsistently across
# clients, and a table that only lines up in some of them is worse than a plain one.
FACTORS: tuple[tuple[str, str, int, str, str], ...] = (
    ("reliability", "Zuv", 27, "unentschuldigtes Fehlen, Einloggen ohne Fahren zählt doppelt", "🚫"),
    ("motivation", "Mot", 18, "Kilometer pro Woche aus der Wochen-Truhe", "🚗"),
    ("drops", "Aus", 16, "Einbrüche unter den eigenen Schnitt, quadratisch gewichtet", "📉"),
    ("contribution", "Bei", 14, "Event-Punkte pro Kadermatch, Fehlen zählt als null", "🏆"),
    ("performance", "Lei", 11, "Score zum Match-Median, um die Garage Power korrigiert", "🎯"),
    ("trend", "Trd", 9, "Richtung der letzten Matches, fallend zählt schlecht", "📊"),
    ("recency", "Akt", 5, "eigene Matches in Folge nicht gefahren", "💤"),
)

LOYALTY_ICON = "⏳"       # Zugehörigkeit - the multiplier, not a factor
IMMEDIATE_ICON = "🔥"     # Sofortfall

# Wie ein Faktor im Satz heißt - die Spaltenköpfe sind zum Vorlesen zu kurz.
FACTOR_PHRASES = {
    "reliability": "Zuverlässigkeit",
    "motivation": "gefahrener Kilometer",
    "drops": "Einbrüchen unter den eigenen Schnitt",
    "contribution": "zu wenig eingefahrener Punkte",
    "performance": "Leistung zur Garage Power",
    "trend": "fallendem Trend",
    "recency": "nicht gefahrenen Matches",
}

# Multiplier by matches driven ever - the strongest single lever in the model, able
# to move a candidate several places on its own. Above 1 only inside probation.
LOYALTY_TIERS: tuple[tuple[int, float], ...] = ((50, 1.0), (150, 0.9), (300, 0.8), (500, 0.7))
LOYALTY_FLOOR = 0.6


def on_probation(driven_total: int) -> bool:
    return driven_total <= PROBATION_MATCHES


def is_returner(*, driven_total: int, window_driven: int, window_rows: int, window: int) -> bool:
    """History outside the window, and a real gap inside it.

    The second half is what keeps an established player out: her history is huge too,
    but she was on the roster for the whole window.
    """
    return (
        driven_total - window_driven >= MIN_MATCHES
        and window_rows <= window - MIN_MATCHES
    )


def loyalty_multiplier(driven_total: int) -> float:
    if on_probation(driven_total):
        return PROBATION_PENALTY
    for limit, factor in LOYALTY_TIERS:
        if driven_total < limit:
            return factor
    return LOYALTY_FLOOR


def blocker_episodes(dates: list[str]) -> int:
    """Check-in no-shows within ``BLOCKER_EPISODE_DAYS`` are one incident.

    Two consecutive matches are two rows but one weekend, and the real case this
    guards against is measurable: a founder with 782 driven matches had two of them
    two days apart and would otherwise be an immediate case.
    """
    episodes: list[date] = []
    for value in sorted(dates):
        try:
            day = date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            continue
        if episodes and (day - episodes[-1]).days <= BLOCKER_EPISODE_DAYS:
            continue
        episodes.append(day)
    return len(episodes)


def _percentile(value: float, values: list[float], *, low_is_worse: bool) -> float:
    """0..1 where 1 is the worst in the cohort.

    A cohort without spread carries no information, so it must land in the middle
    rather than at an extreme: counting "how many are below me" returns 0 for every
    member of a flat cohort, which through ``low_is_worse`` would score all of them
    as the worst in the team.
    """
    if len(values) < 2 or min(values) == max(values):
        return 0.5
    below = sum(1 for other in values if other < value) / (len(values) - 1)
    return (1.0 - below) if low_is_worse else below


def _gp_slope(points: list[tuple[int, float]]) -> tuple[float, float]:
    """Score per garage-power point, regressed on the current roster, plus the mean GP."""
    if len(points) < 3:
        return 0.0, (statistics.fmean(gp for gp, _ in points) if points else 0.0)

    gp_mean = statistics.fmean(gp for gp, _ in points)
    delta_mean = statistics.fmean(delta for _, delta in points)
    numerator = sum((gp - gp_mean) * (delta - delta_mean) for gp, delta in points)
    denominator = sum((gp - gp_mean) ** 2 for gp, _ in points)
    return (numerator / denominator if denominator else 0.0), gp_mean


class _Window:
    """Everything one player did inside the window."""

    def __init__(self) -> None:
        self.rows = 0
        self.points = 0
        self.unexcused = 0
        self.excused = 0
        self.blocker_dates: list[str] = []
        self.deltas: list[tuple[int, float]] = []   # (match order, delta to median)
        self.missed_since_driven: int | None = None

    @property
    def driven(self) -> int:
        return len(self.deltas)

    @property
    def available_rows(self) -> int:
        """Roster matches she could have driven - excused absences do not count.

        Without this the contribution factor smuggled excused absence back into the
        score through the back door: a player who signed off earned no points that
        evening, so the raw per-match figure punished her for being away with notice.
        Unexcused absences stay in the denominator, so ducking out still costs.
        """
        return self.rows - self.excused

    @property
    def points_per_row(self) -> float | None:
        """Event points per available match - what she brought the team per chance.

        Per match rather than as a plain sum, so somebody who joined mid-window is
        not punished for matches she could not be in.
        """
        if self.available_rows < MIN_CONTRIBUTION_ROWS:
            return None
        return self.points / self.available_rows

    @property
    def average_delta(self) -> float | None:
        return statistics.fmean(delta for _, delta in self.deltas) if self.deltas else None

    def semi_deviation(self) -> float | None:
        """Downside spread against one's own average - the drop measure.

        Only dips count, and they count quadratically, so one collapse weighs more
        than a handful of slightly weak evenings.
        """
        average = self.average_delta
        if average is None or self.driven < MIN_TREND_MATCHES:
            return None
        dips = [delta - average for _, delta in self.deltas if delta - average < -DROP_THRESHOLD]
        if not dips:
            return 0.0
        return (sum(dip * dip for dip in dips) / self.driven) ** 0.5

    def drops(self) -> tuple[int, float | None]:
        average = self.average_delta
        if average is None:
            return 0, None
        dips = [delta - average for _, delta in self.deltas if delta - average < -DROP_THRESHOLD]
        return len(dips), (min(dips) if dips else None)

    def trend_slope(self) -> float | None:
        if self.driven < MIN_TREND_MATCHES:
            return None
        # Window order counts down from the newest match, so oldest first is descending.
        chronological = [delta for _, delta in sorted(self.deltas, reverse=True)]
        return linreg_slope(chronological)


def _collect(rows: list[BroomWindowRow], order: dict[int, int]) -> dict[int, _Window]:
    windows: dict[int, _Window] = {}
    medians: dict[int, float] = {}
    scaled_by_match: dict[int, list[float]] = {}

    for row in rows:
        if row.score > 0:
            scaled_by_match.setdefault(row.match_id, []).append(scaled_score(row.score, row.tracks))
    for match_id, values in scaled_by_match.items():
        medians[match_id] = statistics.median(values)

    newest_driven: dict[int, int] = {}
    own_rows: dict[int, list[int]] = {}

    for row in rows:
        window = windows.setdefault(row.player_id, _Window())
        window.rows += 1
        window.points += row.points
        own_rows.setdefault(row.player_id, []).append(order[row.match_id])

        if row.score > 0:
            median = medians.get(row.match_id)
            if median is not None:
                window.deltas.append((order[row.match_id], scaled_score(row.score, row.tracks) - median))
            position = order[row.match_id]
            newest_driven[row.player_id] = min(newest_driven.get(row.player_id, position), position)
            continue

        if row.checkin == 1:
            window.blocker_dates.append(row.start)
        if row.absent:
            window.excused += 1
        elif is_unexcused_absence(row.score, row.points, row.absent):
            window.unexcused += 1

    for player_id, window in windows.items():
        last = newest_driven.get(player_id)
        if last is None:
            window.missed_since_driven = window.rows
        else:
            # Own matches newer than her last driven one - a returner who missed the
            # first half of the window is not stale, she simply was not here.
            window.missed_since_driven = sum(1 for position in own_rows[player_id] if position < last)

    return windows


def rank(*, window: int = WINDOW_MATCHES, include_leaders: bool = False) -> BroomResult:
    match_ids = broom_repo.window_match_ids(window)
    if not match_ids:
        return BroomResult(status="NO_MATCHES", window=window)

    roster = broom_repo.fetch_roster()
    if not roster:
        return BroomResult(status="NO_ROSTER", window=window, matches=len(match_ids))

    order = {match_id: index for index, match_id in enumerate(match_ids)}
    roster_ids = [member.player_id for member in roster]

    # Medians come from every PLTE driver in the match, leaders included - dropping
    # them from the cohort would shift the yardstick everyone is measured against.
    rows = broom_repo.fetch_window_rows(match_ids, roster_ids)
    windows = _collect(rows, order)

    km = broom_repo.fetch_km_averages(roster_ids)
    driven_totals = broom_repo.fetch_driven_totals(roster_ids)
    earlier_blockers = broom_repo.count_blockers_before(match_ids, roster_ids)

    km_ranking = sorted(
        (member.player_id for member in roster if km.get(member.player_id, (0.0, 0))[1] > 0),
        key=lambda player_id: km[player_id][0],
    )
    team_km = statistics.fmean([km[pid][0] for pid in km_ranking]) if km_ranking else 0.0

    # Every cohort statistic below - the GP regression, the percentiles, the team
    # rates - is computed over the whole roster, leaders included. Who gets *listed*
    # is a policy question; how garage power relates to score is not. Estimating the
    # slope without the leaders cut the high-GP end off the regression and flattened
    # it from 1.09 to 0.37 on the live roster.
    rated: list[RosterMember] = []
    cohort: list[RosterMember] = []     # stable population the yardsticks come from
    unrated: list[BroomUnrated] = []
    for member in roster:
        state = windows.get(member.player_id)
        # Everybody in the team gets judged. A thin window is a reason to look closer,
        # not a reason to defer - the noisy factors (trend, drops, contribution) opt
        # out on their own and their weight is redistributed. Only ``MIN_MATCHES``
        # players form the cohort, so a handful of matches never moves anybody else's
        # yardstick.
        if state is not None and state.rows >= 1:
            rated.append(member)
            if state.driven >= MIN_MATCHES:
                cohort.append(member)
            continue
        if member.is_leader and not include_leaders:
            continue
        unrated.append(
            BroomUnrated(
                player_id=member.player_id,
                name=member.name,
                window_driven=0,
                driven_total=driven_totals.get(member.player_id, 0),
                reason="keine Kaderzeile im Fenster",
            )
        )

    leaders_skipped = sum(1 for m in roster if m.is_leader) if not include_leaders else 0

    if not rated:
        return BroomResult(
            status="NO_DATA",
            window=window,
            matches=len(match_ids),
            unrated=unrated,
            leaders_skipped=leaders_skipped,
            team_km_average=team_km,
        )

    slope, gp_mean = _gp_slope(
        [(m.garage_power, windows[m.player_id].average_delta or 0.0) for m in cohort]
    )

    total_rows = sum(windows[m.player_id].rows for m in cohort)
    team_unexcused = sum(windows[m.player_id].unexcused for m in cohort) / total_rows if total_rows else 0.0

    def residual(member: RosterMember) -> float | None:
        average = windows[member.player_id].average_delta
        if average is None:
            return None
        return average - slope * (member.garage_power - gp_mean)

    residuals = {m.player_id: residual(m) for m in rated}
    deviations = {m.player_id: windows[m.player_id].semi_deviation() for m in rated}
    cohort_residuals = [residuals[m.player_id] for m in cohort if residuals[m.player_id] is not None]
    cohort_deviations = [deviations[m.player_id] for m in cohort if deviations[m.player_id] is not None]
    cohort_km = [km[m.player_id][0] for m in cohort if km.get(m.player_id, (0.0, 0))[1] >= 2]
    cohort_points = [
        windows[m.player_id].points_per_row
        for m in cohort
        if windows[m.player_id].points_per_row is not None
    ]
    points_ranking = sorted(
        (m.player_id for m in rated if windows[m.player_id].points_per_row is not None),
        key=lambda player_id: windows[player_id].points_per_row,
    )

    candidates: list[BroomCandidate] = []
    for member in rated:
        if member.is_leader and not include_leaders:
            continue
        state = windows[member.player_id]
        episodes = blocker_episodes(state.blocker_dates)
        km_average, km_weeks = km.get(member.player_id, (None, 0))
        driven_total = driven_totals.get(member.player_id, 0)

        probation = on_probation(driven_total)
        bad = state.unexcused + BLOCKER_WEIGHT * episodes
        if probation:
            # No shrinkage: over-reacting to the small sample is the point.
            reliability = min(1.0, bad / state.rows / UNEXCUSED_SCALE) if state.rows else 0.0
        else:
            reliability = min(
                1.0, (bad + SHRINKAGE * team_unexcused) / (state.rows + SHRINKAGE) / UNEXCUSED_SCALE
            )
        if episodes >= BLOCKER_FLOOR_EPISODES:
            # Repeated check-in no-shows max out the axis they belong to instead of
            # overriding the whole model - the rest of it still gets to speak.
            reliability = 1.0

        values: dict[str, float | None] = {
            "reliability": reliability,
            "performance": (
                _percentile(residuals[member.player_id], cohort_residuals, low_is_worse=True)
                if residuals[member.player_id] is not None and cohort_residuals
                else None
            ),
            "recency": min(1.0, (state.missed_since_driven or 0) / STALE_SCALE),
            "motivation": (
                _percentile(km_average, cohort_km, low_is_worse=True)
                if km_average is not None and km_weeks >= 2 and cohort_km
                else None
            ),
            "contribution": (
                _percentile(state.points_per_row, cohort_points, low_is_worse=True)
                if state.points_per_row is not None and cohort_points
                else None
            ),
            "drops": (
                _percentile(deviations[member.player_id], cohort_deviations, low_is_worse=False)
                if deviations[member.player_id] is not None and cohort_deviations
                else None
            ),
            "trend": None,
        }
        slope_own = state.trend_slope()
        if slope_own is not None:
            values["trend"] = max(0.0, min(1.0, -slope_own / TREND_SCALE + 0.5))

        factors = [
            BroomFactor(key=key, label=label, weight=weight, value=values[key])
            for key, label, weight, _, _ in FACTORS
        ]
        available = [factor for factor in factors if factor.rated]
        weight_sum = sum(factor.weight for factor in available)
        raw_risk = (
            sum(factor.value * factor.weight for factor in available) / weight_sum * 100.0
            if weight_sum
            else 0.0
        )
        returner = is_returner(
            driven_total=driven_total,
            window_driven=state.driven,
            window_rows=state.rows,
            window=len(match_ids),
        )
        loyalty = loyalty_multiplier(driven_total)
        if returner:
            loyalty *= RETURNER_BONUS
        drop_count, worst_drop = state.drops()

        candidates.append(
            BroomCandidate(
                player_id=member.player_id,
                name=member.name,
                garage_power=member.garage_power,
                risk=raw_risk * loyalty,
                raw_risk=raw_risk,
                loyalty=loyalty,
                driven_total=driven_total,
                window_rows=state.rows,
                window_driven=state.driven,
                unexcused=state.unexcused,
                excused=state.excused,
                blocker_episodes=episodes,
                blockers_earlier=earlier_blockers.get(member.player_id, 0),
                km_average=km_average,
                km_weeks=km_weeks,
                km_rank=(km_ranking.index(member.player_id) + 1) if member.player_id in km_ranking else None,
                performance=residuals[member.player_id],
                raw_delta=state.average_delta,
                points_total=state.points,
                points_per_row=state.points_per_row,
                points_rank=(
                    points_ranking.index(member.player_id) + 1
                    if member.player_id in points_ranking
                    else None
                ),
                drops=drop_count,
                worst_drop=worst_drop,
                matches_since_driven=state.missed_since_driven,
                probation=probation,
                returner=returner,
                immediate=(
                    (driven_total < NEWCOMER_MATCHES and episodes >= 1)
                    # Probation: missing a match before anything has been earned ends
                    # it. A member who ducks out of her very first match is out.
                    or (probation and state.unexcused >= 1)
                ),
                factors=factors,
                reasons=[],
            )
        )

    candidates = [
        _with_reasons(
            candidate,
            team_unexcused_rate=team_unexcused,
            team_km=team_km,
            roster_size=len(km_ranking),
            points_cohort=len(points_ranking),
        )
        for candidate in candidates
    ]

    # The veto ignores the loyalty shield on purpose: measured against the live roster
    # the one immediate case has the highest raw risk of all and would still land
    # sixth once her 536 matches are applied.
    immediate = sorted(
        (c for c in candidates if c.immediate),
        # Probation failures lead: there is no history to weigh against them and the
        # decision is the cheapest one on the list.
        key=lambda c: (not c.probation, -c.blocker_episodes, -c.raw_risk),
    )
    ranked = sorted((c for c in candidates if not c.immediate), key=lambda c: -c.risk)

    return BroomResult(
        status="OK",
        window=window,
        matches=len(match_ids),
        candidates=immediate + ranked,
        unrated=sorted(unrated, key=lambda u: u.window_driven),
        cohort_size=len(cohort),
        gp_slope=slope,
        team_unexcused_rate=team_unexcused,
        team_km_average=team_km,
        leaders_skipped=leaders_skipped,
    )


def _with_reasons(
    candidate: BroomCandidate,
    *,
    team_unexcused_rate: float,
    team_km: float,
    roster_size: int,
    points_cohort: int,
) -> BroomCandidate:
    """Turn the numbers into lines a leader can read out in a conversation.

    Deterministic on purpose - the same roster has to produce the same sentences,
    because "why was she not on the list last week?" has to have an answer.
    """
    reasons: list[str] = []

    if candidate.probation:
        reasons.append(
            f"Probezeit: erst {candidate.driven_total} Matches für das Team gefahren – "
            f"jede Schwäche zählt voll"
        )
    if candidate.probation and candidate.unexcused:
        reasons.append("in der Probezeit unentschuldigt gefehlt")
    if candidate.blocker_episodes:
        line = f"{candidate.blocker_episodes}x eingeloggt und nicht gefahren (Slot belegt)"
        if candidate.blocker_episodes >= BLOCKER_FLOOR_EPISODES and not candidate.immediate:
            line += " – Zuverlässigkeit dadurch voll ausgereizt"
        reasons.append(line)
    if candidate.blockers_earlier:
        reasons.append(
            f"{candidate.blockers_earlier}x das Gleiche früher, außerhalb des Fensters"
        )
    if candidate.unexcused:
        share = candidate.unexcused / candidate.window_rows * 100 if candidate.window_rows else 0.0
        reasons.append(
            f"{candidate.unexcused}x unentschuldigt in {candidate.window_rows} Matches = "
            f"{share:.1f}% (Team {team_unexcused_rate * 100:.1f}%)"
        )
    if candidate.window_rows and candidate.excused >= candidate.window_rows * 0.10:
        share = candidate.excused / candidate.window_rows * 100
        reasons.append(
            f"{candidate.excused}x entschuldigt abwesend ({share:.0f}% des Fensters, zählt nicht)"
        )
    if (
        candidate.km_average is not None
        and candidate.km_weeks >= 2
        and team_km > 0
        and candidate.km_average < team_km * 0.6
    ):
        place = f", Platz {candidate.km_rank}/{roster_size}" if candidate.km_rank else ""
        reasons.append(
            f"{candidate.km_average:.0f} km/Woche{place} im Kader (Ø {team_km:.0f})"
        )
    if candidate.points_per_row is not None:
        place = f", Platz {candidate.points_rank}/{points_cohort}" if candidate.points_rank else ""
        contribution = next(
            (f.value for f in candidate.factors if f.key == "contribution"), None
        )
        if contribution is not None and contribution >= 0.65:
            reasons.append(
                f"{candidate.points_total} Punkte = {candidate.points_per_row:.1f} "
                f"pro Kadermatch{place}"
            )
        elif contribution is not None and contribution <= 0.35:
            # The same line has to be able to speak for her: this is the number that
            # says a veteran carries the team even when she misses matches.
            reasons.append(
                f"trägt überdurchschnittlich: {candidate.points_total} Punkte "
                f"= {candidate.points_per_row:.1f} pro Kadermatch{place}"
            )
    if candidate.performance is not None and candidate.raw_delta is not None:
        if candidate.performance < -3000:
            reasons.append(
                f"{candidate.performance / 1000:+.1f}k unter Kadererwartung für "
                f"{candidate.garage_power} GP (roh {candidate.raw_delta / 1000:+.1f}k)"
            )
        elif candidate.raw_delta < -3000:
            reasons.append(
                f"{candidate.raw_delta / 1000:+.1f}k zum Match-Median, durch GP erklärt "
                f"({candidate.performance / 1000:+.1f}k bereinigt)"
            )
    if candidate.drops >= 3 and candidate.worst_drop is not None:
        reasons.append(
            f"{candidate.drops} Einbrüche unter den eigenen Schnitt, "
            f"tiefster {candidate.worst_drop / 1000:.1f}k"
        )
    if candidate.matches_since_driven and candidate.matches_since_driven >= 3:
        reasons.append(
            f"seit {candidate.matches_since_driven} eigenen Matches nicht gefahren"
        )
    if candidate.returner:
        outside = candidate.driven_total - candidate.window_driven
        reasons.append(
            f"Rückkehrerin: {outside} Matches vor dieser Zeit gefahren, "
            f"nur {candidate.window_rows} im Fenster im Kader"
        )
    if candidate.loyalty < 1.0:
        reasons.append(
            f"{candidate.driven_total} Matches für das Team gefahren -> "
            f"Schutz x{candidate.loyalty:.2f}"
        )
    elif candidate.loyalty > 1.0:
        reasons.append(f"kein Schutz durch Zugehörigkeit -> Aufschlag x{candidate.loyalty:.2f}")

    if not reasons:
        # Nothing crossed a reporting threshold, yet she is on the list - then the
        # list itself is the statement, and the strongest factor has to be named.
        # A name with an empty block below it reads as a bug.
        rated = [factor for factor in candidate.factors if factor.rated]
        if rated:
            worst = max(rated, key=lambda factor: factor.value * factor.weight)
            reasons.append(
                f"nichts sticht heraus – gelistet wegen {FACTOR_PHRASES[worst.key]} "
                f"mit {worst.value * 100:.0f} von 100"
            )

    return replace(candidate, reasons=reasons)
