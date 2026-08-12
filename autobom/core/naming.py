"""What to call the workbook.

Kept out of the GUI so the rule is testable without a window, and so the CLI
and the desktop app cannot drift apart on it.
"""

from __future__ import annotations

from pathlib import Path

SUFFIX = "BOM Quantities"
EXTENSION = ".xlsx"


def job_number(bom_filename: str) -> str:
    """The job from a BOM filename: ``8701-01101-I.csv`` -> ``8701``."""
    return Path(bom_filename).stem.strip().split("-")[0]


def default_workbook_name(bom_filenames: list[str]) -> str:
    """``8701 BOM Quantities.xlsx`` when every BOM agrees on one job.

    A run spanning two jobs has no single job number to claim, so the name
    drops it rather than picking one arbitrarily.
    """
    jobs = {job_number(name) for name in bom_filenames if job_number(name)}
    if len(jobs) == 1:
        return f"{jobs.pop()} {SUFFIX}{EXTENSION}"
    return f"{SUFFIX}{EXTENSION}"
