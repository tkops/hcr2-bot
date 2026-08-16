from __future__ import annotations

import sys
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote
from xml.etree import ElementTree

import requests

from secrets_config import NEXTCLOUD_AUTH


NEXTCLOUD_BASE = Path("Power-Ladys-Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"

# One subfolder per source of truth, all relative to NEXTCLOUD_BASE. Keep every remote
# path in the codebase derived from these - the layout is shared with the team, and a
# hardcoded second copy is how the two drift apart.
TEAM_EVENT_DIR = Path("Team-Event")   # S<season>/ with the match videos and match sheets
LADYS_DIR = Path("Ladys")             # team screen recordings and Ladys.xlsx
DONATIONS_DIR = Path("Donations")     # Donations.xlsx
CHEST_DIR = Path("Wochen-Truhe")      # weekly chest, feature still to come


def season_subpath(season: int) -> Path:
    return TEAM_EVENT_DIR / f"S{season}"


def remote_path(*parts) -> str:
    return NEXTCLOUD_BASE.joinpath(*parts).as_posix()

DAV_NS = "{DAV:}"

PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:getlastmodified/><d:getcontentlength/><d:resourcetype/>"
    "</d:prop></d:propfind>"
)


@dataclass(frozen=True)
class RemoteEntry:
    """One entry of a WebDAV collection, path relative to the DAV files root."""

    name: str
    path: str
    size: int
    last_modified: Optional[datetime]
    is_dir: bool


def _report(what: str, error: Exception | None) -> None:
    """Send the reason to stderr, where journalctl keeps it.

    Only the exception type is included: request exceptions carry the full URL,
    which contains the Nextcloud account name, and this text can end up in
    Discord via bot.py's stderr passthrough.
    """
    reason = f": {type(error).__name__}" if error is not None else ""
    print(f"nextcloud: {what}{reason}", file=sys.stderr)


def remote_url(remote_path) -> str:
    user, _ = NEXTCLOUD_AUTH
    return NEXTCLOUD_URL.format(user=user, path=str(remote_path).lstrip("/"))


def upload_file(local_path, remote_path, *, overwrite: bool = False) -> tuple[Optional[str], bool]:
    """
    Upload to Nextcloud.
    - overwrite=False: create only, do not overwrite.
    - overwrite=True: overwrite an existing file.
    Returns (url, created), where created is True only for a new file.
    """
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).lstrip("/")
    url = remote_url(remote_path)

    try:
        head = requests.head(url, auth=(user, password))
        exists = head.status_code == 200
    except requests.RequestException as e:
        _report(f"HEAD failed for {remote_path}", e)
        exists = False

    if exists and not overwrite:
        return url, False

    _ensure_remote_dirs(remote_path)

    with open(local_path, "rb") as f:
        res = requests.put(url, auth=(user, password), data=f)

    if res.status_code in (200, 201, 204):
        return url, not exists
    return None, False


def delete_file(remote_path) -> bool:
    user, password = NEXTCLOUD_AUTH
    try:
        r = requests.delete(remote_url(remote_path), auth=(user, password))
    except requests.RequestException as e:
        _report(f"DELETE failed for {remote_path}", e)
        return False
    return r.status_code in (200, 204)


def download_file(remote_path, local_path: Path) -> Optional[Path]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    user, password = NEXTCLOUD_AUTH
    try:
        response = requests.get(
            remote_url(remote_path),
            auth=(user, password),
            headers={"Cache-Control": "no-cache"},
        )
    except requests.RequestException as e:
        _report(f"GET failed for {remote_path}", e)
        return None

    if response.status_code != 200:
        _report(f"GET returned HTTP {response.status_code} for {remote_path}", None)
        return None

    local_path.write_bytes(response.content)
    return local_path if local_path.exists() and local_path.stat().st_size > 0 else None


def list_directory(remote_path) -> list[RemoteEntry]:
    """List one remote collection (Depth 1). The collection itself is not returned."""
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).strip("/")
    try:
        response = requests.request(
            "PROPFIND",
            remote_url(remote_path),
            auth=(user, password),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data=PROPFIND_BODY.encode("utf-8"),
        )
    except requests.RequestException as e:
        _report(f"PROPFIND failed for {remote_path}", e)
        return []

    if response.status_code != 207:
        _report(f"PROPFIND returned HTTP {response.status_code} for {remote_path}", None)
        return []

    try:
        return _parse_propfind(response.content, base=remote_path)
    except ElementTree.ParseError as e:
        _report(f"PROPFIND returned unparsable XML for {remote_path}", e)
        return []


def _dav_root_prefix() -> str:
    user, _ = NEXTCLOUD_AUTH
    url = NEXTCLOUD_URL.format(user=user, path="")
    return url.split("://", 1)[-1].split("/", 1)[-1]


def _parse_propfind(payload: bytes, *, base: str) -> list[RemoteEntry]:
    root = ElementTree.fromstring(payload)
    prefix = _dav_root_prefix().strip("/")
    entries: list[RemoteEntry] = []

    for response in root.findall(f"{DAV_NS}response"):
        path = _href_to_path(response.findtext(f"{DAV_NS}href") or "")
        if prefix and path.startswith(prefix):
            path = path[len(prefix):].strip("/")
        if not path or path == base:
            continue

        propstat = response.find(f"{DAV_NS}propstat")
        prop = propstat.find(f"{DAV_NS}prop") if propstat is not None else None
        is_dir = prop is not None and prop.find(f"{DAV_NS}resourcetype/{DAV_NS}collection") is not None

        entries.append(
            RemoteEntry(
                name=path.rsplit("/", 1)[-1],
                path=path,
                size=_read_size(prop),
                last_modified=_read_last_modified(prop),
                is_dir=is_dir,
            )
        )

    return entries


def _href_to_path(href: str) -> str:
    """href may be a bare path or an absolute URL - both reduce to the DAV path."""
    raw = unquote(href)
    if "://" in raw:
        rest = raw.split("://", 1)[1]
        raw = rest.split("/", 1)[1] if "/" in rest else ""
    return raw.strip("/")


def _read_size(prop) -> int:
    raw = prop.findtext(f"{DAV_NS}getcontentlength") if prop is not None else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _read_last_modified(prop) -> Optional[datetime]:
    raw = prop.findtext(f"{DAV_NS}getlastmodified") if prop is not None else None
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def match_sheet_remote_path(season: int, filename: str) -> Path:
    return NEXTCLOUD_BASE / season_subpath(season) / filename


def _ensure_remote_dirs(remote_path: str) -> None:
    user, password = NEXTCLOUD_AUTH
    current_path = ""
    for part in remote_path.split("/")[:-1]:
        current_path += f"/{part}"
        requests.request("MKCOL", remote_url(current_path.lstrip("/")), auth=(user, password))

