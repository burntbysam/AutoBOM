from __future__ import annotations

import json
import urllib.error

import pytest

from autobom.updater import github
from autobom.updater.github import UpdateInfo, check_for_update, parse_version


class TestParseVersion:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1.0.0", (1, 0, 0)),
            ("v1.2.3", (1, 2, 3)),
            ("V2.0", (2, 0)),
            (" 1.10.0 ", (1, 10, 0)),
            ("1.0.0-beta", (1, 0, 0)),
        ],
    )
    def test_parsing(self, text, expected):
        assert parse_version(text) == expected

    def test_ordering_is_numeric_not_lexicographic(self):
        assert parse_version("1.10.0") > parse_version("1.9.0")

    def test_garbage_sorts_lowest(self):
        assert parse_version("nightly") == (0,)


class TestUpdateInfo:
    def test_newer_is_available(self):
        info = UpdateInfo("1.0.0", "v1.1.0", "url", None)
        assert info.available is True

    def test_same_is_not_available(self):
        assert UpdateInfo("1.0.0", "v1.0.0", "url", None).available is False

    def test_older_is_not_available(self):
        assert UpdateInfo("1.2.0", "v1.1.0", "url", None).available is False


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestCheckForUpdate:
    def test_reads_tag_and_prefers_exe_asset(self, monkeypatch):
        payload = {
            "tag_name": "v1.4.0",
            "html_url": "https://example.invalid/release",
            "body": "notes",
            "assets": [
                {"name": "source.zip", "browser_download_url": "https://x/source.zip"},
                {"name": "AutoBOM.exe", "browser_download_url": "https://x/AutoBOM.exe"},
            ],
        }
        monkeypatch.setattr(
            github.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
        )
        info = check_for_update("1.0.0")
        assert info.latest_version == "v1.4.0"
        assert info.download_url == "https://x/AutoBOM.exe"
        assert info.available is True

    def test_network_failure_returns_none(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(github.urllib.request, "urlopen", boom)
        assert check_for_update("1.0.0") is None

    def test_missing_tag_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            github.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({})
        )
        assert check_for_update("1.0.0") is None


class TestDownloadAsset:
    def test_rejects_non_https(self, tmp_path):
        with pytest.raises(ValueError):
            github.download_asset("http://example.invalid/a.exe", tmp_path / "a.exe")
