from __future__ import annotations

from hcr2.repositories import matches as match_repo
from hcr2.repositories import seasons as season_repo
from hcr2.repositories import teamevents as teamevent_repo
from hcr2.services import vehicles as vehicle_service
from modules import season, teamevent, vehicle
from tests.support import TemporaryDatabaseTestCase


class CoreDomainTests(TemporaryDatabaseTestCase):
    def test_vehicle_list_reads_from_configured_database(self) -> None:
        output = self.capture_stdout(vehicle.handle_command, "list", [])
        self.assertIn("Hill Climber", output)
        self.assertIn("Rally Car", output)
        self.assertIn("hc", output)
        self.assertIn("rc", output)

    def test_vehicle_service_lists_models(self) -> None:
        vehicles = vehicle_service.list_vehicles()
        self.assertEqual([vehicle.name for vehicle in vehicles], ["Hill Climber", "Rally Car"])
        self.assertEqual([vehicle.shortname for vehicle in vehicles], ["hc", "rc"])

    def test_vehicle_service_adds_and_updates_vehicle(self) -> None:
        vehicle_service.add_vehicle("Dune Buggy", "db")
        added = [vehicle for vehicle in vehicle_service.list_vehicles() if vehicle.shortname == "db"]
        self.assertEqual(len(added), 1)

        changed = vehicle_service.edit_vehicle(added[0].id, name="Desert Buggy")
        self.assertTrue(changed)
        updated = [vehicle for vehicle in vehicle_service.list_vehicles() if vehicle.id == added[0].id]
        self.assertEqual(updated[0].name, "Desert Buggy")

    def test_vehicle_service_rejects_empty_update(self) -> None:
        self.assertFalse(vehicle_service.edit_vehicle(1))

    def test_season_list_filters_by_number(self) -> None:
        output = self.capture_stdout(season.handle_command, "list", ["--number", "2"])
        self.assertIn("Jun 21", output)
        self.assertIn("DIV1", output)
        self.assertNotIn("May 21", output)

    def test_season_repository_lists_models(self) -> None:
        seasons = season_repo.list_all()
        self.assertEqual([season.number for season in seasons], [1, 2])
        self.assertEqual([season.name for season in seasons], ["May 21", "Jun 21"])
        self.assertEqual([season.division for season in seasons], ["CC", "DIV1"])

    def test_season_repository_adds_updates_and_deletes(self) -> None:
        self.assertEqual(season_repo.get_next_season_number(), 3)

        season_repo.add_season(3, "Jul 21", "2021-07-01", "DIV2")
        self.assertTrue(season_repo.season_exists(3))
        self.assertEqual(season_repo.list_by_number(3)[0].division, "DIV2")

        season_repo.update_division(3, "DIV3")
        self.assertEqual(season_repo.list_by_number(3)[0].division, "DIV3")

        season_repo.delete_season(3)
        self.assertFalse(season_repo.season_exists(3))

    def test_match_repository_lists_and_loads_models(self) -> None:
        matches = match_repo.list_matches(season_number=2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].event_name, "Teamcup")
        self.assertEqual(matches[0].opponent, "Rivals")

        detail = match_repo.get_match(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.score_ladys, 123)
        self.assertEqual(detail.score_opponent, 111)

    def test_match_repository_adds_updates_and_deletes(self) -> None:
        self.assertTrue(match_repo.teamevent_exists(1))
        self.assertEqual(match_repo.latest_teamevent_id(), 1)
        self.assertEqual(match_repo.latest_match_start_between("2021-06-01", "2021-07-01"), "2021-06-05")

        match_repo.add_match(
            teamevent_id=1,
            season_number=2,
            start="2021-06-07",
            opponent="Challengers",
            score_ladys=200,
            score_opponent=199,
        )
        added = [match for match in match_repo.list_matches(season_number=2) if match.opponent == "Challengers"]
        self.assertEqual(len(added), 1)

        rowcount = match_repo.update_match(added[0].id, {"opponent": "Updated"})
        self.assertEqual(rowcount, 1)
        self.assertEqual(match_repo.get_match(added[0].id).opponent, "Updated")

        match_repo.delete_match(added[0].id)
        self.assertIsNone(match_repo.get_match(added[0].id))

    def test_teamevent_repository_lists_and_loads_models(self) -> None:
        events = teamevent_repo.list_latest()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "Teamcup")
        self.assertEqual(teamevent_repo.latest_iso_week(), (2021, 21))

        detail = teamevent_repo.get_teamevent(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.tracks, 4)

    def test_teamevent_repository_adds_updates_vehicles_and_deletes(self) -> None:
        self.assertEqual(teamevent_repo.resolve_vehicle_id("hc"), 1)
        self.assertEqual(teamevent_repo.resolve_vehicle_id("Rally Car", allow_name_lookup=True), 2)

        teamevent_id, invalid = teamevent_repo.add_teamevent(
            name="New Cup",
            iso_year=2021,
            iso_week=22,
            tracks=5,
            max_score_per_track=12000,
            vehicle_ids=[1, 2],
        )
        self.assertIsNotNone(teamevent_id)
        self.assertEqual(invalid, [])
        self.assertEqual([vehicle.id for vehicle in teamevent_repo.list_event_vehicles(teamevent_id)], [1, 2])

        rowcount = teamevent_repo.update_teamevent(teamevent_id, {"name": "Updated Cup"})
        self.assertEqual(rowcount, 1)
        self.assertEqual(teamevent_repo.get_teamevent(teamevent_id).name, "Updated Cup")

        warnings = teamevent_repo.replace_event_vehicles(teamevent_id, [2])
        self.assertEqual(warnings, [])
        self.assertEqual([vehicle.id for vehicle in teamevent_repo.list_event_vehicles(teamevent_id)], [2])

        teamevent_repo.clear_event_vehicles(teamevent_id)
        self.assertEqual(teamevent_repo.list_event_vehicles(teamevent_id), [])

        teamevent_repo.delete_teamevent(teamevent_id)
        self.assertIsNone(teamevent_repo.get_teamevent(teamevent_id))

    def test_teamevent_add_cli_accepts_name_only_positional_form(self) -> None:
        output = self.capture_stdout(teamevent.handle_command, "add", ["New Cup"])
        self.assertIn("✅ Team event added:", output)

        detail = teamevent_repo.get_teamevent(2)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "New Cup")
        self.assertEqual(detail.iso_year, 2021)
        self.assertEqual(detail.iso_week, 22)
        self.assertEqual(detail.tracks, 4)
        self.assertEqual(detail.max_score_per_track, 15000)

    def test_teamevent_add_cli_rejects_old_multi_positional_form(self) -> None:
        output = self.capture_stdout(teamevent.handle_command, "add", ["New Cup", "2021/W22", "hc", "5", "12000"])
        self.assertIn('Usage: teamevent add "<name>"', output)
        self.assertIsNone(teamevent_repo.get_teamevent(2))

    def test_teamevent_add_cli_accepts_flag_form_for_optional_values(self) -> None:
        output = self.capture_stdout(
            teamevent.handle_command,
            "add",
            ["--name", "New Cup", "--week", "2021/W22", "--vehicles", "hc,rc", "--tracks", "5", "--score", "12000"],
        )
        self.assertIn("✅ Team event added:", output)

        detail = teamevent_repo.get_teamevent(2)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "New Cup")
        self.assertEqual(detail.iso_year, 2021)
        self.assertEqual(detail.iso_week, 22)
        self.assertEqual(detail.tracks, 5)
        self.assertEqual(detail.max_score_per_track, 12000)
        self.assertEqual([vehicle.id for vehicle in teamevent_repo.list_event_vehicles(2)], [1, 2])
