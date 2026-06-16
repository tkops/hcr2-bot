from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

from secrets_config import NEXTCLOUD_AUTH


NEXTCLOUD_BASE = Path("Power-Ladys-Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"


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
    except Exception:
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
        return r.status_code in (200, 204)
    except Exception:
        return False


def download_file(remote_path, local_path: Path) -> Optional[Path]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    user, password = NEXTCLOUD_AUTH
    try:
        response = requests.get(
            remote_url(remote_path),
            auth=(user, password),
            headers={"Cache-Control": "no-cache"},
        )
    except Exception:
        return None

    if response.status_code != 200:
        return None

    local_path.write_bytes(response.content)
    return local_path if local_path.exists() and local_path.stat().st_size > 0 else None


def match_sheet_remote_path(season: int, filename: str) -> Path:
    return NEXTCLOUD_BASE / f"S{season}" / filename


def _ensure_remote_dirs(remote_path: str) -> None:
    user, password = NEXTCLOUD_AUTH
    current_path = ""
    for part in remote_path.split("/")[:-1]:
        current_path += f"/{part}"
        requests.request("MKCOL", remote_url(current_path.lstrip("/")), auth=(user, password))

