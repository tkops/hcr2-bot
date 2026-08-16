from __future__ import annotations

from hcr2.db.connection import connect_dict_db
# Same window as the distance repository, so profile and ranking agree on "average".
from hcr2.repositories.distances import AVERAGE_WINDOW as DISTANCE_AVERAGE_WINDOW
from hcr2.models.player import (
    PlayerAbsentRow,
    PlayerBirthdayRow,
    PlayerBrief,
    PlayerDetail,
    PlayerLeaderRow,
    PlayerListRow,
    PlayerSearchRow,
)


def list_players(*, active_only: bool = False, sort_by: str = "gp", team_filter: str | None = None) -> list[PlayerListRow]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        query = """
            SELECT id, name, alias, garage_power, active, created_at,
                   birthday, team, COALESCE(discord_name,'-') AS discord_name,
                   COALESCE(is_leader,0) AS is_leader,
                   active_modified, away_until
            FROM players
        """
        conditions: list[str] = []
        params: list[object] = []
        if active_only:
            conditions.append("active = 1")
        if team_filter:
            conditions.append("UPPER(team) = ?")
            params.append(team_filter.upper())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        if sort_by == "name":
            query += " ORDER BY name COLLATE NOCASE"
        else:
            query += " ORDER BY garage_power DESC"

        cur.execute(query, params)
        return [_list_row_from_mapping(row) for row in cur.fetchall()]


def count_active_players() -> int:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM players WHERE active = 1")
        return int(cur.fetchone()["cnt"])


def get_birthday_player_ids(birthday: str) -> list[int]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM players
            WHERE birthday = ?
            ORDER BY name COLLATE NOCASE
            """,
            (birthday,),
        )
        return [row["id"] for row in cur.fetchall()]


def list_birthday_players(*, active_only: bool = False) -> list[PlayerBirthdayRow]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        query = """
            SELECT id, name, birthday, COALESCE(emoji,'') AS emoji, COALESCE(active,0) AS active
            FROM players
            WHERE birthday IS NOT NULL AND birthday != ''
        """
        if active_only:
            query += " AND active = 1"
        cur.execute(query)
        return [
            PlayerBirthdayRow(
                id=row["id"],
                name=row["name"],
                birthday=row["birthday"],
                emoji=row["emoji"],
                active=row["active"],
            )
            for row in cur.fetchall()
        ]


def search_players_like(term: str) -> list[PlayerSearchRow]:
    pattern = f"%{term.lower()}%"
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, alias, garage_power, active,
                   COALESCE(discord_name,'') AS discord_name
            FROM players
            WHERE LOWER(name) LIKE ?
               OR LOWER(alias) LIKE ?
               OR LOWER(COALESCE(discord_name,'')) LIKE ?
            ORDER BY name COLLATE NOCASE
            """,
            (pattern, pattern, pattern),
        )
        return [
            PlayerSearchRow(
                id=row["id"],
                name=row["name"],
                alias=row["alias"],
                garage_power=row["garage_power"],
                active=row["active"],
                discord_name=row["discord_name"],
            )
            for row in cur.fetchall()
        ]


def resolve_player_id_exact(term: str) -> list[int]:
    if term.isdigit():
        player_id = int(term)
        with connect_dict_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM players WHERE id = ?", (player_id,))
            row = cur.fetchone()
            return [row["id"]] if row else []

    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM players
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(alias) = LOWER(?)
               OR LOWER(COALESCE(discord_name,'')) = LOWER(?)
            """,
            (term, term, term),
        )
        return [row["id"] for row in cur.fetchall()]


def find_player_ids_by_name(name: str) -> list[int]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM players
            WHERE LOWER(name) = LOWER(?)
            """,
            (name.strip(),),
        )
        return [row["id"] for row in cur.fetchall()]


def find_player_ids_by_discord(discord_name: str) -> list[int]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM players
            WHERE LOWER(discord_name) = LOWER(?)
            """,
            (discord_name.strip(),),
        )
        return [row["id"] for row in cur.fetchall()]


def get_player_brief(player_id: int) -> PlayerBrief | None:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, alias, discord_name
            FROM players
            WHERE id = ?
            """,
            (player_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return PlayerBrief(id=row["id"], name=row["name"], alias=row["alias"], discord_name=row["discord_name"])


def set_away(player_id: int, away_from: str, away_until: str) -> None:
    with connect_dict_db() as conn:
        conn.execute(
            """
            UPDATE players
               SET away_from = ?, away_until = ?
             WHERE id = ?
            """,
            (away_from, away_until, player_id),
        )


def clear_away(player_id: int) -> None:
    with connect_dict_db() as conn:
        conn.execute(
            """
            UPDATE players
               SET away_from = NULL, away_until = NULL
             WHERE id = ?
            """,
            (player_id,),
        )


def list_leaders() -> list[PlayerLeaderRow]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, COALESCE(discord_name, '-') AS discord_name
            FROM players
            WHERE COALESCE(is_leader, 0) = 1
            ORDER BY name COLLATE NOCASE
            """
        )
        return [
            PlayerLeaderRow(id=row["id"], name=row["name"], discord_name=row["discord_name"])
            for row in cur.fetchall()
        ]


def list_absent_players() -> list[PlayerAbsentRow]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, team, away_until
            FROM players
            WHERE away_from IS NOT NULL
              AND away_until IS NOT NULL
              AND datetime(away_from) <= datetime('now')
              AND datetime(away_until) >= datetime('now')
            """
        )
        return [
            PlayerAbsentRow(
                id=row["id"],
                name=row["name"] or "-",
                team=row["team"] or "-",
                away_until=row["away_until"][:19] if row["away_until"] else "-",
            )
            for row in cur.fetchall()
        ]


def get_player_detail(player_id: int) -> PlayerDetail | None:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, alias, garage_power, active, birthday, team, discord_name,
                   created_at, last_modified, active_modified, away_from, away_until,
                   COALESCE(is_leader, 0) AS is_leader,
                   about, preferred_vehicles, playstyle, language, emoji
            FROM players
            WHERE id = ?
            """,
            (player_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        cur.execute(
            """
            SELECT
                COUNT(*) AS match_count,
                MIN(substr(m.start, 1, 10)) AS first_match,
                MAX(substr(m.start, 1, 10)) AS last_match
            FROM matchscore ms
            JOIN match m ON ms.match_id = m.id
            WHERE ms.player_id = ?
            """,
            (player_id,),
        )
        match_row = cur.fetchone()

        # Average over the recent weeks, not over all time - it describes current form.
        cur.execute(
            """
            SELECT AVG(km) AS avg_km, COUNT(*) AS km_weeks
            FROM (SELECT km FROM distance WHERE player_id = ?
                  ORDER BY year DESC, week DESC LIMIT ?)
            """,
            (player_id, DISTANCE_AVERAGE_WINDOW),
        )
        return _detail_from_mapping(row, match_row, cur.fetchone())


def set_active(player_id: int, active: bool) -> None:
    with connect_dict_db() as conn:
        conn.execute("UPDATE players SET active = ? WHERE id = ?", (1 if active else 0, player_id))


def delete_player(player_id: int) -> None:
    with connect_dict_db() as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (player_id,))


def alias_exists(alias: str, *, team_scope: str | None = None) -> bool:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        if team_scope == "PLTE":
            cur.execute("SELECT 1 FROM players WHERE LOWER(alias)=LOWER(?) AND team='PLTE' LIMIT 1", (alias,))
        else:
            cur.execute("SELECT 1 FROM players WHERE LOWER(alias)=LOWER(?) LIMIT 1", (alias,))
        return cur.fetchone() is not None


def add_player(
    *,
    name: str,
    alias: str | None,
    garage_power: int,
    active: bool,
    birthday: str | None,
    team: str,
    discord_name: str | None,
) -> int:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, alias, garage_power, int(active), birthday, team, discord_name),
        )
        return int(cur.lastrowid)


def get_player_team_alias(player_id: int) -> tuple[str | None, str | None] | None:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT team, alias FROM players WHERE id = ?", (player_id,))
        row = cur.fetchone()
        return (row["team"], row["alias"]) if row else None


def list_plte_aliases_except(player_id: int) -> list[tuple[int, str | None]]:
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, alias FROM players
            WHERE team = 'PLTE' AND id != ?
            """,
            (player_id,),
        )
        return [(row["id"], row["alias"]) for row in cur.fetchall()]


def update_player_fields(player_id: int, updates: dict[str, object]) -> int:
    if not updates:
        return 0

    fields = [f"{column} = ?" for column in updates]
    values = list(updates.values()) + [player_id]
    with connect_dict_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE players SET {', '.join(fields)} WHERE id = ?", values)
        return cur.rowcount


def _list_row_from_mapping(row) -> PlayerListRow:
    return PlayerListRow(
        id=row["id"],
        name=row["name"],
        alias=row["alias"],
        garage_power=row["garage_power"],
        active=row["active"],
        created_at=row["created_at"],
        birthday=row["birthday"],
        team=row["team"],
        discord_name=row["discord_name"],
        is_leader=row["is_leader"],
        active_modified=row["active_modified"],
        away_until=row["away_until"],
    )


def _detail_from_mapping(row, match_row, distance_row=None) -> PlayerDetail:
    return PlayerDetail(
        id=row["id"],
        name=row["name"],
        alias=row["alias"],
        garage_power=row["garage_power"],
        active=row["active"],
        birthday=row["birthday"],
        team=row["team"],
        discord_name=row["discord_name"],
        created_at=row["created_at"],
        last_modified=row["last_modified"],
        active_modified=row["active_modified"],
        away_from=row["away_from"],
        away_until=row["away_until"],
        is_leader=row["is_leader"],
        about=row["about"],
        preferred_vehicles=row["preferred_vehicles"],
        playstyle=row["playstyle"],
        language=row["language"],
        emoji=row["emoji"],
        match_count=(match_row["match_count"] or 0) if match_row else 0,
        first_match=match_row["first_match"] if match_row else None,
        last_match=match_row["last_match"] if match_row else None,
        avg_km=float(distance_row["avg_km"] or 0) if distance_row else 0.0,
        km_weeks=int(distance_row["km_weeks"] or 0) if distance_row else 0,
    )
