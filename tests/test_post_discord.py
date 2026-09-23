from __future__ import annotations

import contextlib
import datetime
import io
import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock

from scripts.post_discord import (
    MAX_ATTACHMENT_BYTES,
    MAX_LEN,
    _carries_image,
    build_parser,
    find_existing_image,
    main,
    parse_since,
    read_message,
    resolve_channel,
    resolve_image,
    split_message,
)


CONFIG = {
    "TOKEN": "token",
    "CHANNEL_IDS": [111],
    "ADMIN_CHANNEL_IDS": [222],
    "BIRTHDAY_CHANNEL_ID": 333,
    "PODIUM_CHANNEL_ID": 444,
    "TEAMCHAT_CHANNEL_ID": 555,
}


class ResolveChannelTests(unittest.TestCase):
    def test_names_map_to_the_same_ids_the_bot_uses(self) -> None:
        self.assertEqual(resolve_channel(CONFIG, "user"), 111)
        self.assertEqual(resolve_channel(CONFIG, "admin"), 222)
        self.assertEqual(resolve_channel(CONFIG, "birthday"), 333)
        self.assertEqual(resolve_channel(CONFIG, "podium"), 444)
        self.assertEqual(resolve_channel(CONFIG, "teamchat"), 555)

    def test_an_unconfigured_channel_says_which_key_is_missing(self) -> None:
        """The two new ids are filled in by hand - the error has to name the key."""
        with self.assertRaises(ValueError) as caught:
            resolve_channel({"PODIUM_CHANNEL_ID": None}, "podium")
        self.assertIn("PODIUM_CHANNEL_ID", str(caught.exception))

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


class AttachmentTests(unittest.TestCase):
    def _image(self, size: int = 32) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"x" * size)
        tmp.close()
        path = pathlib.Path(tmp.name)
        self.addCleanup(path.unlink)
        return path

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_image("/nope/does-not-exist.jpg")

    def test_oversized_file_is_rejected_before_the_request(self) -> None:
        with self.assertRaises(ValueError):
            resolve_image(str(self._image(MAX_ATTACHMENT_BYTES + 1)))

    def test_an_image_never_waits_on_stdin(self) -> None:
        """This is the failure that matters: the skill runs this without a terminal,
        so falling back to stdin for the optional caption hangs the command."""
        args = build_parser().parse_args(
            ["--mode", "dev", "--channel", "podium", "--image", "x.jpg"]
        )
        stdin = mock.Mock()
        stdin.isatty.return_value = False
        stdin.read.side_effect = AssertionError("stdin must not be read for an attachment")
        with mock.patch("sys.stdin", stdin):
            self.assertEqual(read_message(args), "")

    def test_without_an_image_stdin_is_still_the_fallback(self) -> None:
        args = build_parser().parse_args(["--mode", "dev", "--channel", "user"])
        stdin = mock.Mock()
        stdin.isatty.return_value = False
        stdin.read.return_value = "aus der pipe\n"
        with mock.patch("sys.stdin", stdin):
            self.assertEqual(read_message(args), "aus der pipe")


class DuplicateImageTests(unittest.TestCase):
    """The podium shot is usually posted by hand by whoever recorded the match."""

    def _messages(self, payload: list[dict]):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode()
        return mock.patch("scripts.post_discord.urllib.request.urlopen", return_value=response)

    def test_plain_date_counts_from_midnight_utc(self) -> None:
        self.assertEqual(
            parse_since("2026-09-21"),
            datetime.datetime(2026, 9, 21, tzinfo=datetime.timezone.utc),
        )

    def test_a_bad_date_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_since("gestern")

    def test_what_counts_as_a_picture(self) -> None:
        self.assertTrue(_carries_image({"attachments": [{"content_type": "image/jpeg"}]}))
        self.assertTrue(_carries_image({"attachments": [{"filename": "podest.PNG"}]}))
        self.assertTrue(_carries_image({"embeds": [{"type": "image"}]}))
        self.assertFalse(_carries_image({"attachments": [{"filename": "ergebnisse.xlsx"}]}))
        self.assertFalse(_carries_image({"attachments": [], "embeds": [{"type": "link"}]}))

    def test_finds_a_picture_posted_after_the_match(self) -> None:
        payload = [
            {"id": "2", "timestamp": "2026-09-21T18:00:00+00:00",
             "author": {"username": "Turbo"}, "attachments": [{"content_type": "image/png"}]},
        ]
        with self._messages(payload):
            found = find_existing_image("t", 1, parse_since("2026-09-21"))
        self.assertIsNotNone(found)
        self.assertEqual(found["author"], "Turbo")

    def test_an_older_picture_does_not_count(self) -> None:
        """Every match has a picture somewhere further up the channel."""
        payload = [
            {"id": "1", "timestamp": "2026-09-19T18:00:00+00:00",
             "author": {"username": "Turbo"}, "attachments": [{"content_type": "image/png"}]},
        ]
        with self._messages(payload):
            self.assertIsNone(find_existing_image("t", 1, parse_since("2026-09-21")))

    def test_text_after_the_match_does_not_count(self) -> None:
        payload = [
            {"id": "3", "timestamp": "2026-09-21T18:00:00+00:00",
             "author": {"username": "Turbo"}, "attachments": [], "embeds": []},
        ]
        with self._messages(payload):
            self.assertIsNone(find_existing_image("t", 1, parse_since("2026-09-21")))


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

    def test_image_goes_out_as_one_attachment(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"x" * 64)
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink)
        with mock.patch("scripts.post_discord.post_attachment", return_value={"id": "9"}) as up, \
                mock.patch("scripts.post_discord.post") as plain:
            code, out, _ = self._run(
                ["--mode", "dev", "--channel", "podium", "--image", tmp.name, "--text", "Podest"]
            )
        self.assertEqual(code, 0)
        plain.assert_not_called()
        self.assertEqual(up.call_args.args[1], 444)
        self.assertEqual(up.call_args.args[3], "Podest")
        self.assertIn("✅", out)

    def test_image_without_a_caption_is_not_an_empty_message(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(b"x" * 64)
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink)
        with mock.patch("scripts.post_discord.post_attachment", return_value={"id": "9"}) as up:
            code, _, _ = self._run(["--mode", "dev", "--channel", "podium", "--image", tmp.name])
        self.assertEqual(code, 0)
        self.assertEqual(up.call_args.args[3], "")

    def test_image_dry_run_does_not_upload(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"x" * 64)
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink)
        with mock.patch("scripts.post_discord.post_attachment") as up:
            code, out, _ = self._run(
                ["--mode", "dev", "--channel", "teamchat", "--image", tmp.name, "--dry-run"]
            )
        up.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("555", out)

    def _image_file(self) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"x" * 64)
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink)
        return tmp.name

    def test_an_existing_picture_stops_the_post(self) -> None:
        found = {"author": "Turbo", "timestamp": "2026-09-21T18:00:00+00:00", "id": "7"}
        with mock.patch("scripts.post_discord.find_existing_image", return_value=found), \
                mock.patch("scripts.post_discord.post_attachment") as up:
            code, out, _ = self._run([
                "--mode", "prod", "--channel", "podium", "--image", self._image_file(),
                "--skip-if-image-since", "2026-09-21",
            ])
        up.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("Turbo", out)

    def test_no_picture_yet_means_post_it(self) -> None:
        with mock.patch("scripts.post_discord.find_existing_image", return_value=None), \
                mock.patch("scripts.post_discord.post_attachment", return_value={"id": "9"}) as up:
            code, _, _ = self._run([
                "--mode", "prod", "--channel", "podium", "--image", self._image_file(),
                "--skip-if-image-since", "2026-09-21",
            ])
        self.assertEqual(code, 0)
        up.assert_called_once()

    def test_an_unreadable_history_refuses_to_post(self) -> None:
        """Not being allowed to look is not the same as nothing being there - waving
        the post through here would produce exactly the duplicate this guards against."""
        error = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b'{"message":"Missing Access"}'))
        with mock.patch("scripts.post_discord.find_existing_image", side_effect=error), \
                mock.patch("scripts.post_discord.post_attachment") as up:
            code, _, err = self._run([
                "--mode", "prod", "--channel", "podium", "--image", self._image_file(),
                "--skip-if-image-since", "2026-09-21",
            ])
        up.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("403", err)

    def test_mode_is_mandatory(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            build_parser().parse_args(["--channel", "user", "--text", "hi"])


if __name__ == "__main__":
    unittest.main()
