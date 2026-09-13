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
2. **The ranking inside it: Besenpunkte.** Whole numbers, high is bad, and every one
   of them can be looked up by the player herself - that was the whole point of the
   rewrite. Kilometres, performance and absences add points, tenure subtracts them,
   and the season's event points break a tie. The 0-100 risk it replaced was accurate
   and unusable: nobody can argue with a 53.4, and "you have twelve broom points, here
   is where each one comes from" is a sentence that survives the conversation.

Everything else the model knows - drops, check-in no-shows, excused absence, points -
survives as a **reason line**, not as a weight: explaining yes, scoring no. A number
that moves the ranking has to be one the leadership can defend in the conversation
afterwards, and that is what keeps the model this small.

- **Tenure stays a minus, it never becomes a plus.** Inverting it would rank
  identically - the two differ by a constant - but the sentence flips from "your 776
  matches take three points off" to "you only have 27 matches, that is three points
  against you". Match count is almost the same thing as time on the team (7 for the
  newest, 797 for the oldest), so as a penalty it would put the youngest members on
  top every time. It may lower a score and never raise one.
- **There is no veto tier any anymore.** Immediate cases used to stand beside the pool,
  then inside it with a mark. Both are gone: a rule that removes somebody from the
  weighing needs a second mechanism to explain itself, and the points already say what
  it said. A newcomer who occupies a slot pays ``BLOCKER_POINTS`` and gets no tenure
  discount, so she lands at the top on her own - by the same arithmetic as everybody
  else, and without a second vocabulary on the page.
- **A check-in no-show is logging into the event and not driving**, which occupies a
  slot. It costs ``BLOCKER_POINTS``, more than the plain absence: she has shown she had
  the time and collects the event reward without driving for it.
"""
from __future__ import annotations

import statistics
from bisect import bisect_left
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
DROP_THRESHOLD = 1000        # dip below one's own average that counts as a drop

# --- check-in no-shows -----------------------------------------------------
# Früher wurden zwei Vorfälle innerhalb weniger Tage zu **einer Episode**
# zusammengefasst ("ein Wochenende, nicht zwei Vorfälle"). Die Regel existierte, damit
# die Veto-Stufe nicht bei einem einzigen Wochenende zuschlägt - die Stufe ist weg, und
# mit flachen Punkten je Spalte kehrte sich die Regel ins Gegenteil: zwei belegte Slots
# an einem Wochenende hätten 5 gekostet, zwei schlichte Fehltermine aber 6. Wer da war
# und nicht gefahren ist, käme billiger weg als wer gar nicht kam. Jetzt zählt jede
# Zeile. (An der echten DB betraf das zwei Fälle in der gesamten Historie.)

# --- newcomers ---------------------------------------------------------------
# There is no probation rule left. The Treue axis starts at zero below
# ``TREUE_TIERS[0]``, so a newcomer simply earns no discount - nothing has been
# earned, so nothing is subtracted, and that is the whole of it. The veto tier that
# used to live here is gone with it: it needed its own vocabulary on the page to
# explain why somebody was not being weighed, and the points already do the work.

# --- Besenpunkte -----------------------------------------------------------
# **Viele Besenpunkte, und der Besen kommt.** Ganze Zahlen statt eines Risikos von
# 0-100, und das ist der ganze Zweck: jede Spielerin kann ihren eigenen Stand
# nachrechnen, weil sie jede Eingangsgröße selbst nachsehen kann - die Performance
# postet der Bot nach jedem Match, die Kilometer stehen in der Truhe, die Fehltermine
# kennt sie selbst. Ein Rauswurf, der sich aus einer 53,4 ergibt, lässt sich nicht
# besprechen; einer aus "zwölf Besenpunkte, hier kommt jeder einzelne her" schon.
#
# Die Skala darf **unter null** gehen. Wer viel fährt und lange dabei ist, steht im
# Minus, und das ist die beste Nachricht, die diese Liste zu vergeben hat - das alte
# Risiko schnitt sie bei null ab und warf sie damit weg.
#
# Alle Achsen sind **absolut**, nur die Performance ist eine Rangliste. Das geht, weil
# die Verteilungen über Saisons hinweg kaum wandern (km/Woche-Quartile S64 87/152/294,
# S65 91/172/294) - feste Schwellen veralten also nicht zwischen zwei Saisons.

# Kilometer: Schnitt pro Woche über KM_WINDOW_WEEKS, Stufen am echten Kader gemessen.
# Der Team-Schnitt liegt bei ~240 km/Woche, deshalb liegen die Schwellen dort und
# nicht bei 100: an Saison 64 bekamen mit einer 100er-Grenze 39 von 40 Spielerinnen
# dieselbe Stufe, und eine Achse, die niemanden trennt, ist keine.
# **Die letzten fünf Wochen, nicht die Wochen der Saison.** Eine Saison ist im Schnitt
# 4,3 Wochen lang (S64 4,4, S63 4,4, S62 4,3), fünf Wochen sind also grob eine Saison -
# aber immer gleich breit. Das ist der Punkt: eine absolute Schwelle braucht eine feste
# Fensterbreite, sonst heißt dieselbe Stufe am Saisonanfang etwas anderes als am Ende,
# wo die Truhe schon dreimal gelesen wurde. Der Preis ist bekannt und in Kauf genommen:
# in der ersten Woche einer Saison stammen vier der fünf Wochen aus der Vorsaison.
# Vertretbar, weil Kilometer eine Gewohnheit sind und keine Saisoneigenschaft.
KM_WINDOW_WEEKS = 5
KM_TIERS: tuple[tuple[int, int], ...] = ((50, 3), (150, 2), (300, 1))
KM_POINTS_MAX = 3            # <= erste Stufe: gar nichts gefahren
KM_POINTS_MIN = 0            # über der letzten Stufe

# Performance: die einzige Rangliste, und sie darf eine sein - der Bot postet die
# Zahl nach jedem Match, also kennt jede ihren Platz. Schwächste 10, beste 1.
PERF_POINTS_MAX = 10
PERF_POINTS_MIN = 1

# Fehlen. **Ein flacher Wert je Spalte**, nicht ein Grundsatz plus Aufschlag: unter
# "Fehlt" stehen die Male, bei denen sie gar nicht aufgetaucht ist, unter "Slot" die
# mit Check-in. Der belegte Slot wiegt schwerer, und das ist Absicht - wer sich
# einloggt, hat gezeigt, dass er Zeit hatte, und greift die Event-Belohnung ab, ohne
# dafür zu fahren. Vorgabe der Teamleitung.
#
# **Die Höhe ist an der echten Liste kalibriert, nicht geraten.** Die Perf-Achse
# spannt PERF_POINTS_MAX - PERF_POINTS_MIN = 9 Punkte und ist damit breiter als der
# ganze beobachtete Topf von Saison 64 (3 bis 9). Bei 2 Punkten je Fehltermin verpuffte
# das Fehlen darin: Bisa stand dort mit *drei* unentschuldigten Fehlterminen auf
# derselben 9 wie tina und Dommas, die nie gefehlt hatten - sie holte sechs Punkte
# Strafe durch fünf Plätze besseres Fahren wieder herein. Bei 3 wiegen **drei
# Fehltermine genau die volle Leistungsspanne auf** (3 x 3 = 9), und das ist ein Satz,
# den man in einem Gespräch sagen kann. Es ist außerdem genau die Zahl, die im alten
# Modell als UNEXCUSED_CAP stand.
UNEXCUSED_POINTS = 3         # gar nicht aufgetaucht, je Mal
BLOCKER_POINTS = 5           # eingeloggt und nicht gefahren, je Mal

# Zugehörigkeit. **Immer <= 0**, siehe Modul-Docstring: gedreht reihte sie identisch,
# aber der Satz im Gespräch würde aus Neusein einen Vorwurf machen.
#
# Es zählt allein die Zahl der gefahrenen Matches. Es gab einmal einen Zusatzabzug für
# Rückkehrerinnen (``RETURNER_BONUS``), erkannt an Historie außerhalb des Fensters plus
# einer Lücke darin (``window_rows <= window - MIN_MATCHES``). Die Schwelle stammte aus
# der Zeit, als das Fenster 40 Matches breit war; seit der Wertungszeitraum die Saison
# ist (5 bis 15 Matches), war sie größer als ihr eigenes Fenster und konnte gar nicht
# mehr zutreffen - an Saison 65 wäre sie ``window_rows <= -5`` gewesen. Die Regel hat in
# keiner der beiden gemessenen Saisons je gegriffen und ist weggefallen: die Matchzahl
# sagt dasselbe, nur ohne eine Bedingung, die niemand erfüllen kann.
TREUE_TIERS: tuple[tuple[int, int], ...] = ((15, 0), (50, -1), (150, -2))
TREUE_MAX = -3               # über der letzten Stufe

# Reihenfolge und Beschriftung der Punktespalten. **Wörter, keine Emoji**: ein Emoji
# ist zwei Anzeigespalten breit, für ``len()`` aber ein Zeichen, und je nach
# Discord-Client rendert es mal so mal so - eine Tabelle, die nur manchmal
# ausgerichtet ist, ist schlechter als eine ohne Symbole.
# Die Spaltenköpfe tragen die **Einheit des echten Werts**, nicht den Namen der Achse:
# in der Zelle steht "124", und "km/W" sagt, dass das Kilometer pro Woche sind. Die
# Punkte stehen in Klammern daneben.
# **Fehlen und Slot sind zwei Spalten, und zwar disjunkte.** Wer sich einloggt und
# nicht fährt, steht in der DB als unentschuldigter Fehltermin *und* als Check-in -
# in einer gemeinsamen Zelle sah das aus wie zwei Vorfälle ("1+1"), obwohl es einer
# ist. Getrennt zählt jede Zeile genau einmal: "Fehlt" sind die, bei denen sie gar
# nicht aufgetaucht ist, "Slot" die, bei denen sie da war und nicht gefahren ist.
FACTORS: tuple[tuple[str, str, str], ...] = (
    ("motivation", "km/W", "Kilometer pro Woche"),
    ("performance", "Perf", "Fahrleistung zum Match-Median"),
    ("reliability", "Fehlt", "gar nicht aufgetaucht"),
    ("blocker", "Slot", "eingeloggt und nicht gefahren"),
    ("loyalty", "Matches", "gefahrene Matches für das Team"),
)
FACTOR_LABELS = {key: label for key, label, _ in FACTORS}

# Die Event-Punkte der Saison - sie reihen nicht mit, sie trennen nur den Gleichstand.
# Im Team heißen sie schlicht "Punkte" (0 bis 300 je Match, neben dem Score
# eingetragen), deshalb steht das auch über der Spalte: ein Kopf, den niemand erst
# übersetzen muss. Die Besen-Spalte daneben heißt "Besen" und nicht "Besenpunkte",
# also stehen sich die beiden Wörter nicht im Weg.
TIEBREAK_LABEL = "Punkte"
BESEN_LABEL = "Besen"

# Wie eine Achse im Satz heißt - die Spaltenköpfe sind zum Vorlesen zu kurz.
FACTOR_PHRASES = {
    "motivation": "gefahrener Kilometer",
    "performance": "Leistung zum Match-Median",
    "reliability": "unentschuldigten Fehlens",
    "blocker": "belegter Slots",
    "loyalty": "Zugehörigkeit",
}


def km_points(km_per_week: float | None) -> int:
    """Besenpunkte für die Kilometer - wenig gefahren ist viel Punkte."""
    if km_per_week is None:
        return KM_POINTS_MAX
    for limit, points in KM_TIERS:
        if km_per_week <= limit:
            return points
    return KM_POINTS_MIN


def perf_points(key: tuple[bool, float], pool_keys: list[tuple[bool, float]]) -> int:
    """Besenpunkte für die Fahrleistung, gemessen **am Topf**.

    Bei ``SHORTLIST_SIZE`` (10) Plätzen und zehn Punktwerten wird jede Zahl von
    ``PERF_POINTS_MIN`` bis ``PERF_POINTS_MAX`` genau einmal vergeben: die Schwächste
    der Liste bekommt den Höchstwert, die Beste den Kleinsten, dazwischen linear. Das
    ist die Aussage, die im Gespräch trägt - "du bist die Schwächste von den zehn",
    nicht "du liegst im 38. Perzentil".

    Gezählt wird, wie viele im Topf **echt schwächer** fahren, nicht ein laufender
    Index: der vergäbe je nach Sortierstabilität verschiedene Punkte an zwei
    Spielerinnen mit demselben Abstand zum Match-Median. Bei echtem Gleichstand fällt
    ein Wert deshalb aus - der Preis dafür, dass gleiche Leistung gleich bewertet wird.

    Wächst der Topf über zehn hinaus (mehr als zehn unentschuldigte Fehltermine), wird
    dieselbe Gerade über die größere Liste gelegt; dann wiederholen sich Werte.
    """
    if len(pool_keys) < 2:
        return PERF_POINTS_MAX
    weaker = bisect_left(pool_keys, key)
    span = PERF_POINTS_MAX - PERF_POINTS_MIN
    return round(PERF_POINTS_MAX - span * weaker / (len(pool_keys) - 1))


def plain_absences(unexcused: int, blocker_rows: int) -> int:
    """Die Male, bei denen sie gar nicht aufgetaucht ist.

    ``unexcused`` **enthält** die Zeilen mit Check-in - wer sich einloggt und nicht
    fährt, ist auch nicht erschienen -, also müssen sie hier abgezogen werden. Sonst
    stünde derselbe Vorfall in beiden Spalten.
    """
    return max(0, unexcused - blocker_rows)


def plain_absence_points(unexcused: int, blocker_rows: int) -> int:
    """Besenpunkte für die Fehltermine ohne Check-in. Ohne Deckel."""
    return plain_absences(unexcused, blocker_rows) * UNEXCUSED_POINTS


def blocked_slot_points(blocker_rows: int) -> int:
    """Besenpunkte für die Fehltermine mit Check-in. Ohne Deckel."""
    return blocker_rows * BLOCKER_POINTS


def absence_points(unexcused: int, blocker_rows: int) -> int:
    """Was das Fehlen insgesamt kostet - die Summe der beiden Spalten."""
    return plain_absence_points(unexcused, blocker_rows) + blocked_slot_points(blocker_rows)


def treue_points(driven_total: int) -> int:
    """Besenpunkte für die Zugehörigkeit - null oder negativ, nie positiv."""
    for limit, tier in TREUE_TIERS:
        if driven_total < limit:
            return tier
    return TREUE_MAX


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


def last_weeks(last_day: str, count: int) -> list[tuple[int, int]]:
    """Die letzten ``count`` ISO-Wochen, die am Stichtag enden - neueste zuerst.

    Der Stichtag ist das **Ende des Wertungszeitraums**, nicht heute: ``--season 63``
    muss die letzten fünf Wochen *jener* Saison lesen, sonst zöge eine abgeschlossene
    Saison die Kilometer von heute herein und wäre morgen nicht mehr reproduzierbar.
    """
    day = date.fromisoformat(last_day[:10])
    weeks: list[tuple[int, int]] = []
    while len(weeks) < count:
        iso = day.isocalendar()
        if (iso.year, iso.week) not in weeks:
            weeks.append((iso.year, iso.week))
        day -= timedelta(days=7)
    return weeks


def _km_weeks(season: int | None, match_ids: list[int]) -> list[tuple[int, int]]:
    """Die Kilometerwochen, aus denen der Wochenschnitt kommt.

    Immer ``KM_WINDOW_WEEKS`` breit und am Ende des Wertungszeitraums verankert - die
    Saisonwochen selbst wären zwischen einer und dreizehn, und an einer festen Schwelle
    gemessen hieße ein Punktwert dann in jeder Saison etwas anderes.
    """
    bounds = broom_repo.season_bounds(season) if season is not None else None
    if bounds is None:
        # Auch der Saisonmodus landet hier, wenn die Saisonzeile fehlt - die Matches
        # sind dann der einzige Beleg dafür, welcher Zeitraum gemeint war.
        bounds = broom_repo.match_bounds(match_ids)
    if not bounds:
        return []
    return last_weeks(bounds[1], KM_WINDOW_WEEKS)


def _performance_key(raw_delta: float | None) -> tuple[bool, float]:
    """Sortierschlüssel der Fahrleistung, schwächste zuerst.

    ``None`` heißt: im Zeitraum keine Zeile gefahren. Die steht ganz vorn, denn sie hat
    dem Team gar nichts eingebracht - und das ist die Frage, die der Topf stellt.
    """
    return (raw_delta is not None, raw_delta if raw_delta is not None else 0.0)


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
    return candidate.unexcused > 0 or candidate.blocker_rows > 0


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

        # Wer sich einloggt und nicht fährt, belegt einen Slot - **außer sie ist
        # abgemeldet**. Dann ist das Einloggen kein Zugriff auf die Event-Belohnung,
        # sondern nur eine Zeile, die ohnehin schon als entschuldigt zählt. An der
        # echten DB ist der Fall noch nie eingetreten (31 Check-in-No-Shows, keiner
        # davon abgemeldet) - die Regel steht trotzdem hier, weil sie sonst beim
        # ersten Mal falsch entscheidet.
        if row.checkin == 1 and not row.absent:
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
            # Own matches newer than her last driven one - somebody who missed the
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
        # size-dependent rule below has to see the real count, not the asked-for one.
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
            include_leaders=include_leaders,
            team_km_average=team_km,
        )

    total_rows = sum(windows[m.player_id].rows for m in cohort)
    team_unexcused = sum(windows[m.player_id].unexcused for m in cohort) / total_rows if total_rows else 0.0

    # Leistung ist der rohe Abstand zum Match-Median. Die Garage Power wird bewusst
    # nicht herausgerechnet: für einen freien Platz zählt, was eine Spielerin dem Team
    # einbringt, nicht ob ihre Ausrüstung mehr hergegeben hätte. An der echten Saison
    # 64 änderte die Korrektur ohnehin nur eine von zehn Personen im Topf.
    #
    # Die Kohorten-Verteilungen, aus denen die Perzentile kamen, sind mit ihnen weg:
    # jede Achse hat jetzt eine feste Schwelle, und nur die Perf-Achse ist noch eine
    # Rangliste - die über alle Bewerteten, nicht über die Kohorte. Die Kohorte trägt
    # nur noch die Teamquote im Kopf der Ausgabe.
    residuals = {m.player_id: windows[m.player_id].average_delta for m in rated}
    points_ranking = sorted(
        (m.player_id for m in rated if windows[m.player_id].points_per_row is not None),
        key=lambda player_id: windows[player_id].points_per_row,
    )

    candidates: list[BroomCandidate] = []
    for member in rated:
        if member.is_leader and not include_leaders:
            continue
        state = windows[member.player_id]
        blocker_rows = len(state.blocker_dates)
        km_average, km_weeks, km_total = km.get(member.player_id, (None, 0, 0))
        driven_total = driven_totals.get(member.player_id, 0)

        drop_count, worst_drop = state.drops()

        candidates.append(
            BroomCandidate(
                player_id=member.player_id,
                name=member.name,
                garage_power=member.garage_power,
                # Die Punkte brauchen den Leistungsrang, und der steht erst fest, wenn
                # alle Kandidatinnen gebaut sind - _with_points() trägt sie gleich
                # nach. Bis dahin steht hier die Rohform.
                besen=0,
                km_points=0,
                perf_points=0,
                absence_points=absence_points(state.unexcused, blocker_rows),
                loyalty_points=treue_points(driven_total),
                driven_total=driven_total,
                window_rows=state.rows,
                window_driven=state.driven,
                unexcused=state.unexcused,
                excused=state.excused,
                blocker_rows=blocker_rows,
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
                factors=[],
                reasons=[],
            )
        )

    # Stufe 1: der Topf. Rein die Fahrleistung der Saison, schwächste zuerst. Wer im
    # Zeitraum keine einzige Zeile gefahren hat, steht ganz vorn - sie hat dem Team
    # nichts eingebracht, und das ist die Frage, die den Topf füllt. Derselbe Rang
    # trägt gleich auch die Perf-Besenpunkte, deshalb steht er vor der Punkterechnung.
    #
    by_performance = sorted(candidates, key=lambda c: _performance_key(c.raw_delta))
    performance_rank = {c.player_id: index for index, c in enumerate(by_performance, start=1)}

    candidates = [
        replace(c, performance_rank=performance_rank[c.player_id]) for c in candidates
    ]

    # **Zwei Wege in den Topf, und der erste ist bedingungslos: einmal unentschuldigt
    # gefehlt genügt**, egal wie gut jemand fährt. Vorgabe der Teamleitung - nicht zu
    # erscheinen ist der eine Fehler, über den nicht verhandelt wird. Der Topf kann
    # dadurch über SHORTLIST_SIZE hinauswachsen; die Zahl ist eine Zielgröße für das
    # Auffüllen, keine Obergrenze für die Fehltermine.
    by_absence = [c for c in candidates if c.unexcused > 0]
    absent_ids = {c.player_id for c in by_absence}
    fillers = [
        c for c in candidates if c.player_id not in absent_ids and _fills_the_pool(c)
    ]
    fillers.sort(key=lambda c: performance_rank[c.player_id])
    pool_ids = absent_ids | {
        c.player_id for c in fillers[: max(0, SHORTLIST_SIZE - len(absent_ids))]
    }
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

    # **Die Perf-Punkte messen sich am Topf, nicht am Kader** - deshalb stehen sie hier
    # und nicht vor der Auswahl. Zehn Plätze, zehn Punktwerte, jeder genau einmal: die
    # Beste der Liste bekommt PERF_POINTS_MIN, die Schwächste PERF_POINTS_MAX. Vorgabe
    # der Teamleitung, und der Grund ist wieder das Gespräch: "du bist die Schwächste
    # von den zehn" ist eine Aussage, "du liegst im 38. Perzentil des Kaders" nicht.
    #
    # Der Preis ist bekannt: die Skala ist damit **relativ zur Liste**. Wer in den Topf
    # kommt, verschiebt die Punkte aller anderen darin - `--include-leaders` ändert sie
    # also, und eine Neue, die sich hineinfährt, auch. Das ist die Kehrseite davon, dass
    # jede Zahl von 1 bis 10 genau einmal vorkommt, und geht nicht anders.
    pool_keys = sorted(
        _performance_key(c.raw_delta) for c in candidates if c.in_pool
    )
    candidates = [
        _with_points(
            c,
            pool_keys=pool_keys,
            team_km=team_km,
            roster_size=len(km_ranking),
        )
        for c in candidates
    ]
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
    # **Viele Besenpunkte zuerst, bei Gleichstand die Saisonpunkte.** Ein Punktestand
    # aus ganzen Zahlen erzeugt Gleichstände, wo das alte Risiko mit Nachkommastellen
    # eine Trennung vortäuschte - an Saison 64 standen sieben Spielerinnen auf
    # demselben Wert. Die Saisonpunkte lösen das fast restlos auf (aus sieben Gleichen
    # werden sechs Gruppen) und trennen an der Schnittlinie in beiden gemessenen
    # Saisons sauber: wer dem Team mehr eingebracht hat, steht weiter unten.
    ranked = sorted(
        (c for c in candidates if c.in_pool), key=lambda c: (-c.besen, c.points_total)
    )

    roster_size = len(roster)

    return BroomResult(
        status="OK",
        window=window,
        season=season,
        km_weeks=km_weeks_read,
        matches=len(match_ids),
        roster_size=roster_size,
        shortlist_size=SHORTLIST_SIZE,
        all_rated=sorted(candidates, key=lambda c: performance_rank[c.player_id]),
        candidates=ranked,
        unrated=sorted(unrated, key=lambda u: u.window_driven),
        cohort_size=len(cohort),
        team_unexcused_rate=team_unexcused,
        team_km_average=team_km,
        leaders_skipped=leaders_skipped,
        include_leaders=include_leaders,
    )


def _with_points(
    candidate: BroomCandidate,
    *,
    pool_keys: list[tuple[bool, float]],
    team_km: float,
    roster_size: int,
) -> BroomCandidate:
    """Die vier Achsen zu Besenpunkten rechnen und aufaddieren.

    Die Summe ist die Zahl, die in der Tabelle steht, und sie muss sich aus den vier
    Spalten daneben nachaddieren lassen - deshalb wird hier nichts gerundet, gedeckelt
    oder umgelegt. Wer nachrechnet, muss dasselbe herausbekommen, sonst war der ganze
    Umbau umsonst.
    """
    km = km_points(candidate.km_average if candidate.km_weeks else None)
    # Wer nicht im Topf steht, wird auch nicht gegen ihn gereiht: sie fährt per
    # Konstruktion besser als die Schwächsten, über die geredet wird, also bekommt sie
    # den kleinsten Wert. Ihr Punktestand ist ohnehin keine Ranglistenzahl - sie taucht
    # nur in `all_rated` und im JSON auf, nie in der Liste.
    perf = (
        perf_points(_performance_key(candidate.raw_delta), pool_keys)
        if candidate.in_pool
        else PERF_POINTS_MIN
    )
    plain = plain_absence_points(candidate.unexcused, candidate.blocker_rows)
    blocked = blocked_slot_points(candidate.blocker_rows)
    loyalty = candidate.loyalty_points

    if candidate.km_weeks:
        weeks = "Woche" if candidate.km_weeks == 1 else f"{candidate.km_weeks} Wochen"
        place = f", Platz {candidate.km_rank}/{roster_size}" if candidate.km_rank else ""
        # Der Teamschnitt steht **nicht** hier: er steht schon in der Kopfzeile, und
        # in jedem Block noch einmal wäre er zehnmal dieselbe Zahl. Das Verhältnis zu
        # ihm überlebt als "überdurchschnittlich", denn das ist die Aussage.
        km_detail = (
            f"{candidate.km_average:.0f} km/Woche{place} "
            f"({candidate.km_total} km in {weeks})"
        )
        if team_km > 0 and candidate.km_average >= team_km:
            km_detail += " – überdurchschnittlich"
    else:
        km_detail = "keine Kilometer im Zeitraum gemeldet"

    plain_count = plain_absences(candidate.unexcused, candidate.blocker_rows)
    plain_detail = (
        f"{plain_count}x gar nicht aufgetaucht" if plain_count else "nichts vorgefallen"
    )
    blocked_detail = (
        f"{candidate.blocker_rows}x eingeloggt und nicht gefahren"
        if candidate.blocker_rows
        else "nichts vorgefallen"
    )

    # Ohne "Matches" im Text: das Wort steht schon als Spaltenkopf davor.
    loyalty_detail = f"{candidate.driven_total} für das Team gefahren"

    details = {
        "motivation": km_detail,
        "performance": (
            f"{candidate.raw_delta / 1000:+.1f}k zum Match-Median"
            if candidate.raw_delta is not None
            else "im Zeitraum nicht gefahren"
        )
        + (
            # Der Platz **im Topf**, denn daraus entstehen die Punkte. Der Platz im
            # Kader stünde daneben und wäre eine andere Zahl.
            f", Platz {bisect_left(pool_keys, _performance_key(candidate.raw_delta)) + 1}"
            f"/{len(pool_keys)} im Topf"
            if candidate.in_pool and pool_keys
            else ""
        ),
        "reliability": plain_detail,
        "blocker": blocked_detail,
        "loyalty": loyalty_detail,
    }
    # Die Kurzform für die Tabelle. "1+1" heißt ein unentschuldigter Fehltermin und
    # ein belegter Slot - zusammengezählt wären es zwei gleich schwere Vorfälle, und
    # sie sind es nicht. "-" heißt: nichts vorgefallen beziehungsweise keine Zahl da.
    values = {
        "motivation": f"{candidate.km_average:.0f}" if candidate.km_weeks else "-",
        "performance": (
            f"{candidate.raw_delta / 1000:+.1f}k" if candidate.raw_delta is not None else "-"
        ),
        "reliability": str(plain_count) if plain_count else "-",
        "blocker": str(candidate.blocker_rows) if candidate.blocker_rows else "-",
        "loyalty": str(candidate.driven_total),
    }
    points = {
        "motivation": km,
        "performance": perf,
        "reliability": plain,
        "blocker": blocked,
        "loyalty": loyalty,
    }
    factors = [
        BroomFactor(
            key=key,
            label=label,
            points=points[key],
            value=values[key],
            detail=details[key],
        )
        for key, label, _ in FACTORS
    ]
    return replace(
        candidate,
        km_points=km,
        perf_points=perf,
        besen=km + perf + plain + blocked + loyalty,
        factors=factors,
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

    These are the **context** lines only: the four point axes print themselves from
    ``factors``, so anything that merely restates a point value belongs there and not
    here. What is left is what no axis carries - the share an absence makes up, an
    episode from before the window, drops, the season points that break a tie.

    Deterministic on purpose - the same roster has to produce the same sentences,
    because "why was she not on the list last week?" has to have an answer.
    """
    reasons: list[str] = []

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
    # Die Saisonpunkte stehen **nicht** hier. Sie reihen nicht mit, sondern trennen
    # nur den Gleichstand - und dann sagt sie die Ausgabe, bei genau den Zeilen, wo
    # wirklich etwas zu trennen war. Bei allen anderen wäre es eine Zeile, die eine
    # Zahl wiederholt, die schon in ihrer eigenen Spalte steht.
    if candidate.drops >= 3 and candidate.worst_drop is not None:
        reasons.append(
            f"{candidate.drops} Einbrüche unter den eigenen Schnitt, "
            f"tiefster {candidate.worst_drop / 1000:.1f}k"
        )
    if candidate.matches_since_driven and candidate.matches_since_driven >= 3:
        reasons.append(
            f"seit {candidate.matches_since_driven} eigenen Matches nicht gefahren"
        )

    if not reasons:
        # Nothing crossed a reporting threshold, yet she is on the list - then the
        # list itself is the statement, and the heaviest axis has to be named.
        # A name with an empty block below it reads as a bug.
        costly = [factor for factor in candidate.factors if factor.points > 0]
        if costly:
            worst = max(costly, key=lambda factor: factor.points)
            reasons.append(
                f"nichts sticht heraus – was sie listet, ist "
                f"{FACTOR_PHRASES[worst.key]} (+{worst.points})"
            )

    return replace(candidate, reasons=reasons)
