"""Check GitHub Releases for a newer AutoBOM build.

The check is deliberately dependency-free (urllib only) and always fails soft:
a shop machine with no internet must still start the app.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO = "burntbysam/AutoBOM"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
TIMEOUT_SECONDS = 8

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))*")


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    download_url: str | None
    notes: str = ""

    @property
    def available(self) -> bool:
        return parse_version(self.latest_version) > parse_version(self.current_version)


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``v1.2.3`` into ``(1, 2, 3)`` for ordering.

    Unparseable text sorts lowest so a malformed tag never triggers a bogus
    "update available" prompt.
    """
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        match = re.match(r"\d+", chunk.strip())
        if match is None:
            break
        parts.append(int(match.group(0)))
    return tuple(parts) if parts else (0,)


def _asset_url(payload: dict) -> str | None:
    """Prefer a Windows installer/executable asset, else the first asset."""
    assets = payload.get("assets") or []
    for suffix in (".exe", ".msi", ".zip"):
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(suffix) and asset.get("browser_download_url"):
                return asset["browser_download_url"]
    for asset in assets:
        if asset.get("browser_download_url"):
            return asset["browser_download_url"]
    return None


def check_for_update(current_version: str, url: str = API_URL) -> UpdateInfo | None:
    """Return update information, or ``None`` when the check cannot complete."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"AutoBOM/{current_version}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, ValueError, OSError):
        return None

    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not tag:
        return None

    return UpdateInfo(
        current_version=current_version,
        latest_version=tag,
        release_url=str(payload.get("html_url") or RELEASES_PAGE),
        download_url=_asset_url(payload),
        notes=str(payload.get("body") or "").strip(),
    )


def download_asset(url: str, destination: Path) -> Path:
    """Download a release asset to ``destination``.

    The app does not replace its own executable in place -- it downloads
    alongside and tells the user where the new build is, which keeps a failed
    update from leaving the shop without a working tool.
    """
    if urlparse(url).scheme != "https":
        raise ValueError("refusing to download an update over a non-HTTPS URL")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AutoBOM"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination
