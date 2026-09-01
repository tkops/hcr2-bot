from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from scripts.post_discord import (
    MAX_LEN,
    build_parser,
    main,
    resolve_channel,
    split_message,
)


CONFIG = {
    "TOKEN": "token",
    "CHANNEL_IDS": [111],
    "ADMIN_CHANNEL_IDS": [222],
    "BIRTHDAY_CHANNEL_ID": 333,
}


class ResolveChannelTests(unittest.TestCase):
    def test_names_map_to_the_same_ids_the_bot_uses(self) -> None:
        self.assertEqual(resolve_channel(CONFIG, "user"), 111)
        self.assertEqual(resolve_channel(CONFIG, "admin"), 222)
        self.assertEqual(resolve_channel(CONFIG, "birthday"), 333)

    def test_raw_id_passes_through(self) -> None:
        self.assertEqual(resolve_channel(CONFIG, "1007618361045307543"), 1007618361045307543)

    def test_unknown_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_channel(CONFIG, "leaders")

    def test_missing_key_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_channel({"ADMIN_CHANNEL_IDS": []}, "admin")
        with self.assertRaises(ValueError):
            resolve_channel({}, "birthday")


class SplitMessageTests(unittest.TestCase):
    def test_short_text_stays_one_message(self) -> None:
        self.assertEqual(split_message("hallo\nwelt"), ["hallo\nwelt"])

    def test_splits_on_line_boundaries(self) -> None:
        text = "\n".join("x" * 90 for _ in range(30))
        parts = split_message(text, limit=200)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 200)
            self.assertTrue(all(line == "x" * 90 for line in part.split("\n")))

    def test_one_overlong_line_is_hard_split(self) -> None:
        parts = split_message("y" * 250, limit=100)
        self.assertEqual([len(p) for p in parts], [100, 100, 50])

    def test_nothing_is_lost(self) -> None:
        text = "\n".join(f"Zeile {n}" for n in range(200))
        self.assertEqual("\n".join(split_message(text, limit=64)), text)


class MainTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("scripts.post_discord.load_config", return_value=CONFIG), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_does_not_post(self) -> None:
        with mock.patch("scripts.post_discord.post") as posted:
            code, out, _ = self._run(
                ["--mode", "prod", "--channel", "admin", "--text", "hallo", "--dry-run"]
            )
        posted.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("hallo", out)
        self.assertIn("222", out)

    def test_long_message_is_refused_without_split(self) -> None:
        with mock.patch("scripts.post_discord.post") as posted:
            code, _, err = self._run(
                ["--mode", "prod", "--channel", "user", "--text", "z" * (MAX_LEN + 1)]
            )
        posted.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("--split", err)

    def test_empty_message_is_refused(self) -> None:
        with mock.patch("scripts.post_discord.post") as posted:
            code, _, err = self._run(["--mode", "prod", "--channel", "user", "--text", "  "])
        posted.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("❌", err)

    def test_posts_every_part_to_the_resolved_channel(self) -> None:
        with mock.patch("scripts.post_discord.post", return_value={"id": "1"}) as posted:
            code, _, _ = self._run(
                [
                    "--mode", "prod", "--channel", "birthday",
                    "--text", "\n".join("w" * 500 for _ in range(6)),
                    "--split",
                ]
            )
        self.assertEqual(code, 0)
        self.assertGreater(posted.call_count, 1)
        for call in posted.call_args_list:
            self.assertEqual(call.args[0], "token")
            self.assertEqual(call.args[1], 333)
            self.assertLessEqual(len(call.args[2]), MAX_LEN)

    def test_mode_is_mandatory(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            build_parser().parse_args(["--channel", "user", "--text", "hi"])


if __name__ == "__main__":
    unittest.main()
