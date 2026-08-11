from __future__ import annotations

from hcr2.services.deletions import DeleteOutcome


KIND_LABELS = {
    "player": "Player",
    "match": "Match",
    "season": "Season",
    "teamevent": "Team event",
}

HINTS = {
    "player": "Move the scores to the right player first (matchscore edit <id> --player <id>).",
    "match": "Delete or move its scores first (matchscore list --match <id>).",
    "season": "Its matches must be deleted or moved to another season first.",
    "teamevent": "Its matches must be deleted or moved to another team event first.",
}


def print_delete_not_found(outcome: DeleteOutcome) -> None:
    label = KIND_LABELS.get(outcome.kind, outcome.kind.capitalize())
    print(f"❌ {label} {outcome.key} does not exist – nothing was deleted.")


def print_delete_blocked(outcome: DeleteOutcome) -> None:
    label = KIND_LABELS.get(outcome.kind, outcome.kind.capitalize())
    blockers = ", ".join(f"{count} {name}" for name, count in outcome.blocks)
    print(f"❌ {label} {outcome.key} still has {blockers} – nothing was deleted.")
    hint = HINTS.get(outcome.kind)
    if hint:
        print(f"   {hint}")
