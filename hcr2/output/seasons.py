from __future__ import annotations

from hcr2.models.season import Season
from hcr2.output.tables import print_table


def print_seasons(seasons: list[Season]) -> None:
    print_table(
        headers=[f"{'No.':3}", f"{'Name':<8}", f"{'Div':<6}"],
        rows=[
            [f"{season.number:>3}.", f"{season.name:<8}", f"{season.division:<6}"]
            for season in seasons
        ],
        width=25,
    )

