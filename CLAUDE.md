# AutoBOM — working notes

## Versioning: bump `VERSION` on every push

`VERSION` at the repo root is the single source of truth. Bump it **in the same
commit** as the change it describes, before pushing.

| Change | Bump | Example |
| --- | --- | --- |
| Any push at all — bug fix, docs, refactor, test | patch `x.x.+1` | 1.0.0 → 1.0.1 |
| A significant feature added, removed, or overhauled | minor `x.+1.x` | 1.0.1 → 1.1.0 |
| The entire app overhauled | major `+1.x.x` | 1.1.0 → 2.0.0 |

A major bump happens only when the maintainer instructs it, or when Claude asks
and gets agreement first. Never take a major bump unilaterally.

The bumps are cumulative in the ordinary way: a minor bump resets patch to 0, a
major bump resets both. Use the helper so this is not done by hand:

```
python scripts/bump_version.py patch    # or minor / major
```

Only one bump per push, reflecting the largest category of change in it. A push
that both fixes a bug and adds a significant feature is a minor bump, not both.

Note that `VERSION` is in the CI path filter, so bumping it always produces a
new published build. That is intended.

## What this app is

A BOM processor for CNC sheet metal. Bus section BOMs plus an indented list in,
a 5-sheet Excel workbook out. `README.md` has the full rules; the ones that
were hard to learn and are easy to get wrong:

- **Individual parts.** 300-series (`8701-300-I`) and JB (`JB-2724-06`) items on
  the IL have no BOM by design. They are counted at the IL quantity and assigned
  standard stock: 1/8", 60x120, T. A bus section is `8701-01101-I` — five digits
  *with* a leading zero — and never matches those patterns, so a forgotten bus
  section BOM is still caught as FLAG 2 instead of silently becoming one sheet.
- **`COVER JOINER CHANNEL` is never counted**, in a BOM or an IL. See
  `EXCLUDED_DESCRIPTIONS` in `autobom/core/parser.py`.
- **Summary totals group by thickness, not by sheet**, so an F part counts
  toward its own thickness and the category rows add up to the grand total.
  This is why the All sheet's `1/8"` row can exceed the `1-8` sheet's total.
- The workbook is `<job> BOM Quantities.xlsx` — spaces, no underscores, no
  `OUTPUT` prefix. The rule lives in `autobom/core/naming.py`.

## Things that have bitten before

- **`tests/data/` is customer data and is gitignored.** The job 8701 integration
  tests skip on CI. `--selftest` (synthetic, committed) is what actually guards
  end-to-end behaviour on the runner. Do not commit real BOMs.
- **`AutoBOM.exe` is a GUI-subsystem binary.** PowerShell does not wait for it,
  so `$LASTEXITCODE` is meaningless. CI must use `Start-Process -Wait -PassThru`
  and read `.ExitCode`, or the smoke test passes on a broken build.
- **PySide6 worker objects get garbage collected.** A worker moved to a QThread
  with no retained reference dies silently and the thread never finishes. Prefer
  subclassing QThread and overriding `run()`. This broke the update check
  completely; `tests/test_gui_update.py` guards it.
- **Updates install in place and must fail safe.** A downloaded build is
  swapped in only after its SHA256 matches *and* it passes its own
  `--selftest`; a checksum cannot tell a working build from a broken one. The
  swap is rename-aside-then-replace, undone on failure. See
  `autobom/updater/installer.py` and the tests around it — that code can leave
  a machine with no working application if it is got wrong.
- **A frozen app must scrub PyInstaller's env vars before spawning another
  one.** `_PYI_APPLICATION_HOME_DIR` and friends tell a onefile bootloader
  "you are a second stage, use this directory". A child inheriting them runs
  the *parent's* unpacked code and dies on a missing `base_library.zip` when
  the parent exits and deletes it. It also made the update self-test execute
  the running build instead of the downloaded one. Use
  `installer.child_environment()` for every subprocess.
- **Do not re-export a name from `autobom/__init__.py` that matches a
  submodule.** `from .version import version` made `from autobom import
  version` hand back the function, so `version.build_info` raised. Cost two
  debugging detours before the shadowing was removed.
- **`urlparse` reads a Windows drive letter as a URL scheme.** `C:\x` parses as
  scheme `c`. Any scheme shorter than two characters is a drive, not a protocol.
- **Verify against real output before believing a diff.** The original reference
  workbook looked like it contained 14 fabricated rows; they were correct, and
  the shop convention behind them was simply undocumented. Ask before concluding
  that existing output is wrong.

## Releasing

Pushes to `main` or `claude/**` build `AutoBOM.exe` on a Windows runner and
republish it to the fixed `windows-latest-build` tag, so this link never
changes:

```
https://github.com/burntbysam/AutoBOM/releases/download/windows-latest-build/AutoBOM.exe
```

`build_id` (`<run number>.<short sha>`) moves every build independently of
`VERSION`, so the updater still detects a rebuild at the same version. There is
nothing to tag by hand.

To build locally on Linux without a Windows machine:
`packaging/build-windows-exe.sh` (runs a real Windows CPython under Wine).

## Checks before pushing

```
python -m pytest -q
python -m autobom --selftest
```
