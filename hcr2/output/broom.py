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


# The data rows carry no emoji, so they always line up with each other. Only the
# header does, and an emoji is two display columns wide while Python counts it as
# one - so its cell is padded with two spaces to four *display* columns instead of
# being right-aligned to four characters, which would come out one too wide.
WIDTH = 64
ICON_CELL = "  "
DEFAULT_LIMIT = 5
# Ein zu kurzes Fenster macht aus dem Anhang eine Kaderliste, die nichts sagt, was
# die Kopfzeile nicht schon gesagt hat.
UNRATED_LIMIT = 10
# Below this many yardstick players the comparative factors stop meaning much.
MIN_COHORT = 8

# Reihenfolge der Faktorspalten - dieselbe wie die Gewichtung.
ORDER = tuple(key for key, _, _, _, _ in broom_service.FACTORS)


def print_result(result: BroomResult, *, limit: int = DEFAULT_LIMIT, show_all: bool = False) -> None:
    if result.status == "NO_MATCHES":
        print("⚠️ Keine Matches gespeichert.")
        return
    if result.status == "NO_ROSTER":
        print("⚠️ Keine aktiven PLTE-Spielerinnen.")
        return
    if result.status == "NO_DATA" or not result.candidates:
        print(
            f"⚠️ Keine Kaderzeile in den letzten {result.matches} Matches, "
            f"also ist niemand bewertbar."
        )
        return

    listed = result.candidates if show_all else result.candidates[:limit]
    # --all verbreitert die Tabelle, nicht die Begründung: 38 Blöcke sprengen jede
    # Discord-Nachricht, also bleiben die Blöcke am Kopf der Liste.
    explained = result.candidates[:limit]

    print(
        f"🧹 Besen – {len(listed)} von {len(result.candidates)} bewertet, "
        f"letzte {result.matches} Matches"
    )
    header = [
        f"GP-Korrektur {result.gp_slope:.2f}/GP",
        f"Team unentschuldigt {result.team_unexcused_rate * 100:.1f}%",
        f"Ø {result.team_km_average:.0f} km/Woche",
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

    print_table(
        headers=[
            f"{'#':>2}", f"{'Spielerin':<14}", f"{'Risiko':>6}",
            broom_service.LOYALTY_ICON + ICON_CELL,
            *[icon + ICON_CELL for *_, icon in broom_service.FACTORS],
        ],
        rows=[_row(candidate, index) for index, candidate in enumerate(listed, start=1)],
        width=WIDTH,
    )
    if any(candidate.immediate for candidate in listed):
        print(
            f"{broom_service.IMMEDIATE_ICON} = Sofortfall, nicht nach Punkten gereiht "
            f"– siehe unten"
        )

    for candidate in explained:
        print()
        _print_reasons(candidate)

    _print_unrated(result)
    # Legende zuletzt: sie ist Referenz, nicht Inhalt. Bei Ausgaben, die Discord auf
    # zwei Nachrichten aufteilt, gehört in die erste die Rangliste mit ihren
    # Begründungen - nicht die Erklärung der Spalten.
    _print_legend()


def _print_legend() -> None:
    print()
    print("Faktoren (100 = schlechtester Wert im Kader):")
    for _, label, weight, explanation, icon in broom_service.FACTORS:
        print(f"  {icon} {label} {weight:>2}  {explanation}")
    print(
        f"  {broom_service.LOYALTY_ICON} Loy     Zugehörigkeit: "
        f"x{broom_service.LOYALTY_FLOOR:.2f}-1.00 senkt das Risiko, "
        f"x{broom_service.PROBATION_PENALTY:.2f} hebt es"
    )
    print(
        f"  Probezeit (bis {broom_service.PROBATION_MATCHES} gefahrene Matches): ohne "
        f"Glättung gerechnet, ein"
    )
    print("  unentschuldigtes Fehlen ist dort schon ein Sofortfall.")
    print(
        f"  Rückkehrerinnen: Bonus x{broom_service.RETURNER_BONUS:.2f} auf den Schutz – "
        f"zurückzukommen ist Loyalität."
    )
    print("  📊 📉 🏆 bleiben leer (-), wo die Stichprobe zu dünn dafür ist.")
    print("  Entschuldigtes Fehlen zählt nicht, es wird nur als Kontext genannt.")


def _row(candidate: BroomCandidate, index: int) -> list[str]:
    values = {factor.key: factor.value for factor in candidate.factors}
    return [
        f"{index:>2}",
        f"{_short(candidate.name):<14}",
        # Ein Sofortfall wird nicht nach Punkten gereiht, eine Zahl würde also nur zum
        # falschen Vergleich einladen: die des einen realen Falls liegt unter den
        # nächsten vier, obwohl er der Fall ist.
        f"{'    ' + broom_service.IMMEDIATE_ICON if candidate.immediate else f'{candidate.risk:>6.1f}'}",
        f"{candidate.loyalty:>4.2f}",
        *[
            f"{values[key] * 100:>4.0f}" if values.get(key) is not None else f"{'-':>4}"
            for key in ORDER
        ],
    ]


def _print_reasons(candidate: BroomCandidate) -> None:
    head = f"🧹 {candidate.name} ({candidate.player_id})"
    if candidate.immediate:
        head += " – Sofortfall"
    else:
        head += f" – Risiko {candidate.risk:.1f}"
        if candidate.loyalty < 1.0:
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
