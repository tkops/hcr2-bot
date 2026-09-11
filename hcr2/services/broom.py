"""Candidates for removal from the team, ranked.

The command computes, it does not decide - every number carries a readable reason so
the ranking can be argued with instead of merely believed. Two steps, and deliberately
no more than two: the leadership has to be able to say in one sentence why somebody is
being let go.

1. **The pool.** Anyone who missed a match unexcused in the season is in, no matter how
   well she drives - missing without a word is the one mistake that is not negotiated.
   The rest is filled up to ``SHORTLIST_SIZE`` with the weakest drivers of the season,
   measured as the plain distance to the match median over the matches she actually
   drove. The pool can therefore grow past that size: it is a target for the filling,
   not a cap on the absences.
2. **The ranking inside it.** Exactly two things: kilometres from the weekly chest and
   tenure, the latter as the ``loyalty`` multiplier rather than as a weighted axis.
   Reliability and performance are absent on purpose - they filled the pool and must
   not count a second time.

Everything else the model knows - drops, check-in no-shows, excused absence, points -
survives as a **reason line**, not as a weight: explaining yes, scoring no. A number
that moves the ranking has to be one the leadership can defend in the conversation
afterwards, and that is what keeps the model this small.

- **Tenure lowers a risk by a fixed number of points, never by a percentage.** A
  multiplier ties the bonus to how badly somebody scores rather than to how long she has
  been around: on the live list a player with 304 matches was handed 16.4 points while
  one with 493 got 14.8, and the weakest player of the pool collected the largest bonus
  of all. A flat discount depends on tenure alone - and it can be said out loud:
  "your 776 matches are worth 16 points off".
- **Immediate cases stand beside the pool, not in it.** Nothing is weighed up about
  them any more, so they are not ranked against anybody - but they are shown, because
  the seat they free counts towards the target.
- **A check-in no-show is logging into the event and not driving**, which occupies a
  slot. Below ``NEWCOMER_MATCHES`` driven matches a single episode ends the discussion;
  for an established player it is a reason line and nothing else.
"""
from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import date, timedelta

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


# --- shortlist --------------------------------------------------------------
# Zwei Stufen: erst der Topf, dann die Reihung darin. Der Topf ist rein die Leistung
# der Saison - wer dem Team am wenigsten einfährt. Innerhalb des Topfes entscheiden
# Zuverlässigkeit, Motivation und Zugehörigkeit, denn zwischen zwei schwachen
# Spielerinnen ist das der Unterschied, über den man wirklich redet.
SHORTLIST_SIZE = 10
# Ein volles Team hat TEAM_CAPACITY Plätze, und die Leitung will am Saisonende
# TARGET_FREE_SLOTS davon frei haben. Fehlen schon Leute, müssen entsprechend weniger
# gehen: bei 48 Spielerinnen sind es drei, nicht fünf.
TEAM_CAPACITY = 50
TARGET_FREE_SLOTS = 5

# --- window ----------------------------------------------------------------
# A season is the default window, because a season is the unit the decision is made
# in: at the end of one, five players are let go, and evidence from the season before
# is not what that decision is about. Measured on the live roster a season holds 14-15
# matches, and 46 of 50 members drive at least twelve of them - so the thresholds
# below still have their sample, with none of the noise a fixed count drags in from
# an older season. WINDOW_MATCHES stays as the explicit cross-season view (--last).
WINDOW_MATCHES = 40          # ~10 weeks: enough for a trend, current enough for a kick
MIN_MATCHES = 10             # driven matches that make a player part of the cohort
COHORT_SHARE = 0.7           # Anteil des Fensters, der für die Kohorte reicht
MIN_CONTRIBUTION_ROWS = 5    # fewer roster rows make the per-match figure noise

# --- rates -----------------------------------------------------------------
# Unentschuldigtes Fehlen wird nicht mehr zu einer Quote verrechnet: es ist die
# Eintrittskarte in den Topf, und zwar ab dem ersten Mal. Damit sind Shrinkage und
# eine Zuverlässigkeits-Skala hinfällig - was sie austarierten, ist jetzt eine
# Ja/Nein-Frage.
DROP_THRESHOLD = 1000        # dip below one's own average that counts as a drop
# Fehltermine, die den Zuverlässigkeitsfaktor ausreizen. Gezählt wird die Anzahl, nicht
# eine Quote: alle im Topf messen sich an derselben Saison, und "dreimal unentschuldigt
# gefehlt" ist ein Satz, den man in einem Gespräch sagen kann - "14,3 % Fehlquote gegen
# eine Teamquote von 1,5 %" ist keiner.
UNEXCUSED_CAP = 3

# --- check-in no-shows -----------------------------------------------------
BLOCKER_EPISODE_DAYS = 4     # two events this close are one incident, not two
NEWCOMER_MATCHES = 30        # below this, a single episode is an immediate case

# --- probation --------------------------------------------------------------
# The first matches for the team. Nothing has been earned yet, so nothing is forgiven:
# a single unexcused absence is an immediate case rather than a pool ticket.
#
# She gets **no protection, but no surcharge either** (multiplier exactly 1.0). It used
# to be 1.3, which worked while reliability, drops and trend were weighted axes that
# could speak for a clean newcomer. With the ranking down to kilometres and tenure the
# surcharge became almost the only difference between two players, and a spotless
# newcomer landed above an established player with three unexcused absences - exactly
# the failure mode the protective multiplier exists to prevent. The sharpness of
# probation lives in the immediate-case rule now, where it can be explained.
PROBATION_MATCHES = 10
PROBATION_DISCOUNT = 0

# --- returners ---------------------------------------------------------------
# Somebody who left and came back is loyal by the act of coming back, and she must
# not be read as a newcomer just because her window is thin. Told apart by history
# rather than by dates: matches driven *outside* the window. Measured on the live
# roster that separates the two groups perfectly - every newcomer has zero, every
# returner at least nineteen.
RETURNER_DISCOUNT = 3        # Zusatzabzug, in derselben Einheit wie LOYALTY_TIERS

# --- weights ---------------------------------------------------------------
# Excused absence deliberately carries no weight: measured against the live roster it
# correlates with nothing (r = -0.03 against kilometres), so it says nothing about
# commitment - it is real life. It is still reported as context, marked as not counted.
# Every icon is a single codepoint with emoji presentation by default - no variation
# selectors, no ZWJ sequences, no skin tones. Those render inconsistently across
# clients, and a table that only lines up in some of them is worse than a plain one.
# **Vier Dinge reihen den Topf**, und mehr sollen es nicht werden - der Grund ist nicht
# Sparsamkeit, sondern das Gespräch danach: ein Rauswurf muss in einem Satz begründbar
# sein. Drei davon sind gewichtete Achsen, die vierte ist die Zugehörigkeit als
# Multiplikator ``loyalty``, weil sie ein Risiko nur senken können soll.
#
# Zuverlässigkeit und Leistung zählen hier, obwohl sie auch den Topf füllen. Das ist
# Absicht: der Eintritt ist eine Ja/Nein-Frage (einmal gefehlt, oder unter den
# Schwächsten), die Reihung eine Wie-stark-Frage. Ohne sie wären drei unentschuldigte
# Fehltermine und einer gleichwertig, und die Schwächste des Kaders stünde unter einer,
# die nur mehr Kilometer fährt.
#
# Alles andere (Einbrüche, Check-in-No-Shows, Beitrag, entschuldigtes Fehlen) ist
# Begründungszeile geblieben, aber reiht nicht mit: erklären ja, mitrechnen nein.
# Die Spaltenköpfe sind **Wörter, keine Emoji**. Ein Emoji ist zwei Anzeigespalten
# breit, für ``len()`` aber ein Zeichen, und je nach Discord-Client rendert es mal so
# mal so - eine Tabelle, die nur manchmal ausgerichtet ist, ist schlechter als eine
# ohne Symbole. "Fehlt / Perf / km / Matches" sagt außerdem direkt, was in der Spalte
# steht, und die Spalten tragen seit 1.18 die echten Werte statt Perzentile.
FACTORS: tuple[tuple[str, str, int, str], ...] = (
    ("reliability", "Fehlt", 35, "unentschuldigte Fehltermine der Saison"),
    ("performance", "Perf", 35, "Score zum Match-Median, nur gefahrene Matches"),
    ("motivation", "km", 30, "Kilometer im Zeitraum, gesamt"),
)

FACTOR_LABELS = {key: label for key, label, _, _ in FACTORS}
FACTOR_WEIGHTS = {key: weight for key, _, weight, _ in FACTORS}

LOYALTY_LABEL = "Matches"   # Zugehörigkeit - the multiplier, not a factor
IMMEDIATE_ICON = "🔥"       # Sofortfall - keine Tabellenspalte, daher unkritisch

# Wie ein Faktor im Satz heißt - die Spaltenköpfe sind zum Vorlesen zu kurz.
FACTOR_PHRASES = {
    "reliability": "unentschuldigten Fehlens",
    "performance": "Leistung zum Match-Median",
    "motivation": "gefahrener Kilometer",
}

# Punkte, die die Zugehörigkeit vom Risiko abzieht, gestaffelt nach gefahrenen
# Matches. **Additiv, nicht multiplikativ** - und das ist der Punkt: ein Faktor wirkt
# prozentual, also hing der Bonus daran, wie schlecht jemand dasteht, statt daran, wie
# lange sie dabei ist. An der echten Liste bekam eine Spielerin mit 304 Matches 16,4
# Punkte geschenkt und eine mit 493 nur 14,8, weil deren Rohrisiko niedriger war; und
# die in allen drei Achsen Schwächste kassierte mit 29,7 Punkten den größten Bonus
# überhaupt. Ein fester Abzug hängt allein an der Zugehörigkeit - und ist ein Satz, den
# man in einem Gespräch sagen kann: "deine 776 Matches bringen dir 16 Punkte Abzug".
LOYALTY_TIERS: tuple[tuple[int, int], ...] = ((50, 0), (150, 4), (300, 8), (500, 12))
LOYALTY_MAX = 16


def cohort_threshold(window: int) -> int:
    """Gefahrene Matches, ab denen eine Spielerin den Maßstab mitbestimmt.

    ``MIN_MATCHES`` ist auf eine volle Saison gemünzt. In einer **laufenden** Saison
    kann die Zahl niemand erreichen - nach vier Matches wäre die Kohorte leer, jeder
    Perzentilfaktor unbewertet und die Rangliste eine alphabetische Liste mit lauter
    Nullen. Deshalb ist die Schwelle ein Anteil des Fensters, gedeckelt auf
    ``MIN_MATCHES``: bei 15 Matches bleibt es bei 10 wie bisher, bei 4 sind es 3.
    """
    if window <= 0:
        return MIN_MATCHES
    return max(1, min(MIN_MATCHES, round(window * COHORT_SHARE)))


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


def loyalty_discount(driven_total: int) -> int:
    """Punkte, die die Zugehörigkeit vom Rohrisiko abzieht."""
    if on_probation(driven_total):
        return PROBATION_DISCOUNT
    for limit, discount in LOYALTY_TIERS:
        if driven_total < limit:
            return discount
    return LOYALTY_MAX


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


def window_weeks(first_day: str, last_day: str) -> list[tuple[int, int]]:
    """The ISO weeks whose Thursday falls inside the period.

    Thursday is the ISO anchor day: it decides which year - and here which season - a
    week belongs to, so a week straddling the turn of the month lands in exactly one
    of the two instead of counting for both. Measured on the live seasons that comes
    out gapless and overlap-free: season 63 ends at week 31, season 64 starts at 32.
    """
    start = date.fromisoformat(first_day[:10])
    end = date.fromisoformat(last_day[:10])
    weeks: list[tuple[int, int]] = []
    day = start
    while day <= end:
        iso = day.isocalendar()
        thursday = date.fromisocalendar(iso.year, iso.week, 4)
        if start <= thursday <= end and (iso.year, iso.week) not in weeks:
            weeks.append((iso.year, iso.week))
        day += timedelta(days=1)
    return weeks


def _km_weeks(season: int | None, match_ids: list[int]) -> list[tuple[int, int]]:
    """The kilometre weeks the window covers.

    One rule, two shapes of window: a season is bounded by the season table, a
    ``--last`` run by its oldest and newest match. Either way the kilometres come from
    the period being judged and from nowhere else.
    """
    bounds = broom_repo.season_bounds(season) if season is not None else None
    if bounds is None:
        # Auch der Saisonmodus landet hier, wenn die Saisonzeile fehlt - die Matches
        # sind dann der einzige Beleg dafür, welcher Zeitraum gemeint war.
        bounds = broom_repo.match_bounds(match_ids)
    return window_weeks(*bounds) if bounds else []


def _fills_the_pool(candidate: BroomCandidate) -> bool:
    """Ob eine Spielerin für den Leistungstopf in Frage kommt.

    Ohne eine gefahrene Zeile gibt es keine Leistung zu messen, und sie stünde allein
    deshalb an der Spitze. Bei einer durchgehend abgemeldeten Spielerin wäre das
    entschuldigtes Fehlen als Vorwurf - im ganzen Modell ist es ausdrücklich keiner.
    War sie dagegen unentschuldigt weg oder hat einen Slot belegt, ohne zu fahren,
    hat sie dem Team nichts eingebracht und gehört nach vorn.
    """
    if candidate.raw_delta is not None:
        return True
    return candidate.unexcused > 0 or candidate.blocker_episodes > 0


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

    def drops(self) -> tuple[int, float | None]:
        average = self.average_delta
        if average is None:
            return 0, None
        dips = [delta - average for _, delta in self.deltas if delta - average < -DROP_THRESHOLD]
        return len(dips), (min(dips) if dips else None)



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


def rank(
    *,
    season: int | None = None,
    window: int | None = None,
    include_leaders: bool = False,
) -> BroomResult:
    """Rank the roster over one season, or over ``window`` matches if one is given.

    ``window`` wins when both are passed - it is the explicit request for the
    cross-season view, while the season is what you get by not asking.
    """
    if window is not None:
        match_ids = broom_repo.window_match_ids(window)
        season = None
    else:
        if season is None:
            season = broom_repo.current_season()
        match_ids = broom_repo.season_match_ids(season) if season is not None else []
        # The window is what the data turned out to be, not what was asked for - every
        # size-dependent rule below (is_returner above all) has to see the real count.
        window = len(match_ids)

    if not match_ids:
        return BroomResult(status="NO_MATCHES", window=window, season=season)

    roster = broom_repo.fetch_roster()
    if not roster:
        return BroomResult(
            status="NO_ROSTER", window=window, season=season, matches=len(match_ids)
        )

    order = {match_id: index for index, match_id in enumerate(match_ids)}
    roster_ids = [member.player_id for member in roster]
    min_cohort_matches = cohort_threshold(len(match_ids))

    # Medians come from every PLTE driver in the match, leaders included - dropping
    # them from the cohort would shift the yardstick everyone is measured against.
    rows = broom_repo.fetch_window_rows(match_ids, roster_ids)
    windows = _collect(rows, order)

    km = broom_repo.fetch_km_for_weeks(roster_ids, _km_weeks(season, match_ids))
    # Die Wochen, für die es Zahlen *gibt*, nicht die, die das Fenster breit ist: die
    # Truhe wird erst seit KW 33 gelesen, und "aus 4 Wochen" wäre dann eine Behauptung
    # über Daten, die niemand eingetragen hat.
    km_weeks_read = max((weeks for _, weeks, _ in km.values()), default=0)
    driven_totals = broom_repo.fetch_driven_totals(roster_ids)
    earlier_blockers = broom_repo.count_blockers_before(match_ids, roster_ids)

    km_ranking = sorted(
        (member.player_id for member in roster if km.get(member.player_id, (0.0, 0, 0))[1] > 0),
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
            if state.driven >= min_cohort_matches:
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
            season=season,
            km_weeks=km_weeks_read,
            matches=len(match_ids),
            unrated=unrated,
            leaders_skipped=leaders_skipped,
            team_km_average=team_km,
        )

    total_rows = sum(windows[m.player_id].rows for m in cohort)
    team_unexcused = sum(windows[m.player_id].unexcused for m in cohort) / total_rows if total_rows else 0.0

    # Leistung ist der rohe Abstand zum Match-Median. Die Garage Power wird bewusst
    # nicht mehr herausgerechnet: für einen freien Platz zählt, was eine Spielerin dem
    # Team einbringt, nicht ob ihre Ausrüstung mehr hergegeben hätte. An der echten
    # Saison 64 änderte die Korrektur ohnehin nur eine von zehn Personen im Topf.
    residuals = {m.player_id: windows[m.player_id].average_delta for m in rated}
    cohort_residuals = [
        residuals[m.player_id] for m in cohort if residuals[m.player_id] is not None
    ]
    cohort_km = [km[m.player_id][0] for m in cohort if km.get(m.player_id, (0.0, 0, 0))[1] >= 1]
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
        km_average, km_weeks, km_total = km.get(member.player_id, (None, 0, 0))
        driven_total = driven_totals.get(member.player_id, 0)

        probation = on_probation(driven_total)

        values: dict[str, float | None] = {
            "reliability": min(1.0, state.unexcused / UNEXCUSED_CAP),
            "performance": (
                _percentile(residuals[member.player_id], cohort_residuals, low_is_worse=True)
                if residuals[member.player_id] is not None and cohort_residuals
                else None
            ),
            "motivation": (
                _percentile(km_average, cohort_km, low_is_worse=True)
                if km_average is not None and km_weeks >= 1 and cohort_km
                else None
            ),
        }

        factors = [
            BroomFactor(key=key, label=label, weight=weight, value=values.get(key))
            for key, label, weight, _ in FACTORS
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
        discount = loyalty_discount(driven_total)
        if returner:
            discount += RETURNER_DISCOUNT
        drop_count, worst_drop = state.drops()

        candidates.append(
            BroomCandidate(
                player_id=member.player_id,
                name=member.name,
                garage_power=member.garage_power,
                # Nie unter null: ein Abzug soll schützen, keine negativen Risiken
                # erzeugen, die sich nicht mehr sinnvoll vergleichen lassen.
                risk=max(0.0, raw_risk - discount),
                raw_risk=raw_risk,
                loyalty_discount=discount,
                driven_total=driven_total,
                window_rows=state.rows,
                window_driven=state.driven,
                unexcused=state.unexcused,
                excused=state.excused,
                blocker_episodes=episodes,
                blockers_earlier=earlier_blockers.get(member.player_id, 0),
                km_average=km_average,
                km_weeks=km_weeks,
                km_total=km_total,
                km_rank=(km_ranking.index(member.player_id) + 1) if member.player_id in km_ranking else None,
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

    # Stufe 1: der Topf. Rein die Fahrleistung der Saison, schwächste zuerst. Wer im
    # Zeitraum keine einzige Zeile gefahren hat, steht ganz vorn - sie hat dem Team
    # nichts eingebracht, und das ist die Frage, die den Topf füllt.
    by_performance = sorted(
        candidates,
        key=lambda c: (c.raw_delta is not None, c.raw_delta if c.raw_delta is not None else 0.0),
    )
    performance_rank = {c.player_id: index for index, c in enumerate(by_performance, start=1)}
    candidates = [
        replace(c, performance_rank=performance_rank[c.player_id]) for c in candidates
    ]

    # Sofortfälle werden unabhängig vom Topf entschieden, stehen also nicht darin: sie
    # sind keine Abwägung mehr. Ihr Platz zählt trotzdem auf die zu schaffenden mit.
    immediate = sorted(
        (c for c in candidates if c.immediate),
        # Probation failures lead: there is no history to weigh against them and the
        # decision is the cheapest one on the list.
        key=lambda c: (not c.probation, -c.blocker_episodes, -c.raw_risk),
    )
    # Zwei Wege in den Topf, und der erste ist bedingungslos: **einmal unentschuldigt
    # gefehlt genügt**, egal wie gut jemand fährt. Vorgabe der Teamleitung - nicht zu
    # erscheinen ist der eine Fehler, über den nicht verhandelt wird. Der Topf kann
    # dadurch über SHORTLIST_SIZE hinauswachsen; die Zahl ist eine Zielgröße für das
    # Auffüllen, keine Obergrenze für die Zuverlässigkeitsfälle.
    eligible = [c for c in candidates if not c.immediate]
    by_absence = [c for c in eligible if c.unexcused > 0]
    absent_ids = {c.player_id for c in by_absence}
    fillers = [
        c for c in eligible if c.player_id not in absent_ids and _fills_the_pool(c)
    ]
    fillers.sort(key=lambda c: performance_rank[c.player_id])
    pool = by_absence + fillers[: max(0, SHORTLIST_SIZE - len(by_absence))]
    pool_ids = {c.player_id for c in pool}
    candidates = [
        replace(
            c,
            in_pool=c.player_id in pool_ids,
            pool_reason=(
                "unexcused" if c.player_id in absent_ids
                else ("performance" if c.player_id in pool_ids else "")
            ),
        )
        for c in candidates
    ]
    # Fehlen die Kilometer, tragen Zuverlässigkeit und Leistung die Reihung weiter -
    # ihr Gewicht wird umgelegt. Ein Sonderweg ist dafür nicht mehr nötig.
    ranked = sorted(
        (c for c in candidates if c.in_pool and not c.immediate), key=lambda c: -c.risk
    )

    # Ein volles Team hat TEAM_CAPACITY Plätze und die Leitung will TARGET_FREE_SLOTS
    # davon frei haben - fehlen schon Leute, müssen entsprechend weniger gehen.
    roster_size = len(roster)
    slots_to_free = max(0, roster_size - (TEAM_CAPACITY - TARGET_FREE_SLOTS))

    return BroomResult(
        status="OK",
        window=window,
        season=season,
        km_weeks=km_weeks_read,
        matches=len(match_ids),
        roster_size=roster_size,
        slots_to_free=slots_to_free,
        shortlist_size=SHORTLIST_SIZE,
        immediate_cases=immediate,
        all_rated=sorted(candidates, key=lambda c: performance_rank[c.player_id]),
        candidates=ranked,
        unrated=sorted(unrated, key=lambda u: u.window_driven),
        cohort_size=len(cohort),
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
        reasons.append(
            f"{candidate.blocker_episodes}x eingeloggt und nicht gefahren (Slot belegt)"
        )
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
    # Die Kilometer stehen immer da, nicht erst unter einer Schwelle: sie sind die
    # Zahl, die den Platz in dieser Liste bestimmt. Eine Begründung, die das
    # Reihungskriterium verschweigt, taugt für kein Gespräch.
    if candidate.km_average is not None and candidate.km_weeks >= 1:
        place = f", Platz {candidate.km_rank}/{roster_size}" if candidate.km_rank else ""
        # Dieselbe Zahl wie in der Tabelle: Gesamtkilometer des Zeitraums. Der
        # Wochenschnitt steht nur dahinter, wenn es mehr als eine Woche war - sonst
        # wiederholt er sich bloß selbst.
        line = f"{candidate.km_total} km im Zeitraum{place} im Kader"
        if candidate.km_weeks > 1:
            line += f" ({candidate.km_average:.0f}/Woche, Ø {team_km:.0f})"
        elif team_km > 0:
            line += f" (Ø {team_km:.0f})"
        if team_km > 0 and candidate.km_average >= team_km:
            line += " – überdurchschnittlich"
        reasons.append(line)
    elif candidate.km_weeks == 0:
        reasons.append("keine Kilometer im Zeitraum gemeldet")
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
    if candidate.raw_delta is not None and candidate.raw_delta < -3000:
        reasons.append(f"{candidate.raw_delta / 1000:+.1f}k zum Match-Median")
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
            f"nur {candidate.window_rows} im Fenster im Kader "
            f"(+{RETURNER_DISCOUNT} Punkte Abzug)"
        )
    if candidate.loyalty_discount:
        reasons.append(
            f"{candidate.driven_total} Matches für das Team gefahren -> "
            f"{candidate.loyalty_discount} Punkte Abzug"
        )

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
