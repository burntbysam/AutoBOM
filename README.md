# AutoBOM

Desktop BOM processor for CNC sheet metal work. Feed it your bus section BOMs
and your IL (indented list) CSVs; it filters for sheet aluminium, multiplies out
final quantities, classifies parts by thickness and Trumpf fit, and writes a
sorted 5-sheet Excel workbook for the shop floor.

The whole workflow is deterministic — same files in, same workbook out, every
time.

## Using the app

1. Launch AutoBOM.
2. Drag your bus section BOMs (`8701-01101-I.csv`) into the left list and your
   IL CSVs (`IL-8701-011.csv`) into the right one. You can also use **Add
   files…**, and dropping a folder picks up every `.csv` inside it.
3. Press **Process → Save workbook**.
4. If the cross-check finds a mismatch, a **⚠️ FLAGS — REVIEW REQUIRED** dialog
   explains it and waits. Nothing is written until you choose *Add missing
   files* or *Ignore and continue*.
5. Pick where to save. You get `OUTPUT__<job>_BOM_Quantities.xlsx`.

### Command line

The same engine runs headless, which is handy for batch jobs:

```
python -m autobom path/to/job-folder -o OUTPUT__8701_BOM_Quantities.xlsx
```

Files are sorted into BOMs and ILs by name (anything starting `IL` is an IL);
override with `--bom FILE` / `--il FILE`. Cross-check flags stop the run with
exit code 1 unless you pass `--ignore-flags`.

## What the rules are

**Input** — both file types are pipe-delimited with a leading `sep=|` line.

| BOM columns | IL columns |
| --- | --- |
| ITEM NUMBER, ITEM QUANTITY, DESCRIPTION, INVENTORY CODE, SHOP TYPE | LINE NUMBER, ASSEMBLY QUANTITY, DESCRIPTION, ASSEMBLY NUMBER, SHOP CODE |

**Filtering** — only rows whose DESCRIPTION starts with `SHEET,AL` are kept, and
that check is case-sensitive.

**Part numbers** — built from the filename and item number:
`8551-07127-I.csv` + item `3` → `8551-7127-3` (drop the extension, drop the
trailing `-I`, drop one leading zero from the assembly, append the item).

**Quantities** — Final Qty = BOM item quantity × IL assembly quantity, summed
wherever the same part number turns up more than once.

**Thickness** (±0.005): `1/8"` covers 0.120–0.130, `3/16"` covers 0.1825–0.1925,
everything else is `OTHER` and gets flagged for review.

**Fits Trumpf** — `T` when the smaller dimension is ≤ 60 and the larger is
≤ 133.5, in either orientation; otherwise `F`. This is independent of thickness.

**Output** — five sheets, always, with columns `Qty | Part # | Thickness | Size
| Fits Trumpf` and every sheet sorted by Part #:

| Sheet | Contents |
| --- | --- |
| `1-8` | 1/8" **and** T |
| `3-16` | 3/16" **and** T |
| `F Parts` | everything F, any thickness |
| `Other` | everything OTHER, either fit |
| `All` | every part |

An OTHER part goes on `Other` and `All` only. An F part goes on `F Parts` and
`All` only.

### Cross-check flags

- **FLAG 1** — a BOM you supplied that no IL line references. Its parts are not
  in the workbook, because there is no assembly quantity to multiply by.
- **FLAG 2** — an assembly the IL calls for that you supplied no BOM for. Its
  sheet metal is not counted.

AutoBOM never invents a part for an unmatched assembly. If the IL asks for
`JB-2724-06` and no `JB-2724-06` BOM was supplied, that assembly is reported as
FLAG 2 and contributes zero rows — its thickness and sheet size are simply not
knowable from the files on hand.

## Development

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Layout:

| Path | Purpose |
| --- | --- |
| `autobom/core/` | parsing, classification, aggregation, Excel output — no GUI imports |
| `autobom/gui/` | PySide6 desktop window |
| `autobom/updater/` | GitHub Releases version check |
| `autobom/cli.py` | headless entry point |
| `packaging/autobom.spec` | PyInstaller build |

Sample BOMs, ILs and reference workbooks are customer data and are **not**
committed; `tests/data/` is gitignored. Drop real files there and the
integration tests in `tests/test_sample_data.py` pick them up automatically —
without them, those tests skip and the rest of the suite still runs.

### Building the executable

PyInstaller does not cross-compile, so the Windows build has to happen on
Windows (or in the `windows-latest` CI job):

```
pip install -r requirements-dev.txt
pyinstaller --noconfirm packaging/autobom.spec
```

That produces a single-file `dist/AutoBOM.exe`.

### Releasing

Bump `VERSION`, commit, then push a tag:

```
git tag v1.1.0 && git push origin v1.1.0
```

`.github/workflows/release.yml` runs the tests, builds `AutoBOM.exe` on Windows,
and attaches it to the GitHub release. The app checks that release feed on
launch and offers the download when a newer tag appears; the check fails
silently when the machine is offline, so AutoBOM still works on an isolated
shop network.
