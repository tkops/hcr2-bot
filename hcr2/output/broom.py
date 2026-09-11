"""Ausgabe der Besen-Rangliste.

Die Tabelle ist die Rangliste, die Blöcke darunter sind die Begründung. Jede
gelistete Kandidatin bekommt ihre Zeilen, weil fünf Namen und eine Zahl nichts sind,
womit eine Leitung in ein Gespräch gehen kann.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from hcr2.models.broom import BroomCandidate, BroomResult
from hcr2.output.tables import print_table
from hcr2.services import broom as broom_service


# Kopf und Daten sind reiner Text, also richten sie sich immer aneinander aus - die
# frühere Emoji-Kopfzeile war zwei Anzeigespalten breit bei einem Zeichen Länge und
# rutschte je nach Discord-Client.
#
# Die Spalten tragen **die echten Zahlen**, keine Perzentile: -23.2k ist der Wert aus
# `stats perf --driven-only`, den jede Leaderin kennt, 820 sind die Kilometer des
# Zeitraums, 2 sind zwei Fehltermine und 776 sind gefahrene Matches. Gerechnet wird
# intern weiter mit Perzentilen - aber mit einer 87 in der Zeile kann im Gespräch
# niemand etwas anfangen.
COLUMN_WIDTHS = {"reliability": 5, "performance": 7, "motivation": 6}
LOYALTY_WIDTH = 7
# 2 + 14 + 6 + 5 + 7 + 6 + 7 Zellen plus sechs Trennzeichen
WIDTH = 2 + 14 + 6 + 5 + 7 + 6 + 7 + 6
DEFAULT_LIMIT = 5
# Ein zu kurzes Fenster macht aus dem Anhang eine Kaderliste, die nichts sagt, was
# die Kopfzeile nicht schon gesagt hat.
UNRATED_LIMIT = 10
# Below this many yardstick players the comparative factors stop meaning much.
MIN_COHORT = 8

# Reihenfolge der Faktorspalten - dieselbe wie die Gewichtung.
ORDER = tuple(key for key, _, _, _ in broom_service.FACTORS)


def print_result(
    result: BroomResult, *, limit: int | None = None, show_all: bool = False
) -> None:
    """``limit`` = None heißt: so viele Begründungen, wie Plätze frei werden sollen."""
    if result.status == "NO_MATCHES":
        if result.season is not None:
            print(f"⚠️ Keine Matches in Saison {result.season} gespeichert.")
        else:
            print("⚠️ Keine Matches gespeichert.")
        return
    if result.status == "NO_ROSTER":
        print("⚠️ Keine aktiven PLTE-Spielerinnen.")
        return
    if result.status == "NO_DATA" or not result.candidates:
        print(f"⚠️ Keine Kaderzeile in {_window_label(result)}, also ist niemand bewertbar.")
        return

    # Die Begründungsblöcke gehen auf so viele Namen, wie Plätze frei werden sollen -
    # das ist die Zahl der Entscheidungen, die tatsächlich anstehen. --top ersetzt sie,
    # --all erklärt den ganzen Topf.
    if show_all:
        explained_count = len(result.candidates)
    elif limit is not None:
        explained_count = limit
    else:
        explained_count = max(1, min(result.slots_to_free or DEFAULT_LIMIT, len(result.candidates)))
    explained = result.candidates[:explained_count]

    print(f"🧹 Besen – {_window_label(result)} · {_target_label(result)}")
    header = [
        f"Team unentschuldigt {result.team_unexcused_rate * 100:.1f}%",
        _km_label(result),
    ]
    if result.leaders_skipped:
        header.append(f"{result.leaders_skipped} Leader übersprungen")
    print(" · ".join(header))
    if result.cohort_size < MIN_COHORT:
        # Without a yardstick population the comparative factors cannot be computed
        # at all, and a ranking built on the rest reads far more solid than it is.
        print(
            f"⚠️ Nur {result.cohort_size} Spielerinnen mit {broom_service.MIN_MATCHES}+ "
            f"gefahrenen Matches im Fenster – Vergleichsfaktoren sind unsicher."
        )

    _print_immediate(result)

    print()
    print(_pool_label(result))
    if not result.km_weeks:
        print("⚠️ Keine Kilometer im Zeitraum – gereiht nur nach Fehlen und Leistung.")
    print_table(
        headers=[
            f"{'#':>2}", f"{'Spielerin':<14}", f"{'Risiko':>6}",
            *[
                f"{label:>{COLUMN_WIDTHS[key]}}"
                for key, label, _, _ in broom_service.FACTORS
            ],
            f"{broom_service.LOYALTY_LABEL:>{LOYALTY_WIDTH}}",
        ],
        rows=[
            _row(candidate, index)
            for index, candidate in enumerate(result.candidates, start=1)
        ],
        width=WIDTH,
    )

    for candidate in explained:
        print()
        _print_reasons(candidate)

    _print_unrated(result)
    # Legende zuletzt: sie ist Referenz, nicht Inhalt. Bei Ausgaben, die Discord auf
    # zwei Nachrichten aufteilt, gehört in die erste die Rangliste mit ihren
    # Begründungen - nicht die Erklärung der Spalten.
    _print_legend()


def _pool_label(result: BroomResult) -> str:
    """Woraus der Topf besteht - der Eintrittsgrund ist die halbe Begründung.

    Ein unentschuldigter Fehltermin ist die bedingungslose Eintrittskarte, der Rest
    wird nach Leistung aufgefüllt. Wer das nicht danebenstehen sieht, liest die Liste
    als reine Leistungsrangliste und wundert sich über die guten Fahrerinnen darin.
    """
    by_absence = sum(1 for c in result.candidates if c.pool_reason == "unexcused")
    by_performance = len(result.candidates) - by_absence
    parts = []
    if by_absence:
        parts.append(f"{by_absence}x unentschuldigt gefehlt")
    if by_performance:
        parts.append(f"{by_performance}x nach Leistung aufgefüllt")
    return f"Topf ({len(result.candidates)}): " + ", ".join(parts or ["leer"])


def _target_label(result: BroomResult) -> str:
    """Wie viele Plätze frei werden sollen - die Zahl, um die es am Saisonende geht.

    Sie folgt aus der Kadergröße: fehlen schon Leute, sind entsprechend weniger zu
    verabschieden. Sofortfälle zählen mit, sie machen ja denselben Platz frei.
    """
    if not result.slots_to_free:
        return f"Kader {result.roster_size} – kein Platz zu schaffen"
    text = f"Kader {result.roster_size} → {result.slots_to_free} Plätze zu schaffen"
    if result.immediate_cases:
        rest = max(0, result.slots_to_free - len(result.immediate_cases))
        text += (
            f", davon {len(result.immediate_cases)} als Sofortfall, "
            f"also {rest} aus dem Topf"
        )
    return text


def _print_immediate(result: BroomResult) -> None:
    """Sofortfälle stehen außerhalb des Topfes: über sie wird nicht abgewogen.

    Sie werden trotzdem gezeigt, weil ihr Platz auf die zu schaffenden zählt - und
    weil eine Entscheidung, die niemand mehr begründet bekommt, keine bleibt.
    """
    if not result.immediate_cases:
        return
    print()
    print(
        f"{broom_service.IMMEDIATE_ICON} Sofortfälle – unabhängig vom Topf, "
        f"machen aber denselben Platz frei:"
    )
    for candidate in result.immediate_cases:
        print()
        _print_reasons(candidate)


def _km_label(result: BroomResult) -> str:
    """Ohne die Wochenzahl ist der Schnitt nicht einzuordnen: die Kilometer kommen aus
    dem Wertungszeitraum, und der kann am Saisonanfang eine einzige Woche breit sein."""
    if not result.km_weeks:
        return "keine Kilometer im Zeitraum"
    weeks = "1 Woche" if result.km_weeks == 1 else f"{result.km_weeks} Wochen"
    return f"Ø {result.team_km_average:.0f} km/Woche aus {weeks}"


def _window_label(result: BroomResult) -> str:
    """Woraus die Liste gerechnet ist - im Kopf, weil eine Rangliste ohne ihren
    Zeitraum nicht überprüfbar ist."""
    if result.season is None:
        return f"letzte {result.matches} Matches"
    return f"Saison {result.season} ({result.matches} Matches)"


def _print_legend() -> None:
    print()
    print("So kommt die Liste zustande – zwei Schritte, mehr nicht:")
    print(
        f"  1. In den Topf kommt, wer unentschuldigt gefehlt hat (immer, egal wie gut),"
    )
    print(
        f"     aufgefüllt auf {broom_service.SHORTLIST_SIZE} mit den Schwächsten der Saison."
    )
    print("  2. Gereiht wird darin nach vier Dingen – die Spalten zeigen die echten Werte:")
    print(
        f"     {'Fehlt':<8}{broom_service.FACTOR_WEIGHTS['reliability']:>2}  "
        f"unentschuldigte Fehltermine der Saison "
        f"(ab {broom_service.UNEXCUSED_CAP} voll gewertet)"
    )
    print(
        f"     {'Perf':<8}{broom_service.FACTOR_WEIGHTS['performance']:>2}  "
        f"Score zum Match-Median – dieselbe Zahl wie 'stats perf --driven-only'"
    )
    print(
        f"     {'km':<8}{broom_service.FACTOR_WEIGHTS['motivation']:>2}  "
        f"Kilometer im Zeitraum, gesamt"
    )
    print(
        f"     {'Matches':<8}    Zugehörigkeit: gefahrene Matches insgesamt, ziehen bis "
        f"zu {broom_service.LOYALTY_MAX} Punkte vom Risiko ab"
    )
    print("                 (in der Probezeit 0 – kein Schutz, aber auch keine Strafe)")
    print("Gereiht wird über den Rang im Kader, nicht über die Rohwerte – Risiko ist 0-100.")
    print(
        f"Probezeit (bis {broom_service.PROBATION_MATCHES} Matches): ein unentschuldigtes "
        f"Fehlen ist dort ein Sofortfall."
    )
    print(
        f"Rückkehrerinnen: {broom_service.RETURNER_DISCOUNT} Punkte extra – "
        f"zurückzukommen ist Loyalität."
    )
    print("Entschuldigtes Fehlen zählt nirgends, es wird nur als Kontext genannt.")


def _row(candidate: BroomCandidate, index: int) -> list[str]:
    delta = (
        f"{candidate.raw_delta / 1000:+.1f}k" if candidate.raw_delta is not None else "-"
    )
    cells = {
        # Derselbe Wert, den `stats perf --driven-only` zeigt - an der echten Saison
        # geprüft, Zeile für Zeile.
        "performance": f"{delta:>{COLUMN_WIDTHS['performance']}}",
        "motivation": (
            f"{candidate.km_total:>{COLUMN_WIDTHS['motivation']}}"
            if candidate.km_weeks
            else f"{'-':>{COLUMN_WIDTHS['motivation']}}"
        ),
        "reliability": f"{candidate.unexcused:>{COLUMN_WIDTHS['reliability']}}",
    }
    return [
        f"{index:>2}",
        f"{_short(candidate.name):<14}",
        f"{candidate.risk:>6.1f}",
        *[cells[key] for key in ORDER],
        # Gefahrene Matches statt des Multiplikators: die Zahl, aus der er entsteht.
        f"{candidate.driven_total:>{LOYALTY_WIDTH}}",
    ]


def _print_reasons(candidate: BroomCandidate) -> None:
    head = f"🧹 {candidate.name} ({candidate.player_id})"
    if candidate.immediate:
        head += " – Sofortfall"
    else:
        head += f" – Risiko {candidate.risk:.1f}"
        if candidate.loyalty_discount:
            head += f" (roh {candidate.raw_risk:.1f})"
    print(head)
    for reason in candidate.reasons:
        print(f"   • {reason}")


def _print_unrated(result: BroomResult) -> None:
    if not result.unrated:
        return
    print()
    print("Nicht bewertet (zu wenige Matches im Fenster – Neue und Rückkehrerinnen):")
    for entry in result.unrated[:UNRATED_LIMIT]:
        print(
            f"   {_short(entry.name):<14} id {entry.player_id:<4} {entry.reason}, "
            f"{entry.driven_total} insgesamt"
        )
    hidden = len(result.unrated) - UNRATED_LIMIT
    if hidden > 0:
        print(f"   … und {hidden} weitere")


def print_json(result: BroomResult) -> None:
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


def _short(name: str, width: int = 14) -> str:
    return name if len(name) <= width else name[: width - 1] + "…"
