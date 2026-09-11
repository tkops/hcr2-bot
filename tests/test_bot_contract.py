"""Contract tests for the coupling between bot.py and the CLI.

bot.py does not import the package - it shells out to hcr2.py and parses the
printed output with regexes. That makes the output format a contract, and these
tests pin it: they render real CLI output through the same code paths the CLI
uses and then parse it with bot.py's own patterns. If someone reformats
hcr2/output/players.py, this fails instead of the Discord bot.

Importing bot.py needs a stubbed secrets_config and argv, because it validates
its config at import time.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

from modules import player
from tests.support import TemporaryDatabaseTestCase


def _import_bot():
    """Import bot.py with stubbed secrets so it works on a fresh checkout."""
    if "bot" in sys.modules:
        return sys.modules["bot"]

    stub = types.ModuleType("secrets_config")
    stub.CONFIG = {
        "dev": {
            "TOKEN": "test-token",
            "CHANNEL_IDS": [1],
            "ADMIN_CHANNEL_IDS": [2],
            "LEADER_ROLE_IDS": [3],
            "BIRTHDAY_CHANNEL_ID": 4,
        }
    }
    stub.NEXTCLOUD_AUTH = ("user", "password")

    with mock.patch.dict(sys.modules, {"secrets_config": stub}), \
            mock.patch.object(sys, "argv", ["bot.py", "dev"]):
        import bot  # noqa: PLC0415 - deliberately imported under stubs
    return bot


bot = _import_bot()


class BotOutputContractTests(TemporaryDatabaseTestCase):
    def test_player_show_output_is_parsable_by_bot_regexes(self) -> None:
        output = self.capture_stdout(player.handle_command, "show", ["--id", "1"])

        self.assertIsNotNone(bot.ID_LINE_RE.search(output), output)
        self.assertEqual(bot.ID_LINE_RE.search(output).group(1), "1")
        self.assertIsNotNone(bot.NAME_LINE_RE.search(output), output)
        self.assertEqual(bot.NAME_LINE_RE.search(output).group(1).strip(), "Alice")

    def test_bot_helpers_extract_id_and_name_from_show_output(self) -> None:
        output = self.capture_stdout(player.handle_command, "show", ["--id", "1"])

        self.assertEqual(bot._parse_player_name_from_show(output), "Alice")
        fields = bot._parse_show_fields(output)
        self.assertEqual(fields.get("ID"), "1")
        self.assertEqual(fields.get("Name"), "Alice")

    def test_birthday_ids_marker_is_parsable(self) -> None:
        output = self.capture_stdout(player.handle_command, "bday", ["today"])

        # The marker line is only emitted when somebody has a birthday today,
        # so assert on the pattern itself rather than on today's data.
        # Returned as strings because they go straight back into a CLI call.
        self.assertEqual(bot._parse_birthday_ids("BIRTHDAY_IDS: 1, 2, 3"), ["1", "2", "3"])
        self.assertEqual(bot._parse_birthday_ids("no marker here"), [])
        if "BIRTHDAY_IDS:" in output:
            self.assertTrue(bot._parse_birthday_ids(output))

    def test_team_regex_matches_the_teams_the_cli_accepts(self) -> None:
        for team in ("PLTE", "PL1", "PL9", "plte"):
            self.assertIsNotNone(bot.TEAM_RE.match(team), team)
        for team in ("PL0", "PL10", "XX", ""):
            self.assertIsNone(bot.TEAM_RE.match(team), team)


class BotErrorDetectionTests(TemporaryDatabaseTestCase):
    def test_exit_code_decides_instead_of_substring_search(self) -> None:
        self.assertTrue(bot._output_is_error(bot.CliResult("anything", ok=False)))
        self.assertFalse(bot._output_is_error(bot.CliResult("✅ done", ok=True)))

    def test_success_output_containing_error_words_is_not_an_error(self) -> None:
        """Regression: player names, opponents and notes may contain these words."""
        for text in (
            "✅ Match saved against Invalid Crew",
            "Name           : invalid_hero",
            "✅ Sheet imported (opponent: Not Found Racers)",
        ):
            with self.subTest(text=text):
                self.assertFalse(bot._output_is_error(bot.CliResult(text, ok=True)))

    def test_plain_strings_fall_back_to_the_status_prefix(self) -> None:
        self.assertTrue(bot._output_is_error("❌ Player 8 still has 786 match scores"))
        self.assertFalse(bot._output_is_error("✅ all good"))
        self.assertFalse(bot._output_is_error(""))

    def test_blocked_delete_is_reported_as_an_error(self) -> None:
        output = self.capture_stdout(player.delete_player, 1)

        self.assertTrue(bot._output_is_error(output))
        self.assertEqual(
            bot._clean_status_text(output).splitlines()[0],
            "Player 1 still has 1 match score – nothing was deleted.",
        )

    def test_cli_result_behaves_like_the_string_it_replaces(self) -> None:
        result = bot.CliResult("line one\nline two", ok=True)

        self.assertIsInstance(result, str)
        self.assertEqual(result.splitlines(), ["line one", "line two"])
        self.assertIn("line one", result)
        self.assertTrue(bool(result))
        self.assertFalse(bool(bot.CliResult("", ok=False)))


class DiscordMessageLengthTests(TemporaryDatabaseTestCase):
    """Discord drops a message over 2000 characters, so long output has to be split."""

    def test_a_long_table_is_split_on_line_boundaries(self) -> None:
        bot = _import_bot()
        text = "\n".join(f"row {index:03d} " + "x" * 40 for index in range(200))

        chunks = bot.codeblock_chunks(text, budget=500)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 500)
        # nothing lost and no row cut in half
        self.assertEqual("\n".join(chunks).split("\n"), text.split("\n"))

    def test_a_single_overlong_line_is_cut_rather_than_dropped(self) -> None:
        bot = _import_bot()
        chunks = bot.codeblock_chunks("y" * 1200, budget=500)

        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), "y" * 1200)

    def test_short_output_stays_one_chunk(self) -> None:
        bot = _import_bot()
        self.assertEqual(bot.codeblock_chunks("one\ntwo", budget=500), ["one\ntwo"])

    def test_a_full_roster_ranking_fits_one_message(self) -> None:
        """49 players is the real team size - it must not need splitting at all."""
        from hcr2.models.distance import DistanceRankRow
        from hcr2.output import distances as distance_output

        bot = _import_bot()
        rows = [
            DistanceRankRow(player_id=index, name=f"PL|Longish{index:02d}", km=900 - index * 7,
                            average=800 - index * 7, weeks=8)
            for index in range(49)
        ]
        output = self.capture_stdout(distance_output.print_ranking, 2026, 34, rows)

        self.assertLessEqual(len(output) + bot.CODEBLOCK_FENCE_LEN, bot.MAX_DISCORD_MSG_LEN)



class BroomShortcutTests(TemporaryDatabaseTestCase):
    """'.B' is the short form of '.stats broom'."""

    def test_digits_become_a_top_limit(self) -> None:
        bot = _import_bot()
        self.assertEqual(bot.broom_call(["10"]), ["stats", "broom", "--top", "10"])

    def test_words_map_to_the_flags_nobody_types_in_discord(self) -> None:
        bot = _import_bot()
        self.assertEqual(bot.broom_call(["all"]), ["stats", "broom", "--all"])
        self.assertEqual(
            bot.broom_call(["leader"]), ["stats", "broom", "--include-leaders"]
        )

    def test_no_arguments_means_the_cli_default(self) -> None:
        bot = _import_bot()
        self.assertEqual(bot.broom_call([]), ["stats", "broom"])

    def test_a_season_is_typed_as_s_plus_number(self) -> None:
        """Der Zeitraum ist sonst immer die laufende Saison - ohne diese Form käme
        eine abgeschlossene Saison in Discord gar nicht mehr an."""
        bot = _import_bot()
        self.assertEqual(bot.broom_call(["s63"]), ["stats", "broom", "--season", "63"])
        self.assertEqual(
            bot.broom_call(["s63", "3"]),
            ["stats", "broom", "--season", "63", "--top", "3"],
        )

    def test_unknown_arguments_are_passed_through(self) -> None:
        """So '--last 80' keeps working from Discord without a mapping per flag."""
        bot = _import_bot()
        self.assertEqual(
            bot.broom_call(["--last", "80"]), ["stats", "broom", "--last", "80"]
        )

    def test_a_digit_behind_a_flag_is_that_flags_value(self) -> None:
        """Not the top limit - '.B --last 80 3' has to mean both."""
        bot = _import_bot()
        self.assertEqual(
            bot.broom_call(["--last", "80", "3"]),
            ["stats", "broom", "--last", "80", "--top", "3"],
        )

    def test_the_shortcut_is_not_public(self) -> None:
        """Both entry points have to be leader-only, and they get there differently:
        '.B' is simply absent from PUBLIC_COMMANDS, so the channel and role check in
        on_message covers it. '.stats' *is* public, which is why the broom subcommand
        needs its own explicit gate - removing that gate would expose the list.
        """
        bot = _import_bot()
        self.assertFalse(bot.is_public(".B"))
        self.assertTrue(bot.is_public(".stats"))

        source = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
        self.assertIn('if sub == "broom" and not (leader and in_admin_channel):', source)
