"""Row and result shapes for the broom ranking."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BroomWindowRow:
    """One matchscore inside the window, joined with what is needed to judge it."""

    match_id: int
    player_id: int
    start: str
    score: int
    points: int
    absent: int | None
    checkin: int | None
    tracks: int | None


@dataclass(frozen=True)
class RosterMember:
    player_id: int
    name: str
    garage_power: int
    is_leader: bool


@dataclass(frozen=True)
class BroomFactor:
    """Eine Achse des Punktestands.

    ``points`` sind **Besenpunkte** und damit vorzeichenbehaftet: plus spricht gegen
    die Spielerin, minus für sie.

    Die echte Zahl dahinter gibt es zweimal, weil sie zwei Aufgaben hat. ``value`` ist
    die kurze Form für die Tabelle (``124``, ``-4.4k``, ``1+1``) - **dort steht der
    echte Wert und die Punkte nur in Klammern daneben**, denn mit "124 km/Woche" kann
    eine Leaderin im Gespräch etwas anfangen, mit einer 2 nicht. ``detail`` ist die
    ausgeschriebene Form für den Begründungsblock, wo Platz für Rang und Vergleich ist.
    """

    key: str
    label: str
    points: int
    value: str                   # kurz, für die Tabelle
    detail: str                  # ausgeschrieben, für den Begründungsblock


@dataclass(frozen=True)
class BroomCandidate:
    player_id: int
    name: str
    garage_power: int
    # **Besenpunkte: viele sind schlecht.** Eine ganze Zahl statt eines Risikos von
    # 0-100, damit jede den eigenen Stand nachrechnen kann - das war der ganze Zweck
    # des Umbaus. Sie darf unter null gehen: wer viel fährt und lange dabei ist, steht
    # im Minus, und das ist die beste Nachricht, die diese Liste zu vergeben hat.
    besen: int
    km_points: int               # wenig gefahren -> bis +3
    perf_points: int             # schlechteste Fahrleistung +10, beste +1
    absence_points: int          # unentschuldigt +2, Slot belegt +3 obendrauf
    loyalty_points: int          # Zugehörigkeit, allein nach Matchzahl - immer <= 0
    driven_total: int            # matches driven ever - what loyalty is measured on
    window_rows: int
    window_driven: int
    unexcused: int
    excused: int
    # Matches, in denen sie eingeloggt war und nicht gefahren ist. Jede Zeile zählt;
    # die frühere Zusammenfassung zu "Episoden" ist weg (siehe Modul-Docstring).
    blocker_rows: int
    blockers_earlier: int
    km_average: float | None
    km_weeks: int
    km_total: int                # Summe im Wertungszeitraum - die Zahl für die Tabelle
    km_rank: int | None
    raw_delta: float | None      # average distance to the match median - the shortlist
    # Die Saisonpunkte sind der **Tiebreaker**: bei gleichem Punktestand steht unten,
    # wer dem Team mehr eingebracht hat. Sie reihen nicht mit, sie trennen nur.
    points_total: int            # event points earned inside the window
    points_per_row: float | None # per roster match, absences counted as zero
    points_rank: int | None      # 1 = contributed least
    drops: int
    worst_drop: float | None
    matches_since_driven: int | None
    performance_rank: int = 0    # Platz im Kader nach Fahrleistung, 1 = schwächste
    in_pool: bool = False        # im Topf - über Fehltermin oder über Leistung
    pool_reason: str = ""        # "unexcused" | "performance" | "" 
    factors: list[BroomFactor] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BroomUnrated:
    """Only for a player with no roster row in the window at all - there is nothing
    to measure. Everybody who was in a match gets rated."""

    player_id: int
    name: str
    window_driven: int
    driven_total: int
    reason: str


@dataclass(frozen=True)
class BroomResult:
    status: str
    window: int = 0
    matches: int = 0
    season: int | None = None    # None = ein Matchfenster statt einer Saison
    km_weeks: int = 0            # Kilometerwochen, die das Fenster abdeckt
    roster_size: int = 0
    shortlist_size: int = 0      # Größe des Leistungstopfes
    # Alle bewerteten Spielerinnen nach Fahrleistung, schwächste zuerst. ``candidates``
    # ist der Topf daraus - die Vollliste bleibt, weil eine Auswahl ohne die Grundmenge
    # nicht nachprüfbar ist.
    all_rated: list[BroomCandidate] = field(default_factory=list)
    candidates: list[BroomCandidate] = field(default_factory=list)
    unrated: list[BroomUnrated] = field(default_factory=list)
    cohort_size: int = 0         # players with MIN_MATCHES driven - the yardstick
    team_unexcused_rate: float = 0.0
    team_km_average: float = 0.0
    leaders_skipped: int = 0
    # Ob --include-leaders gesetzt war. ``leaders_skipped == 0`` beantwortet das nicht:
    # es ist auch dann null, wenn es gar keine Leader gibt. Die Ausgabe muss den
    # Unterschied zeigen können - sonst tut das Flag sichtbar nichts, solange kein
    # Leader schwach genug für den Topf ist.
    include_leaders: bool = False
