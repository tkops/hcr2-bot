from __future__ import annotations

from collections.abc import Iterable


def render_table(*, headers: list[str], rows: Iterable[list[str]], width: int) -> str:
    lines = [" ".join(headers), "-" * width]
    lines.extend(" ".join(row) for row in rows)
    return "\n".join(lines)


def print_table(*, headers: list[str], rows: Iterable[list[str]], width: int) -> None:
    print(render_table(headers=headers, rows=rows, width=width))

