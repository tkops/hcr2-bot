#!/usr/bin/env python3
"""Read the recent messages of one of the bot's Discord channels.

The counterpart to post_discord.py. bot.py only ever reacts to commands and
`on_message` listens in CHANNEL_IDS and ADMIN_CHANNEL_IDS only, so there is no
way to see what was said in a channel - least of all in `birthday`, the leader
chat the bot posts to but takes no commands in. This is that way in: announce
something with post_discord.py, then read the replies here.

Channel names mean exactly what they mean in bot.py and in post_discord.py -
the names, the config keys and the resolver are imported from there rather than
copied, because two tables of channel ids are how the two drift apart.

Usage:
    python3 scripts/read_discord.py --mode prod --channel birthday
    python3 scripts/read_discord.py --mode prod --channel birthday --since 2026-09-13
    python3 scripts/read_discord.py --mode prod --channel admin --limit 200 --json

Output is oldest first, so it reads like the channel does. Timestamps are shown
in local time through hcr2.timestamps.to_local, the same way every other
timestamp in this repo is displayed.

Reading is safe to repeat - unlike a post, nothing here changes anything on
Discord - so --mode is required merely to say which server is meant.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from hcr2.timestamps import LOCAL_ZONE, to_local  # noqa: E402
from scripts.post_discord import API, load_config, resolve_channel  # noqa: E402

# Discord caps one request at 100 messages; more than that means paginating.
PAGE_LIMIT = 100
DEFAULT_LIMIT = 50


def fetch_page(token: str, channel_id: int, limit: int, before: str | None) -> list[dict]:
    """One page, newest first - the order the API returns."""
    query = {"limit": str(limit)}
    if before:
        query["before"] = before
    url = f"{API}/channels/{channel_id}/messages?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (hcr2-bot, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def fetch_messages(
    token: str,
    channel_id: int,
    limit: int,
    since: datetime | None = None,
    *,
    fetch=fetch_page,
) -> tuple[list[dict], bool]:
    """Walk backwards until `limit` messages or the `since` cutoff is reached.

    Returns the messages oldest first plus whether the limit stopped the walk
    while older messages were still in reach. The caller says so out loud: a
    silently truncated channel would drop somebody's reply without a trace,
    and a reply nobody sees is exactly what this script exists to prevent.

    Pagination always runs backwards with `before`, and `since` is a stop
    condition rather than the API's `after` parameter - one way through the
    history is easier to reason about than two.
    """
    collected: list[dict] = []
    before: str | None = None
    hit_limit = False
    while len(collected) < limit:
        want = min(PAGE_LIMIT, limit - len(collected))
        page = fetch(token, channel_id, want, before)
        if not page:
            break
        for message in page:
            stamp = message_time(message)
            if since is not None and stamp is not None and stamp < since:
                return list(reversed(collected)), False
            collected.append(message)
        before = page[-1]["id"]
        if len(page) < want:
            # Short page means the channel is exhausted. Measured against `want`
            # and not against PAGE_LIMIT: the last request asks for the remainder,
            # so a full answer to it is shorter than a page and would otherwise
            # look like the end of the channel.
            break
        if len(collected) >= limit:
            hit_limit = True
    return list(reversed(collected)), hit_limit


def message_time(message: dict) -> datetime | None:
    """The message timestamp as an aware local datetime, None if unparsable."""
    raw = message.get("timestamp")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).astimezone(LOCAL_ZONE)
    except ValueError:
        return None


def parse_since(text: str) -> datetime:
    """'2026-09-13' or '2026-09-13 08:00' in local time."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=LOCAL_ZONE)
        except ValueError:
            continue
    raise ValueError(f"cannot read --since {text!r}, use YYYY-MM-DD[ HH:MM]")


def author_name(message: dict) -> str:
    author = message.get("author") or {}
    return author.get("global_name") or author.get("username") or "?"


def is_bot(message: dict) -> bool:
    return bool((message.get("author") or {}).get("bot"))


def format_message(message: dict) -> str:
    """One message as a block: header line, then the text indented below it.

    Attachments and embeds are named rather than dropped - an empty content
    with a picture under it would otherwise read as an empty message.
    """
    stamp = to_local(str(message.get("timestamp") or ""))
    head = f"[{stamp}] {author_name(message)}"
    referenced = message.get("referenced_message")
    if referenced:
        head += f" (↳ {author_name(referenced)})"
    lines = [head + ":"]

    body = (message.get("content") or "").rstrip()
    if body:
        lines += [f"    {line}" for line in body.split("\n")]
    for attachment in message.get("attachments") or []:
        lines.append(f"    [Anhang: {attachment.get('filename', '?')}]")
    for embed in message.get("embeds") or []:
        title = embed.get("title") or embed.get("description") or "ohne Titel"
        lines.append(f"    [Embed: {str(title)[:80]}]")
    if len(lines) == 1:
        lines.append("    [leer]")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mode", required=True, choices=["dev", "prod"])
    parser.add_argument(
        "--channel",
        required=True,
        help="user | admin | birthday | <channel id>",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"how many messages at most (default {DEFAULT_LIMIT})",
    )
    parser.add_argument("--since", help="only messages from this local date/time on")
    parser.add_argument("--skip-bots", action="store_true", help="hide the bot's own posts")
    parser.add_argument("--json", action="store_true", help="print the raw messages as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        since = parse_since(args.since) if args.since else None
        config = load_config(args.mode)
        channel_id = resolve_channel(config, args.channel)
    except (OSError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if args.limit < 1:
        print("❌ --limit must be at least 1", file=sys.stderr)
        return 1

    try:
        messages, hit_limit = fetch_messages(
            config["TOKEN"], channel_id, args.limit, since
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        print(f"❌ HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        # Same reasoning as integrations/nextcloud.py: the type, not the message,
        # because a URL error carries the request URL - here with the channel id.
        print(f"❌ {type(exc).__name__}", file=sys.stderr)
        return 1

    if args.skip_bots:
        messages = [m for m in messages if not is_bot(m)]

    if args.json:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return 0

    span = ""
    if messages:
        span = f", {to_local(str(messages[0]['timestamp']))} .. " \
               f"{to_local(str(messages[-1]['timestamp']))}"
    print(f"--- {args.mode}/{args.channel} ({channel_id}), "
          f"{len(messages)} messages{span} ---")
    for message in messages:
        print(format_message(message))
    if not messages:
        print("(nothing to show)")
    if hit_limit:
        print(f"⚠️  stopped at --limit {args.limit} - there may be older messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
