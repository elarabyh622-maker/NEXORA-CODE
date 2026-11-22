"""Build or verify the Codex local automation starter ZIP."""

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference"
ARCHIVE = ROOT.parents[1] / "phase2/apps/web/public/projects/codex-automation-starter-v1.zip"
PROJECT_FILES = (
    "README.md",
    "LEARNER-PROMPT.md",
    "LICENSES.md",
    "New-InventoryReport.ps1",
    "Test-InventoryReport.ps1",
    "data/orders.csv",
)


def starter_files():
    files = {name: (REFERENCE / name).read_bytes().replace(b"\r\n", b"\n") for name in PROJECT_FILES}
    key = "New-InventoryReport.ps1"
    completed_preview = b"if ($Preview) {\n    $report\n    return\n}"
    stub = (b"# TODO: Complete preview before creating or writing any files.\n"
            b"if ($Preview) {\n    throw 'Preview mode is incomplete.'\n}")
    if files[key].count(completed_preview) != 1:
        raise ValueError("Expected one completed preview branch in the reference script")
    files[key] = files[key].replace(completed_preview, stub)
    return files


def package_starter(check: bool):
    files = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            if zipped.namelist() != list(files):
                raise ValueError("Unexpected Codex automation starter ZIP members")
            if any(zipped.read(name) != contents for name, contents in files.items()):
                raise ValueError("Codex automation starter ZIP differs from reviewed sources")
    else:
        with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, contents in files.items():
                entry = zipfile.ZipInfo(name, date_time=(2026, 11, 21, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                zipped.writestr(entry, contents, compresslevel=9)
    print(f"PASSED: {ARCHIVE.name} has {len(files)} reviewed members")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the existing starter ZIP")
    package_starter(parser.parse_args().check)
