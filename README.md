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
5. Pick where to save. You get `<job> BOM Quantities.xlsx`.

### Command line

The same engine runs headless, which is handy for batch jobs:

```
python -m autobom path/to/job-folder -o "8701 BOM Quantities.xlsx"
```

Files are sorted into BOMs and ILs by name (anything starting `IL` is an IL);
override with `--bom FILE` / `--il FILE`. Cross-check flags stop the run with
exit code 1 unless you pass `--ignore-flags`.

## What the rules are

**Input** — both file types are pipe-delimited with a leading `sep=|` line.

| BOM columns | IL columns |
| --- | --- |
| ITEM NUMBER, ITEM QUANTITY, DESCRIPTION, INVENTORY CODE, SHOP TYPE | LINE NUMBER, ASSEMBLY QUANTITY, DESCRIPTION, ASSEMBLY NUMBER, SHOP CODE |

**Filtering** — only rows whose DESCRIPTION starts with `SHEET,AL` are kept.
The check is case-sensitive, but spacing around the comma is not meaningful:
`SHEET, AL, ...` (job 8763's style) matches too.

**Part numbers** — built from the filename and item number:
`8551-07127-I.csv` + item `3` → `8551-7127-3` (drop the extension, drop the
trailing `-I`, drop one leading zero from the assembly, append the item).

**Quantities** — Final Qty = BOM item quantity × IL assembly quantity, summed
wherever the same part number turns up more than once.

**Individual parts** — the 300 series (`8701-300-I`) and JB parts
(`JB-2724-06`) are single pieces, not assemblies, so they have no BOM of their
own. They are taken straight off the IL, counted at the IL's assembly quantity
with nothing to multiply, and assigned standard stock: **1/8", 60x120, T**.
Their part number is the assembly number verbatim.

A bus section is `8701-01101-I` — five digits *with* a leading zero — so it
never matches those patterns, and a bus section BOM you forgot to send is still
caught as FLAG 2 rather than quietly becoming one standard sheet.

Sizes may be written plain (`60x120`) or with inch marks and a capital X
(`92"X120"`, `69.50"X120"`); both parse as real dimensions.

**Missing size** — a `SHEET,AL` row whose description carries no WxH is
counted at the standard **60x120** sheet rather than skipped; a skipped row is
a missing part on the floor. The run reports every row it assumed, in the
console and the app's log, so a defaulted size is visible and correctable.
A row with no readable thickness is still skipped and warned about — there is
no bucket to put it in.

**Never counted** — any row whose description is `COVER JOINER CHANNEL` is
dropped, in a BOM or an IL, whatever it is attached to. The run reports each
row it removed. The list lives in `EXCLUDED_DESCRIPTIONS` in
`autobom/core/parser.py` if more need adding.

**Thickness** (±0.005): `1/8"` covers 0.120–0.130, `3/16"` covers 0.1825–0.1925,
everything else is `OTHER` and gets flagged for review.

**Fits Trumpf** — the largest sheet the machine takes is **61.5 x 120**. `T`
when the smaller dimension is ≤ 61.5 and the larger is ≤ 120, in either
orientation; anything over that is `F`. Both limits are inclusive, so 61.5x120
itself fits. This is independent of thickness.

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

### Totals

Every sheet ends with a totals line below the data — the piece count sits under
the `Qty` column it sums, alongside the number of line items:

```
63   TOTAL PIECES   35   LINE ITEMS
```

The `All` sheet carries the full tally instead, grouped **by thickness**, so an
F part counts toward its own thickness rather than being set aside:

```
SUMMARY
Category               Line items   Pieces
1/8"                           38       66
3/16"                           0        0
1/8" + 3/16" total             38       66
OTHER thickness                 0        0
Grand total                    38       66
```

The three category rows add up to the grand total: nothing is counted twice and
nothing is left out. Because the grouping is by thickness, the `1/8"` row here
can exceed the `1-8` sheet's own total — the sheet holds only parts that also
fit the Trumpf, while this row counts every 1/8" part. Both numbers are on the
face of the workbook. The same tally prints to the console after a run.

### Cross-check flags

- **FLAG 1** — a BOM you supplied that no IL line references. Its parts are not
  in the workbook, because there is no assembly quantity to multiply by.
- **FLAG 2** — a *bus section* the IL calls for that you supplied no BOM for.
  Its sheet metal is not counted. 300-series and JB parts never appear here;
  they are individual parts and are counted automatically.

Outside those two families, AutoBOM never invents a part for an unmatched
assembly — an unknown assembly's thickness and sheet size are not knowable from
the files on hand, so it is flagged rather than guessed at.

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

On Windows (and in the `windows-latest` CI job, which is the reference build):

```
pip install -r requirements-dev.txt
pyinstaller --noconfirm packaging/autobom.spec
```

That produces a single-file `dist/AutoBOM.exe`.

**From Linux**, without a Windows machine:

```
apt-get install wine64
packaging/build-windows-exe.sh
```

PyInstaller cannot cross-compile, but it does not have to — the script runs a
real Windows CPython under Wine, so PyInstaller emits a genuine PE executable.
It fetches the interpreter from the `python-build-standalone` GitHub release
assets rather than python.org, which egress policies often block.

Either way the `.exe` is unsigned, so Windows SmartScreen warns on first launch
until it builds reputation. Code signing is a separate step.

### Releasing

There is nothing to tag. `.github/workflows/build-windows.yml` runs on every
push to `main` or a `claude/**` branch: it runs the tests, builds the
executable, makes the built `.exe` self-test itself, and republishes it to a
fixed release tag.

`VERSION` is bumped in the same commit as the change it describes:

| Change | Bump | |
| --- | --- | --- |
| Any push — bug fix, docs, refactor | patch | `1.0.0 → 1.0.1` |
| A significant feature added, removed or overhauled | minor | `1.0.1 → 1.1.0` |
| The whole app overhauled | major | `1.1.0 → 2.0.0` |

```
python scripts/bump_version.py patch    # or minor / major
```

A major bump is the maintainer's call only. The build identifier moves on its
own every build, independently of `VERSION`.

The download link is therefore permanent:

> **https://github.com/burntbysam/AutoBOM/releases/download/windows-latest-build/AutoBOM.exe**

The release also carries `latest.json`, the manifest installed copies poll:

```json
{"version": "1.0.0", "build_id": "42.a1b2c3d", "sha256": "…",
 "size": 25356582, "url": "https://…/AutoBOM.exe", "notes": "…"}
```

`build_id` is `<run number>.<short sha>` and changes on every build, so a fix
shipped without a version bump is still recognised as newer. A downloaded
update is rejected and deleted unless it matches the published SHA256.

Point the check somewhere else with `AUTOBOM_UPDATE_URL`. It accepts a UNC path,
which is usually what a shop wants — no GitHub access needed on the floor:

```
set AUTOBOM_UPDATE_URL=\\server\shared\AutoBOM\latest.json
```

The check runs on a background thread and fails silently when the machine is
offline, so AutoBOM still starts on an isolated network.

### Updating in place

When a newer build exists, the dialog offers **Update now**. AutoBOM downloads
it with a progress bar you can cancel, and installs it only after two checks:

1. the download matches the published SHA256, and
2. the downloaded build passes its own `--selftest`.

The second is the one that matters. A checksum proves the file arrived intact,
not that it works — a build that shipped a broken classifier would be perfectly
intact and would quietly produce the wrong cut list. Anything that fails either
check is deleted and the working copy is left untouched.

Windows will not let a running program overwrite its own image, but it will let
it be renamed, so the live build is renamed aside, the new one takes its place,
and the old copy is deleted on next launch. If the swap fails the rename is
undone, so a failed update leaves a working application rather than none.

Any process AutoBOM starts — the self-test, and the restart afterwards — gets
an environment with PyInstaller's bootloader variables removed. Inheriting them
makes the child run the *parent's* unpacked bundle, which then vanishes when the
parent exits.

**Update now** is hidden when there is nothing to replace — running from source,
or an executable in a location you cannot write to, such as Program Files
without elevation. The download page is still offered in those cases.

### Identifying a copy

**Help → About AutoBOM** reports the version, the CI build number, the commit it
was built from, where the executable lives, the Python and Qt versions, and the
update source it polls. **Copy details** puts all of that on the clipboard as
plain text, so "which build are you on?" has a paste-able answer.

A build made locally rather than by CI says so, instead of showing a build
number that means nothing.

### Verifying a copy

```
AutoBOM.exe --selftest
```

Processes a synthetic job covering every rule — both thickness windows, OTHER,
both Trumpf outcomes, an individual part and an excluded description — writes a
workbook, and checks every value. Exit code 0 means the copy is sound. It needs
no customer files, so it works on any machine.
