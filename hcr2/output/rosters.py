from __future__ import annotations

from collections.abc import Sequence

from hcr2.models.roster import PendingAddition, RosterPlan
from hcr2.output.tables import print_table


KIND_ICONS = {
    "GP": "⚡",
    "RENAME": "✏️ ",
    "ADD": "➕",
    "REACTIVATE": "♻️ ",
    "DEACTIVATE": "➖",
}

KIND_ORDER = ("ADD", "REACTIVATE", "DEACTIVATE", "RENAME", "GP")


def print_plan_errors(errors: Sequence[str]) -> None:
    print("❌ Roster update aborted:")
    for message in errors:
        print(" -", message)


def print_plan(plan: RosterPlan, *, applied: bool = False) -> None:
    if plan.errors and not applied:
        print_plan_errors(plan.errors)

    for kind in KIND_ORDER:
        rows = [change for change in plan.changes if change.kind == kind]
        if not rows:
            continue
        print()
        print(f"{KIND_ICONS.get(kind, '·')} {kind} ({len(rows)})")
        for change in rows:
            marker = "" if change.status in ("", "OK") else f"  ❌ {change.status}"
            player = f"{change.player_id}" if change.player_id else "new"
            print(f"   {player:>5}  {change.name:<24} {change.detail}{marker}")

    for message in plan.notes:
        print(f"🔎 {message}")
    for message in plan.warnings:
        print(f"⚠️  {message}")


def print_pending(pending: Sequence[PendingAddition]) -> None:
    """The whole point of the roster flow: never guess whether someone was here before."""
    if not pending:
        return
    print()
    print(f"❓ {len(pending)} addition(s) need your decision - new member, or back again?")
    for addition in pending:
        reading = addition.reading
        print()
        print(f"   '{reading.name}' (garage power {reading.garage_power})")
        if not addition.candidates:
            print("      no similar player found - looks genuinely new")
        else:
            print_table(
                headers=[f"      {'ID':>5}", f"{'Player':<24}", f"{'Team':<6}", f"{'Act':>3}", f"{'GP':>7}", "Match"],
                rows=[
                    [
                        f"      {c.player_id:>5}",
                        f"{c.name:<24}",
                        f"{(c.team or '-'):<6}",
                        f"{c.active:>3}",
                        f"{c.garage_power:>7}",
                        f"{c.similarity:.0%}",
                    ]
                    for c in addition.candidates
                ],
                width=66,
            )
        print(f'      → new:        {{"name": "{reading.name}", "garage_power": {reading.garage_power}, "new": true}}')
        print(f'      → came back:  {{"name": "{reading.name}", "garage_power": {reading.garage_power}, "reactivate": <id>}}')


def print_summary(plan: RosterPlan, *, dry_run: bool) -> None:
    counts = {kind: len([c for c in plan.changes if c.kind == kind]) for kind in KIND_ORDER}
    summary = ", ".join(f"{counts[kind]} {kind.lower()}" for kind in KIND_ORDER if counts[kind])
    summary = summary or "no changes"

    if dry_run:
        print()
        print(f"ℹ️  Dry run: {summary}; {plan.unchanged} unchanged. Nothing written.")
        return

    failed = [change for change in plan.changes if change.status not in ("", "OK")]
    print()
    print(f"✅ Roster updated: {summary}; {plan.unchanged} unchanged, {len(failed)} failed.")


def print_needs_decision() -> None:
    print("❌ Roster update aborted: every addition needs \"new\" or \"reactivate\" first.")
