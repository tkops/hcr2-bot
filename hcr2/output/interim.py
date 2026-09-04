"""Ausgabe des Zwischenstands - deutsch und postfertig.

Der Text geht direkt an die Teamleitung (Leader-Channel), deshalb deutsch wie bei
[[broom]]. Bewusst *kein* Codeblock und keine Spaltentabelle: die Nachricht wird am
Handy gelesen, dort bricht eine Tabelle um und wird unlesbar, Aufzählungen nicht.

`format_report` gibt den Text zurück, statt ihn zu drucken, damit dieselbe Ausgabe in
eine Datei für `scripts/post_discord.py` geschrieben werden kann.
"""
from __future__ import annotations

from collections.abc import Sequence

from hcr2.models.video import InterimPlayer, InterimReport


STATE_LABELS = [
    ("open", "Offen"),
    ("checkin", "Eingecheckt"),
    ("away", "Urlaub"),
    ("joined", "Erst nach Matchstart dazu"),
]


def print_no_match_found(match_id: int) -> None:
    print(f"❌ No match found for id {match_id}.")
    print("   Das Match zuerst anlegen: python3 hcr2.py match add --opponent <name> --teamevent <id>")


def print_report(report: InterimReport) -> None:
    print(format_report(report))
    for warning in report.warnings:
        print(f"⚠️  {warning}")
    for error in report.errors:
        print(f"❌ {error}")


def print_written(path: str) -> None:
    print(f"📝 {path}")
    print(f"   Posten: python3 scripts/post_discord.py --mode prod --channel birthday --file {path}")


def format_report(report: InterimReport) -> str:
    """Kurz halten ist hier eine Anforderung, keine Vorliebe: der Bericht wird mitten im
    Match gelesen und soll zu einer Handlung führen. Deshalb je Liste höchstens
    `TOP_LIMIT` Namen (bei "Luft nach oben" `BEHIND_LIMIT`, und dort ohne Restzähler),
    absolute Zahlen statt Prozenten und keine Erklärzeilen."""
    lines = [
        f"🏁 **Zwischenstand Match {report.match_id}** · {report.event_name} · gegen {report.opponent}",
        f"Match {report.position} von {report.event_matches}{_time_left(report)} · "
        f"{report.driven} von {report.roster_size} gefahren",
    ]

    if report.not_driven:
        lines.append("")
        lines.append(f"⏳ **Noch nicht gefahren ({len(report.not_driven)})**")
        for state, label in STATE_LABELS:
            names = [player.name for player in report.not_driven if player.state == state]
            if names:
                lines.append(f"{label}: {', '.join(names)}")

    if report.aborted:
        lines.append("")
        lines.append("🛑 **Wirkt abgebrochen**")
        lines.extend(_target_lines(report.aborted, report))
        lines.extend(_rest(report.aborted_more))

    if report.behind:
        lines.append("")
        lines.append("📉 **Luft nach oben**")
        lines.extend(_target_lines(report.behind, report))

    if report.improved:
        lines.append("")
        lines.append("🌟 **Steigerungen**")
        for player in report.improved:
            lines.append(f"• {player.name} {_num(player.base)} → {_num(player.score)}")

    if report.newcomers:
        lines.append("")
        lines.append("🆕 **Neu im Team**")
        for player in report.newcomers:
            score = _num(player.score) if player.score else "noch nichts"
            lines.append(f"• {player.name} {score} ({player.note})")

    lines.append("")
    lines.append(_footer(report))
    return "\n".join(lines)


def _target_lines(players: Sequence[InterimPlayer], report: InterimReport) -> list[str]:
    """Absolute Zahlen: was sie hat, was beim Tempo des Teams drin wäre. Die Prozentzahl
    dahinter stand vorher hier und war für die Leitung nur Rechenarbeit."""
    return [
        f"• {player.name} {_num(player.score)} · möglich ~{_num(_expected(player, report))}"
        for player in players
    ]


def _rest(count: int) -> list[str]:
    return [f"… und {count} weitere"] if count else []


def _expected(player: InterimPlayer, report: InterimReport) -> int:
    """Was sie beim Tempo des Teams jetzt stehen müsste - der Vergleich, den die
    Prozentzahl macht, in Punkten ausgeschrieben."""
    if not report.pace:
        return player.base
    return round(player.base * report.pace)


def _time_left(report: InterimReport) -> str:
    return f" · noch {report.time_left}" if report.time_left else ""


def _footer(report: InterimReport) -> str:
    if report.reference == "event":
        return "_Nichts eingetragen. Vergleich: eigener Score aus dem Event, gegen das Teamtempo._"
    return "_Nichts eingetragen. Erstes Match des Events, Vergleich gegen den eigenen Schnitt._"


def _num(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")
