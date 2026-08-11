"""Shared helpers.

Real customer BOMs are not committed (see .gitignore); tests that need them
live in test_sample_data.py and skip when tests/data is empty. Everything else
builds its own CSVs on the fly so the suite runs anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent / "data"


def write_csv(directory: Path, name: str, rows: list[str]) -> Path:
    """Write a pipe-delimited CSV with the ``sep=|`` directive these exports carry."""
    path = directory / name
    path.write_text("sep=|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def sample_data_dir() -> Path:
    boms = [
        path
        for path in DATA_DIR.glob("*.csv")
        if not path.stem.upper().startswith("IL")
    ]
    if not boms:
        pytest.skip("no local sample data in tests/data (not committed)")
    return DATA_DIR
