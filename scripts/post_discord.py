#!/usr/bin/env python3
"""Post a message to one of the bot's Discord channels.

bot.py only writes to Discord as a reaction to a command. This is the manual way
in - a feature announcement, a note to the leaders, a test post. It reads the
same token and channel ids as the bot (secrets_config.CONFIG), so the channel
names here mean exactly what they mean in bot.py:

    user      CHANNEL_IDS[0]        team channel, public commands
    admin     ADMIN_CHANNEL_IDS[0]  leader commands ('.B', '.stats broom', ...)
    birthday  BIRTHDAY_CHANNEL_ID   the bot posts birthdays here, it takes no
                                    commands in this channel

Usage:
    python3 scripts/post_discord.py --mode prod --channel admin --file note.md
    python3 scripts/post_discord.py --mode prod --channel birthday --text "Hi"
    echo "Kurze Info" | python3 scripts/post_discord.py --mode dev --channel user

--mode is required on purpose: dev and prod are different Discord servers, and a
post cannot be taken back by re-running the command. --dry-run shows what would
be sent, including how it would be split.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"

# Discord drops anything over 2000 characters - same limit bot.py guards with
# MAX_DISCORD_MSG_LEN, kept a little lower there for the code fences it adds.
MAX_LEN = 2000

# Channel name -> (config key, whether the key holds a list)
CHANNELS = {
    "user": ("CHANNEL_IDS", True),
    "admin": ("ADMIN_CHANNEL_IDS", True),
    "birthday": ("BIRTHDAY_CHANNEL_ID", False),
}


def load_config(mode: str) -> dict:
    """Import secrets_config lazily so the module stays importable in tests."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from secrets_config import CONFIG  # noqa: PLC0415

    if mode not in CONFIG:
        raise ValueError(f"unknown mode {mode!r}, known: {', '.join(sorted(CONFIG))}")
    return CONFIG[mode]


def resolve_channel(config: dict, channel: str) -> int:
    """Turn 'admin' or a raw id into a channel id."""
    if channel.isdigit():
        return int(channel)
    if channel not in CHANNELS:
        known = ", ".join(sorted(CHANNELS))
        raise ValueError(f"unknown channel {channel!r}, use one of: {known} - or an id")
    key, is_list = CHANNELS[channel]
    value = config.get(key)
    if is_list:
        if not value:
            raise ValueError(f"{key} is empty in this mode")
        return int(value[0])
    if not value:
        raise ValueError(f"{key} is not configured in this mode")
    return int(value)


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on line boundaries, hard-splitting only a single overlong line."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def post(token: str, channel_id: int, content: str) -> dict:
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (hcr2-bot, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def read_message(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    if args.text:
        return args.text
    if sys.stdin.isatty():
        raise ValueError("no message given - use --file, --text or pipe it in")
    return sys.stdin.read().rstrip("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mode", required=True, choices=["dev", "prod"])
    parser.add_argument(
        "--channel",
        required=True,
        help="user | admin | birthday | <channel id>",
    )
    parser.add_argument("--file", help="read the message from this file")
    parser.add_argument("--text", help="the message itself")
    parser.add_argument(
        "--split",
        action="store_true",
        help=f"send as several messages if longer than {MAX_LEN} characters",
    )
    parser.add_argument("--dry-run", action="store_true", help="show, do not send")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        content = read_message(args)
        config = load_config(args.mode)
        channel_id = resolve_channel(config, args.channel)
    except (OSError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if not content.strip():
        print("❌ the message is empty", file=sys.stderr)
        return 1

    parts = split_message(content) if args.split else [content]
    if not args.split and len(content) > MAX_LEN:
        print(
            f"❌ {len(content)} characters, Discord allows {MAX_LEN} - use --split",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        for n, part in enumerate(parts, 1):
            print(f"--- {args.mode}/{args.channel} ({channel_id}), "
                  f"part {n}/{len(parts)}, {len(part)} characters ---")
            print(part)
        return 0

    for n, part in enumerate(parts, 1):
        try:
            body = post(config["TOKEN"], channel_id, part)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            print(f"❌ part {n}/{len(parts)}: HTTP {exc.code}: {detail}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"❌ part {n}/{len(parts)}: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"✅ part {n}/{len(parts)} posted, message id {body['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
