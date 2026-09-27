from __future__ import annotations

import contextlib
import io
import unittest
from datetime import datetime, timezone
from unittest import mock

from hcr2.timestamps import LOCAL_ZONE
from scripts.read_discord import (
    DEFAULT_LIMIT,
    PAGE_LIMIT,
    build_parser,
    fetch_messages,
    format_message,
    main,
    parse_since,
)


CONFIG = {
    "TOKEN": "token",
    "CHANNEL_IDS": [111],
    "ADMIN_CHANNEL_IDS": [222],
    "BIRTHDAY_CHANNEL_ID": 333,
}


def message(mid: int, *, minute: int = 0, author: str = "lady", **extra) -> dict:
    """A message as the API returns it - newest first means highest id first."""
    body = {
        "id": str(mid),
        "timestamp": f"2026-09-13T10:{minute:02d}:00.000000+00:00",
        "author": {"username": author},
        "content": f"Nachricht {mid}",
    }
    body.update(extra)
    return body


def pages(*batches: list[dict]):
    """A fake fetch_page that hands out the given batches in order."""
    calls: list[dict] = []
    remaining = list(batches)

    def fetch(token, channel_id, limit, before):
        calls.append({"limit": limit, "before": before})
        return remaining.pop(0) if remaining else []

    fetch.calls = calls
    return fetch


class FetchMessagesTests(unittest.TestCase):
    def test_returns_oldest_first(self) -> None:
        fetch = pages([message(3), message(2), message(1)])
        messages, _ = fetch_messages("t", 1, 10, fetch=fetch)
        self.assertEqual([m["id"] for m in messages], ["1", "2", "3"])

    def test_walks_back_with_before(self) -> None:
        first = [message(i) for i in range(200, 100, -1)]
        second = [message(i) for i in range(100, 50, -1)]
        fetch = pages(first, second)
        messages, _ = fetch_messages("t", 1, 150, fetch=fetch)
        self.assertEqual(len(messages), 150)
        self.assertEqual(fetch.calls[0], {"limit": PAGE_LIMIT, "before": None})
        self.assertEqual(fetch.calls[1], {"limit": 50, "before": "101"})

    def test_short_page_ends_the_walk_without_a_limit_warning(self) -> None:
        # The channel simply has fewer messages than asked for.
        fetch = pages([message(2), message(1)])
        messages, hit_limit = fetch_messages("t", 1, 50, fetch=fetch)
        self.assertEqual(len(messages), 2)
        self.assertFalse(hit_limit)

    def test_a_full_answer_to_the_last_request_is_reported_as_truncated(self) -> None:
        # Regression: a page shorter than PAGE_LIMIT but as long as requested is
        # not the end of the channel - measuring against PAGE_LIMIT hid older
        # messages and reported nothing.
        fetch = pages([message(i) for i in range(50, 0, -1)])
        messages, hit_limit = fetch_messages("t", 1, 50, fetch=fetch)
        self.assertEqual(len(messages), 50)
        self.assertTrue(hit_limit)

    def test_since_stops_the_walk(self) -> None:
        fetch = pages([message(3, minute=30), message(2, minute=10), message(1, minute=0)])
        cutoff = datetime(2026, 9, 13, 10, 5, tzinfo=timezone.utc).astimezone(LOCAL_ZONE)
        messages, hit_limit = fetch_messages("t", 1, 50, cutoff, fetch=fetch)
        self.assertEqual([m["id"] for m in messages], ["2", "3"])
        self.assertFalse(hit_limit)


class ParseSinceTests(unittest.TestCase):
    def test_date_and_datetime_are_local(self) -> None:
        self.assertEqual(
            parse_since("2026-09-13"),
            datetime(2026, 9, 13, tzinfo=LOCAL_ZONE),
        )
        self.assertEqual(
            parse_since("2026-09-13 08:30"),
            datetime(2026, 9, 13, 8, 30, tzinfo=LOCAL_ZONE),
        )

    def test_nonsense_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_since("gestern")


class FormatMessageTests(unittest.TestCase):
    def test_timestamp_is_shown_in_local_time(self) -> None:
        # 10:00 UTC is 12:00 in Europe/Berlin - the same convention the rest of
        # the repo uses for stored timestamps.
        self.assertIn("2026-09-13 12:00", format_message(message(1)))

    def test_reply_names_the_original_author(self) -> None:
        text = format_message(message(2, referenced_message=message(1, author="tina")))
        self.assertIn("↳ tina", text)

    def test_attachment_is_named_instead_of_dropped(self) -> None:
        text = format_message(
            message(1, content="", attachments=[{"filename": "bild.png"}])
        )
        self.assertIn("[Anhang: bild.png]", text)
        self.assertNotIn("[leer]", text)

    def test_an_empty_message_says_so(self) -> None:
        self.assertIn("[leer]", format_message(message(1, content="")))

    def test_body_lines_are_indented_under_the_header(self) -> None:
        lines = format_message(message(1, content="eins\nzwei")).split("\n")
        self.assertTrue(lines[0].endswith(":"))
        self.assertEqual(lines[1:], ["    eins", "    zwei"])


class MainTests(unittest.TestCase):
    def _run(self, argv: list[str], messages: list[dict], hit_limit: bool = False):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("scripts.read_discord.load_config", return_value=CONFIG), \
                mock.patch(
                    "scripts.read_discord.fetch_messages",
                    return_value=(messages, hit_limit),
                ) as fetched, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue(), fetched

    def test_reads_the_channel_the_bot_means(self) -> None:
        code, out, _, fetched = self._run(
            ["--mode", "prod", "--channel", "birthday"], [message(1)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(fetched.call_args.args[1], 333)
        self.assertEqual(fetched.call_args.args[2], DEFAULT_LIMIT)
        self.assertIn("Nachricht 1", out)

    def test_skip_bots_hides_the_bots_own_posts(self) -> None:
        messages = [
            message(1, author="lady"),
            message(2, author="hcr2"),
        ]
        messages[1]["author"]["bot"] = True
        _, out, _, _ = self._run(
            ["--mode", "prod", "--channel", "birthday", "--skip-bots"], messages
        )
        self.assertIn("Nachricht 1", out)
        self.assertNotIn("Nachricht 2", out)

    def test_truncation_is_reported(self) -> None:
        _, out, _, _ = self._run(
            ["--mode", "prod", "--channel", "admin", "--limit", "1"],
            [message(1)],
            hit_limit=True,
        )
        self.assertIn("--limit 1", out)

    def test_empty_channel_says_so(self) -> None:
        code, out, _, _ = self._run(["--mode", "prod", "--channel", "user"], [])
        self.assertEqual(code, 0)
        self.assertIn("nothing to show", out)

    def test_json_output_is_machine_readable(self) -> None:
        import json as _json

        _, out, _, _ = self._run(
            ["--mode", "prod", "--channel", "user", "--json"], [message(1)]
        )
        self.assertEqual(_json.loads(out)[0]["id"], "1")

    def test_bad_since_is_rejected_before_any_request(self) -> None:
        code, _, err, fetched = self._run(
            ["--mode", "prod", "--channel", "user", "--since", "gestern"], []
        )
        self.assertEqual(code, 1)
        self.assertIn("❌", err)
        fetched.assert_not_called()

    def test_mode_is_mandatory(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            build_parser().parse_args(["--channel", "user"])


if __name__ == "__main__":
    unittest.main()
