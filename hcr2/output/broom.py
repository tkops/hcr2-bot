"""Ausgabe der Besen-Rangliste.

**Der Ton ist sachlich, nicht wertend.** Die Liste geht in ein Gespräch, in dem
jemand erfährt, dass sie gehen soll - Wörter wie "die Schwächsten" kommen dort nicht
an, und sie sind auch gar nicht gemeint: bewertet wird eine Fahrleistung in einem
Zeitraum, kein Mensch. Deshalb steht in der Legende "die geringste Fahrleistung" und
nicht "die Schwächste", und der Gleichstand wird von unten erklärt ("wer mehr
eingebracht hat, steht weiter unten") statt von oben.

**Die Ausgabe sagt "Ladys", nicht "Spielerinnen".** Das Team heißt Power Ladys, aber
es fahren auch Männer mit - die weibliche Form wäre also schlicht falsch, und
"SpielerInnen" liest sich in einer Tabellenspalte wie ein Tippfehler. "Ladys" ist die
Kurzform des Teamnamens und meint alle; so redet die Leitung auch im Channel.

Die Tabelle ist die Rangliste, die Blöcke darunter sind die Begründung, die Legende
am Ende ist das Punktesystem. Jede gelistete Lady bekommt ihre Zeile, weil
fünf Namen und eine Zahl nichts sind, womit eine Leitung in ein Gespräch gehen kann.

**Die Tabelle zeigt die Punkte, die Begründung die Zahlen dahinter.** Das ist die
Arbeitsteilung, auf der der ganze Umbau von Risiko auf Besenpunkte steht: die vier
Spalten müssen sich zur Gesamtzahl nachaddieren lassen (2+6+5-1 = 12), sonst kann
niemand nachrechnen - und die Zahl, aus der ein Punktwert entstanden ist, steht
darunter im Klartext, sonst kann niemand nachprüfen.
"""
from __future__ import annotations

import json
import textwrap
from dataclasses import asdict

from hcr2.models.broom import BroomCandidate, BroomResult
from hcr2.output.tables import print_table
from hcr2.services import broom as broom_service


# Kopf und Daten sind reiner Text, also richten sie sich immer aneinander aus - die
# frühere Emoji-Kopfzeile war zwei Anzeigespalten breit bei einem Zeichen Länge und
# rutschte je nach Discord-Client.
# Jede Achsenzelle trägt "<echter Wert> (<Punkte>)" - die breiteste ist Perf mit
# "-20.8k (10)". Der echte Wert führt, weil eine Leaderin mit "124 km/Woche" in ein
# Gespräch gehen kann und mit einer 2 nicht; die Punkte stehen daneben, damit sich die
# Gesamtzahl trotzdem nachaddieren lässt.
COLUMN_WIDTHS = {
    "motivation": 8,
    "performance": 11,
    "reliability": 6,
    "blocker": 5,
    "loyalty": 8,
}
# Der Tiebreaker steht **mit in der Tabelle**, obwohl er nicht mitreiht: bei
# Gleichstand entscheidet er den Platz, und dann muss man ihn sehen können, ohne die
# Liste zu verlassen. Vier Stellen reichen - im Topf reichte der höchste gemessene
# Wert bis 1465 (Saison 63).
TIEBREAK_WIDTH = 6
NAME_WIDTH = 13
BESEN_WIDTH = 5
# Neun Zellen (#, Name, Besen, fünf Achsen, Tiebreaker), also acht Trennzeichen.
WIDTH = (
    2 + NAME_WIDTH + BESEN_WIDTH + sum(COLUMN_WIDTHS.values()) + TIEBREAK_WIDTH + 8
)
# Ein zu kurzes Fenster macht aus dem Anhang eine Kaderliste, die nichts sagt, was
# die Kopfzeile nicht schon gesagt hat.
UNRATED_LIMIT = 10

# Reihenfolge der Punktespalten - dieselbe wie in der Legende.
ORDER = tuple(key for key, _, _ in broom_service.FACTORS)


def print_result(result: BroomResult, *, limit: int | None = None) -> None:
    """Tabelle und Punktesystem, sonst nichts.

    Die Begründungsblöcke pro Person sind weg: die Tabelle trägt die echten Werte, das
    Punktesystem darunter sagt, wie daraus Punkte werden, und damit steht jede Zeile
    für sich. Was die Blöcke zusätzlich hatten (Quote gegen den Teamschnitt, Einbrüche,
    Vorfälle vor dem Fenster), lebt in ``--json`` weiter - im Gespräch trägt die Zeile.

    ``limit`` kürzt die Tabelle; ohne ihn steht der ganze Topf da.
    """
    if result.status == "NO_MATCHES":
        if result.season is not None:
            print(f"⚠️ Keine Matches in Saison {result.season} gespeichert.")
        else:
            print("⚠️ Keine Matches gespeichert.")
        return
    if result.status == "NO_ROSTER":
        print("⚠️ Keine aktiven PLTE-Ladys.")
        return
    if result.status == "NO_DATA" or not result.candidates:
        _print_wrapped(
            f"⚠️ Keine Kaderzeile in {_window_label(result)}, also ist niemand bewertbar.",
            emoji=1,
        )
        return

    rows = result.candidates if limit is None else result.candidates[:limit]

    print(f"🧹 Besenliste – {_window_label(result)}{_leader_note(result)}")
    print()
    # Auch diese beiden laufen über den Umbruch: der Topf kann viele Eintrittsgründe
    # aufzählen, und eine Warnung, die breiter ist als die Tabelle, sieht aus wie ein
    # Fehler in der Ausgabe.
    _print_wrapped(_pool_label(result))
    if not result.km_weeks:
        _print_wrapped(
            "⚠️ Keine Kilometer im Zeitraum – alle bekommen die volle km-Strafe.",
            emoji=1,
        )
    print_table(
        headers=[
            f"{'#':>2}",
            f"{'Lady':<{NAME_WIDTH}}",
            f"{broom_service.BESEN_LABEL:>{BESEN_WIDTH}}",
            *[
                f"{label:>{COLUMN_WIDTHS[key]}}"
                for key, label, _ in broom_service.FACTORS
            ],
            f"{broom_service.TIEBREAK_LABEL:>{TIEBREAK_WIDTH}}",
        ],
        rows=[_row(candidate, index) for index, candidate in enumerate(rows, start=1)],
        width=WIDTH,
    )

    _print_unrated(result)
    # Die Legende steht am Ende: sie ist Referenz, nicht Inhalt.
    _print_legend(result)


def _pool_label(result: BroomResult) -> str:
    """Woraus der Topf besteht - der Eintrittsgrund ist die halbe Begründung.

    Ein unentschuldigter Fehltermin ist die bedingungslose Eintrittskarte, der Rest
    wird nach Leistung aufgefüllt. Wer das nicht danebenstehen sieht, liest die Liste
    als reine Leistungsrangliste und wundert sich über die guten Ladys darin.
    """
    by_absence = sum(1 for c in result.candidates if c.pool_reason == "unexcused")
    by_performance = len(result.candidates) - by_absence
    parts = []
    if by_absence:
        parts.append(f"{by_absence}x unentschuldigt gefehlt")
    if by_performance:
        parts.append(f"{by_performance}x nach Leistung aufgefüllt")
    return f"Topf ({len(result.candidates)}): " + ", ".join(parts or ["leer"])


def _leader_note(result: BroomResult) -> str:
    """Ob die Leader mitgezählt wurden - sonst tut ``--include-leaders`` sichtbar nichts.

    An Saison 65 wächst ``all_rated`` damit von 41 auf 50, und die Tabelle bleibt Zeile
    für Zeile dieselbe: kein Leader ist schwach genug für den Topf. Wer das Flag tippt,
    könnte ohne diesen Zusatz nicht erkennen, ob es angekommen ist.
    """
    return " · mit Leadern" if result.include_leaders else ""


def _window_label(result: BroomResult) -> str:
    """Woraus die Liste gerechnet ist - im Kopf, weil eine Rangliste ohne ihren
    Zeitraum nicht überprüfbar ist."""
    if result.season is None:
        return f"letzte {result.matches} Matches"
    return f"Saison {result.season} ({result.matches} Matches)"


def _print_legend(result: BroomResult) -> None:
    """Das Punktesystem als **Nachschlagetabelle**, nicht als Text.

    Die Spalten der Rangliste tragen die echten Werte; hier steht nur, wie aus einem
    Wert eine Punktzahl wird. Eine Zeile je Achse, in derselben Reihenfolge wie die
    Spalten - damit man von einer Zelle geradeaus nach unten schauen kann.

    **Nichts hier ist breiter als die Tabelle.** Der Umbruch wird gerechnet und nicht
    von Hand gesetzt: sonst reicht ein Wort mehr in einer Schwelle, und die Erklärung
    steht über die Liste hinaus - in einem Discord-Codeblock heißt das, dass die Zeile
    seitlich wegläuft, während die Tabelle daneben ordentlich endet.
    """
    svc = broom_service
    rows = [
        (
            svc.FACTOR_LABELS["motivation"],
            _tier_line(svc.KM_TIERS, svc.KM_POINTS_MIN, "<=", "darüber"),
        ),
        (
            svc.FACTOR_LABELS["performance"],
            f"Platz im Topf: +{svc.PERF_POINTS_MAX} für die geringste Fahrleistung "
            f"... +{svc.PERF_POINTS_MIN} für die höchste, jeder Wert genau einmal",
        ),
        (
            svc.FACTOR_LABELS["reliability"],
            f"gar nicht aufgetaucht: +{svc.UNEXCUSED_POINTS} je Mal",
        ),
        (
            svc.FACTOR_LABELS["blocker"],
            f"eingeloggt und nicht gefahren: +{svc.BLOCKER_POINTS} je Mal",
        ),
        (
            svc.FACTOR_LABELS["loyalty"],
            _tier_line(svc.TREUE_TIERS, svc.TREUE_MAX, "<", "ab"),
        ),
    ]
    label_width = max(len(label) for label, _ in rows)

    # Die gelesenen Wochen stehen dabei, wenn sie vom Fenster abweichen: die Truhe
    # wird nicht jede Woche gelesen, und "Schnitt aus fünf Wochen" wäre dann eine
    # Behauptung über Zahlen, die niemand eingetragen hat.
    weeks = f"letzten {svc.KM_WINDOW_WEEKS} Wochen"
    if result.km_weeks and result.km_weeks != svc.KM_WINDOW_WEEKS:
        weeks += f" ({result.km_weeks} davon in der Truhe eingetragen)"

    print()
    _print_wrapped(
        "Besenpunkte – je mehr Punkte, desto weiter oben steht man. In der Tabelle "
        "steht der echte Wert, die Punkte daneben in Klammern. So kommen sie zusammen:"
    )
    for label, line in rows:
        _print_wrapped(line, first=f"  {label:<{label_width}}  ")
    print()
    _print_wrapped(
        f"Im Topf ist, wer unentschuldigt gefehlt hat – immer, egal wie gut. Aufgefüllt "
        f"wird auf {svc.SHORTLIST_SIZE} nach der Fahrleistung der Saison. Entschuldigtes "
        f"Fehlen zählt nirgends mit."
    )
    _print_wrapped(f"Kilometer sind der Wochenschnitt der {weeks}.")
    _print_wrapped(
        f"Bei Gleichstand entscheiden die {svc.TIEBREAK_LABEL} der Saison – wer mehr "
        f"eingefahren hat, steht weiter unten."
    )


def _print_wrapped(text: str, *, first: str = "", emoji: int = 0) -> None:
    """Auf ``WIDTH`` umbrechen, Folgezeilen unter dem Textanfang.

    ``first`` ist das Präfix der ersten Zeile (bei den Achsen ihr Spaltenname); die
    Folgezeilen rücken genau so weit ein, damit die Erklärung einer Achse als ein
    Block stehen bleibt und nicht unter ihren eigenen Namen rutscht.

    ``emoji`` ist die Zahl der Emoji im Text. ``textwrap`` zählt in Zeichen, ein Emoji
    belegt aber **zwei** Anzeigespalten - ohne die Korrektur wäre eine Warnzeile genau
    um diese Differenz zu breit, und zwar nur manchmal.
    """
    for line in textwrap.wrap(
        text,
        width=WIDTH - emoji,
        initial_indent=first,
        subsequent_indent=" " * len(first),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [first.rstrip()]:
        print(line)


def _tier_line(tiers, beyond: int, compare: str, beyond_word: str) -> str:
    """Eine Staffel als Zeile: ``<=50 +3, <=150 +2, <=300 +1, darüber +0``.

    Das Vergleichszeichen ist ein Parameter, weil die beiden Staffeln es verschieden
    meinen: die Kilometerstufe greift bei ``<=`` (genau 50 km sind noch +3), die
    Treuestufe bei ``<`` (genau 15 Matches sind schon -1). Eine Legende, die das
    verwischt, ist an der Grenze falsch - und genau dort schaut jemand nach.
    """
    parts = [f"{compare}{limit} {points:+d}" for limit, points in tiers]
    parts.append(f"{beyond_word} {tiers[-1][0]} {beyond:+d}" if beyond_word == "ab"
                 else f"{beyond_word} {beyond:+d}")
    return ", ".join(parts)


def _row(candidate: BroomCandidate, index: int) -> list[str]:
    # Eine Achse ohne Wert und ohne Punkte bekommt nur den Strich: "- (0)" ist zehnmal
    # dieselbe Null in einer Spalte, in der fast nie etwas steht.
    cells = {
        f.key: f.value if f.value == "-" and not f.points else f"{f.value} ({f.points})"
        for f in candidate.factors
    }
    return [
        f"{index:>2}",
        f"{_short(candidate.name, NAME_WIDTH):<{NAME_WIDTH}}",
        f"{candidate.besen:>{BESEN_WIDTH}}",
        *[f"{cells.get(key, ''):>{COLUMN_WIDTHS[key]}}" for key in ORDER],
        f"{candidate.points_total:>{TIEBREAK_WIDTH}}",
    ]


def _print_unrated(result: BroomResult) -> None:
    if not result.unrated:
        return
    print()
    print("Nicht bewertet (keine Kaderzeile im Zeitraum):")
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
