from __future__ import annotations

from unittest import mock

from hcr2.repositories import players as player_repo
from hcr2.services import players as player_service
from modules import player
from tests.support import TemporaryDatabaseTestCase


class PlayerTests(TemporaryDatabaseTestCase):
    def test_player_repository_lists_and_loads_models(self) -> None:
        players = player_repo.list_players(sort_by="gp")
        self.assertEqual([player.name for player in players], ["Alice", "Betty"])
        self.assertEqual(player_repo.count_active_players(), 1)

        active_plte = player_repo.list_players(active_only=True, team_filter="PLTE")
        self.assertEqual([player.name for player in active_plte], ["Alice"])

        detail = player_repo.get_player_detail(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Alice")
        self.assertEqual(detail.match_count, 1)
        self.assertEqual(detail.first_match, "2021-06-05")
        self.assertEqual(detail.last_match, "2021-06-05")

    def test_player_repository_updates_active_and_deletes(self) -> None:
        player_repo.set_active(2, True)
        self.assertEqual(player_repo.count_active_players(), 2)

        player_repo.set_active(2, False)
        self.assertEqual(player_repo.get_player_detail(2).active, 0)

        player_repo.delete_player(2)
        self.assertIsNone(player_repo.get_player_detail(2))

    def test_player_repository_adds_player_and_checks_aliases(self) -> None:
        new_id = player_repo.add_player(
            name="Clara",
            alias="clara",
            garage_power=3000,
            active=True,
            birthday="02-14",
            team="PLTE",
            discord_name="clara#1",
        )
        self.assertTrue(player_repo.alias_exists("clara", team_scope="PLTE"))
        detail = player_repo.get_player_detail(new_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara")
        self.assertEqual(detail.birthday, "02-14")

        self.assertEqual(player_repo.update_player_fields(new_id, {"garage_power": 3500}), 1)
        self.assertEqual(player_repo.get_player_detail(new_id).garage_power, 3500)

    def test_player_repository_lists_birthdays(self) -> None:
        self.assertEqual(player_repo.get_birthday_player_ids("01-15"), [1])
        birthdays = player_repo.list_birthday_players(active_only=True)
        self.assertEqual([row.name for row in birthdays], ["Alice"])

    def test_player_repository_searches_and_lists_leaders(self) -> None:
        self.assertEqual([row.name for row in player_repo.search_players_like("ali")], ["Alice"])
        self.assertEqual(player_repo.resolve_player_id_exact("alice"), [1])
        self.assertEqual([row.name for row in player_repo.list_leaders()], ["Alice"])

    def test_player_service_lists_detail_and_mutates_basis(self) -> None:
        result = player_service.list_players(active_only=True, team_filter="PLTE")
        self.assertEqual(result.active_count, 1)
        self.assertEqual([player.name for player in result.rows], ["Alice"])

        detail = player_service.get_player_detail(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Alice")

        player_service.activate_player(2)
        self.assertEqual(player_service.list_players().active_count, 2)

        player_service.deactivate_player(2)
        self.assertEqual(player_service.get_player_detail(2).active, 0)

        player_service.delete_player(2)
        self.assertIsNone(player_service.get_player_detail(2))

    def test_player_service_adds_player_with_generated_alias(self) -> None:
        result = player_service.add_player(name="Clara Driver", team="PLTE", gp=3000, active=True)
        self.assertEqual(result.status, "ADDED")
        self.assertEqual(result.alias, "claradriver1")
        self.assertTrue(result.alias_generated)

        detail = player_service.get_player_detail(result.player_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara Driver")
        self.assertEqual(detail.alias, "claradriver1")

    def test_player_add_cli_defaults_team_to_plte(self) -> None:
        output = self.capture_stdout(player.handle_command, "add", ["--name", "Clara Driver"])
        self.assertIn("Clara Driver", output)

        detail = player_repo.get_player_detail(3)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara Driver")
        self.assertEqual(detail.team, "PLTE")
        self.assertEqual(detail.alias, "claradriver1")

    def test_player_add_cli_accepts_name_only_positional_form(self) -> None:
        output = self.capture_stdout(player.handle_command, "add", ["Clara Driver"])
        self.assertIn("Clara Driver", output)

        detail = player_repo.get_player_detail(3)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara Driver")
        self.assertEqual(detail.team, "PLTE")
        self.assertEqual(detail.garage_power, 0)

    def test_player_add_cli_rejects_old_multi_positional_form(self) -> None:
        output = self.capture_stdout(player.handle_command, "add", ["PLTE", "Clara Driver", "clara"])
        self.assertIn("Usage: player add <name>", output)
        self.assertIsNone(player_repo.get_player_detail(3))

    def test_player_service_rejects_plte_alias_conflict(self) -> None:
        result = player_service.add_player(name="Alice Clone", alias="alice", team="PLTE")
        self.assertEqual(result.status, "ALIAS_CONFLICT")

    def test_player_service_parses_birthday_and_validates_team(self) -> None:
        self.assertEqual(player_service.parse_birthday("15.01."), "01-15")
        self.assertIsNone(player_service.parse_birthday("2021-01-15"))
        self.assertTrue(player_service.is_valid_team("PLTE"))
        self.assertFalse(player_service.is_valid_team("PL10"))

    def test_player_service_edits_player_fields(self) -> None:
        result = player_service.edit_player(
            2,
            name="Betty Updated",
            gp=4500,
            active=True,
            birthday="02-14",
            team="PL1",
            discord_name="betty#2",
            leader=True,
        )
        self.assertEqual(result.status, "UPDATED")

        detail = player_service.get_player_detail(2)
        self.assertEqual(detail.name, "Betty Updated")
        self.assertEqual(detail.garage_power, 4500)
        self.assertEqual(detail.active, 1)
        self.assertEqual(detail.birthday, "02-14")
        self.assertEqual(detail.discord_name, "betty#2")
        self.assertEqual(detail.is_leader, 1)

    def test_player_service_edit_reports_noop_and_alias_conflict(self) -> None:
        self.assertEqual(player_service.edit_player(2).status, "NOTHING_TO_UPDATE")

        player_service.add_player(name="Ally", alias="ally", team="PLTE")
        conflict = player_service.edit_player(2, team="PLTE", alias="all")
        self.assertEqual(conflict.status, "ALIAS_CONFLICT")
        self.assertEqual(conflict.alias, "all")
        self.assertEqual(conflict.conflict_alias, "ally")

    def test_player_service_lists_birthdays(self) -> None:
        with mock.patch.object(player_service, "today_mm_dd", return_value="01-15"):
            self.assertEqual(player_service.birthday_ids_for_today(), [1])

        result = player_service.list_birthdays(active_only=True, num=1)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0][1].name, "Alice")

    def test_player_service_searches_and_lists_leaders(self) -> None:
        self.assertEqual([row.name for row in player_service.search_players("ali")], ["Alice"])
        self.assertEqual(player_service.resolve_player_id_exact("alice"), 1)
        self.assertEqual(player_service.resolve_player_id_fuzzy("ali").player_id, 1)
        self.assertEqual([row.name for row in player_service.list_leaders()], ["Alice"])

    def test_player_service_sets_and_clears_away(self) -> None:
        self.assertEqual(player_service.parse_weeks_token("2w"), 14)
        set_result = player_service.set_away_for_player(1, days=7)
        self.assertEqual(set_result.status, "SET")
        self.assertIsNotNone(set_result.brief)

        detail = player_service.get_player_detail(1)
        self.assertIsNotNone(detail.away_from)
        self.assertIsNotNone(detail.away_until)

        clear_result = player_service.clear_away_for_player(1)
        self.assertEqual(clear_result.status, "CLEARED")
        self.assertIsNotNone(clear_result.brief)
        self.assertIsNone(player_service.get_player_detail(1).away_until)
