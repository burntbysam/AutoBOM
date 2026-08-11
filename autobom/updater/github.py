"""Check for a newer AutoBOM build.

The source is a small JSON manifest rather than the GitHub API. The API is rate
limited per IP (a shop behind one NAT can exhaust it between them) and its
"latest release" deliberately hides prereleases, so it is the wrong target for
"the current Windows build". CI republishes the manifest and the executable to
one fixed tag instead, and this polls that.

The manifest may live at an https URL or a plain path -- a UNC share such as
``\\\\server\\shared\\AutoBOM\\latest.json`` is usually what a shop wants, since
it needs no GitHub access from the floor. Override with the
``AUTOBOM_UPDATE_URL`` environment variable.

Every failure is soft: a machine with no network must still start the app.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..version import build_id, run_number, version

REPO = "burntbysam/AutoBOM"
# The tag CI republishes on every build. Explicit, because /releases/latest/
# excludes prereleases and would drift to any future tagged version.
RELEASE_TAG = "windows-latest-build"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/{RELEASE_TAG}"
DEFAULT_MANIFEST_URL = (
    f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/latest.json"
)
ENV_VAR = "AUTOBOM_UPDATE_URL"

TIMEOUT_SECONDS = 8
DOWNLOAD_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    current_build_id: str
    latest_version: str
    latest_build_id: str
    url: str
    sha256: str = ""
    size: int = 0
    notes: str = ""
    release_page: str = RELEASE_PAGE

    @property
    def available(self) -> bool:
        """Newer version, or the same version rebuilt by a later CI run."""
        latest, current = parse_version(self.latest_version), parse_version(
            self.current_version
        )
        if latest > current:
            return True
        if latest < current:
            return False
        return run_number(self.latest_build_id) > run_number(self.current_build_id)


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``v1.2.3`` into ``(1, 2, 3)``. Unparseable text sorts lowest."""
    parts: list[int] = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        match = re.match(r"\d+", chunk.strip())
        if match is None:
            break
        parts.append(int(match.group(0)))
    return tuple(parts) if parts else (0,)


def manifest_url() -> str:
    return os.environ.get(ENV_VAR, "").strip() or DEFAULT_MANIFEST_URL


def _read_source(location: str, timeout: int) -> bytes:
    """Read an https URL or a local/UNC path."""
    if urlparse(location).scheme in ("http", "https"):
        request = urllib.request.Request(
            location, headers={"User-Agent": f"AutoBOM/{version()}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    return Path(location).read_bytes()


def check_for_update(url: str | None = None) -> UpdateInfo | None:
    """Return update information, or ``None`` when the check cannot complete."""
    location = url or manifest_url()
    try:
        payload = json.loads(_read_source(location, TIMEOUT_SECONDS).decode("utf-8"))
    except (
        urllib.error.URLError,
        ssl.SSLError,
        TimeoutError,
        ValueError,
        OSError,
    ):
        return None
    if not isinstance(payload, dict):
        return None

    latest_version = str(payload.get("version") or "").strip()
    download_url = str(payload.get("url") or "").strip()
    if not latest_version or not download_url:
        return None

    try:
        size = int(payload.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    return UpdateInfo(
        current_version=version(),
        current_build_id=build_id(),
        latest_version=latest_version,
        latest_build_id=str(payload.get("build_id") or ""),
        url=download_url,
        sha256=str(payload.get("sha256") or "").strip().lower(),
        size=size,
        notes=str(payload.get("notes") or "").strip(),
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_asset(info: UpdateInfo, destination: Path) -> Path:
    """Download the new build and verify it before handing back the path.

    A download that does not match the published checksum is deleted rather
    than left on disk where somebody might run it.
    """
    if urlparse(info.url).scheme not in ("https", "file", ""):
        raise ValueError("refusing to download an update over a non-HTTPS URL")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_read_source(info.url, DOWNLOAD_TIMEOUT_SECONDS))

    if info.sha256:
        actual = sha256_of(destination)
        if actual != info.sha256:
            destination.unlink(missing_ok=True)
            raise ValueError(
                f"checksum mismatch: expected {info.sha256}, got {actual}"
            )
    return destination
