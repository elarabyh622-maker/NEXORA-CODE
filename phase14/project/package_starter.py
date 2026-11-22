"""Build or verify the downloadable C# inventory starter ZIP."""

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference"
ARCHIVE = ROOT.parents[1] / "phase2/apps/web/public/projects/csharp-inventory-starter-v1.zip"
PROJECT_FILES = (
    "README.md",
    "LICENSES.md",
    "Inventory.Core/Inventory.Core.csproj",
    "Inventory.Core/Inventory.cs",
    "Inventory.Core/InventoryFile.cs",
    "Inventory.Core/Product.cs",
    "Inventory.Cli/Inventory.Cli.csproj",
    "Inventory.Cli/Program.cs",
    "Inventory.Tests/Inventory.Tests.csproj",
    "Inventory.Tests/Program.cs",
    "data/sample-inventory.json",
)


def starter_files():
    files = {name: (REFERENCE / name).read_bytes().replace(b"\r\n", b"\n") for name in PROJECT_FILES}
    source = files["Inventory.Core/Inventory.cs"]
    signature = b"    public int RemoveStock(string sku, int quantity)\n    {\n"
    if source.count(signature) != 1:
        raise ValueError("Expected one RemoveStock method in the inventory source")
    opening, _, remaining = source.partition(signature)
    body, closing, tail = remaining.partition(b"\n    }\n")
    if not body or not closing:
        raise ValueError("Expected a complete reference implementation of RemoveStock")
    stub = (
        "        // TODO: أكمل التحقق من الكمية والرصيد وتحديث الصنف.\n"
        "        throw new NotImplementedException(\"أكمل مهمة صرف الكمية.\");"
    ).encode("utf-8")
    files["Inventory.Core/Inventory.cs"] = opening + signature + stub + closing + tail
    return files


def package_starter(check: bool):
    files = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            if zipped.namelist() != list(files):
                raise ValueError("Unexpected inventory starter ZIP members")
            if any(zipped.read(name) != data for name, data in files.items()):
                raise ValueError("Inventory starter ZIP differs from reviewed sources")
    else:
        with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, contents in files.items():
                entry = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                zipped.writestr(entry, contents, compresslevel=9)
    print(f"PASSED: {ARCHIVE.name} has {len(files)} reviewed members")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the existing starter ZIP")
    package_starter(parser.parse_args().check)
