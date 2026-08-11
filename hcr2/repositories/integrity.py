from __future__ import annotations

from hcr2.db.connection import connect_db


def count_referencing_rows(table: str, column: str, value) -> int:
    """Count rows in `table` pointing at `value` via `column`.

    Table and column are never user input: they come from the DEPENDENCIES map
    in hcr2/services/deletions.py.
    """
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (value,))
        return int(cur.fetchone()[0])
