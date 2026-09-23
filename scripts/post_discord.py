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
    podium    PODIUM_CHANNEL_ID     the winners' podium picture after a match
    teamchat  TEAMCHAT_CHANNEL_ID   the internal team chat, where the match recap goes

The last two are written to by the match-video skill, not by bot.py - like
`birthday` they take no commands, so a reply typed under such a post does nothing.

Usage:
    python3 scripts/post_discord.py --mode prod --channel admin --file note.md
    python3 scripts/post_discord.py --mode prod --channel birthday --text "Hi"
    python3 scripts/post_discord.py --mode prod --channel podium --image podium.jpg
    echo "Kurze Info" | python3 scripts/post_discord.py --mode dev --channel user

--mode is required on purpose: dev and prod are different Discord servers, and a
post cannot be taken back by re-running the command. --dry-run shows what would
be sent, including how it would be split.

--image attaches a file (with an optional caption from --text/--file/stdin). It
goes out as one multipart request, so --split does not apply to it.

--skip-if-image-since <date> looks at the channel first and posts nothing when
somebody already put a picture there on or after that date. The podium shot is
usually posted by hand by whoever recorded the match; a second one is noise. It
needs "Read Message History" in that channel - and if the check cannot run, the
post is refused rather than sent, because "could not look" is not "nothing there".
"""
from __future__ import annotations

import argparse
import datetime
import json
import mimetypes
import pathlib
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://discord.com/api/v10"

# Discord drops anything over 2000 characters - same limit bot.py guards with
# MAX_DISCORD_MSG_LEN, kept a little lower there for the code fences it adds.
MAX_LEN = 2000

# How far back the duplicate check looks. A results channel sees a handful of posts
# between two matches, so one page is plenty.
HISTORY_LIMIT = 50
# Extensions that count as a picture when Discord sends no content type.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic")

# Discord refuses an attachment past this size for a bot in an unboosted server.
# Checked here so a 30 MB video fails with a sentence instead of an HTTP 413.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# Channel name -> (config key, whether the key holds a list)
CHANNELS = {
    "user": ("CHANNEL_IDS", True),
    "admin": ("ADMIN_CHANNEL_IDS", True),
    "birthday": ("BIRTHDAY_CHANNEL_ID", False),
    "podium": ("PODIUM_CHANNEL_ID", False),
    "teamchat": ("TEAMCHAT_CHANNEL_ID", False),
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


def post_attachment(token: str, channel_id: int, path: pathlib.Path, content: str) -> dict:
    """Upload one file, optionally with a caption, as multipart/form-data."""
    payload = json.dumps({"content": content} if content else {}).encode("utf-8")
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    boundary = f"----hcr2-{secrets.token_hex(16)}"
    sep = f"--{boundary}\r\n".encode()
    body = b"".join([
        sep,
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        payload,
        b"\r\n",
        sep,
        f'Content-Disposition: form-data; name="files[0]"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DiscordBot (hcr2-bot, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def parse_since(raw: str) -> datetime.datetime:
    """A plain date means from midnight UTC that day."""
    try:
        value = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"--skip-if-image-since: {raw!r} is not a date (YYYY-MM-DD)") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value


def _carries_image(message: dict) -> bool:
    for attachment in message.get("attachments") or []:
        content_type = (attachment.get("content_type") or "").lower()
        name = (attachment.get("filename") or "").lower()
        if content_type.startswith("image/") or name.endswith(IMAGE_SUFFIXES):
            return True
    return any((embed.get("type") or "") == "image" for embed in message.get("embeds") or [])


def find_existing_image(token: str, channel_id: int, since: datetime.datetime) -> dict | None:
    """The newest message with a picture posted on or after `since`, or None.

    Raises on an API error on purpose: not being allowed to read the history must not
    look like an empty channel, or the guard would wave through exactly the duplicate
    it exists to prevent.
    """
    query = urllib.parse.urlencode({"limit": HISTORY_LIMIT})
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages?{query}",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (hcr2-bot, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        messages = json.load(resp)
    for message in messages:
        stamp = message.get("timestamp") or ""
        try:
            posted = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if posted >= since and _carries_image(message):
            return {
                "author": (message.get("author") or {}).get("username", "?"),
                "timestamp": stamp,
                "id": message.get("id", "?"),
            }
    return None


def resolve_image(raw: str) -> pathlib.Path:
    path = pathlib.Path(raw)
    if not path.is_file():
        raise ValueError(f"no such file: {raw}")
    size = path.stat().st_size
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"{raw} is {size // 1024} KB, Discord takes at most "
            f"{MAX_ATTACHMENT_BYTES // 1024} KB from a bot"
        )
    return path


def read_message(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    if args.text:
        return args.text
    # An attachment is a message on its own, so a caption has to be asked for
    # explicitly. Falling back to stdin here would hang the moment this runs
    # without a terminal - which is exactly how the match-video skill calls it.
    if args.image:
        return ""
    if sys.stdin.isatty():
        raise ValueError("no message given - use --file, --text or pipe it in")
    return sys.stdin.read().rstrip("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mode", required=True, choices=["dev", "prod"])
    parser.add_argument(
        "--channel",
        required=True,
        help="user | admin | birthday | podium | teamchat | <channel id>",
    )
    parser.add_argument("--image", help="attach this file (picture, screenshot)")
    parser.add_argument(
        "--skip-if-image-since",
        metavar="DATE",
        help="post nothing if the channel already has a picture from this date on",
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


def post_image(
    args: argparse.Namespace,
    config: dict,
    channel_id: int,
    image: pathlib.Path,
    content: str,
) -> int:
    """One request, one message - an attachment is never split."""
    if len(content) > MAX_LEN:
        print(
            f"❌ the caption is {len(content)} characters, Discord allows {MAX_LEN}",
            file=sys.stderr,
        )
        return 1
    if args.dry_run:
        size = image.stat().st_size
        print(f"--- {args.mode}/{args.channel} ({channel_id}), "
              f"attachment {image.name}, {size // 1024} KB ---")
        if content:
            print(content)
        return 0
    try:
        body = post_attachment(config["TOKEN"], channel_id, image, content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        print(f"❌ HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"❌ {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"✅ {image.name} posted, message id {body['id']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        content = read_message(args)
        config = load_config(args.mode)
        channel_id = resolve_channel(config, args.channel)
        image = resolve_image(args.image) if args.image else None
        since = parse_since(args.skip_if_image_since) if args.skip_if_image_since else None
    except (OSError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if since is not None:
        try:
            existing = find_existing_image(config["TOKEN"], channel_id, since)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            print(
                f"❌ cannot read the channel history (HTTP {exc.code}: {detail}) - "
                "not posting, since that is not proof the picture is missing",
                file=sys.stderr,
            )
            return 1
        except urllib.error.URLError as exc:
            print(f"❌ cannot read the channel history ({type(exc).__name__}) - not posting",
                  file=sys.stderr)
            return 1
        if existing is not None:
            print(
                f"⏭️  {existing['author']} already posted a picture on "
                f"{existing['timestamp'][:16]} (message {existing['id']}) - nothing sent"
            )
            return 0

    if not content.strip() and image is None:
        print("❌ the message is empty", file=sys.stderr)
        return 1

    if image is not None:
        return post_image(args, config, channel_id, image, content)

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
