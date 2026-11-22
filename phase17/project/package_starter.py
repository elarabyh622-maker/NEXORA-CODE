"""Build or verify the Java 21 library starter ZIP."""

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference"
ARCHIVE = ROOT.parents[1] / "phase2/apps/web/public/projects/java-library-starter-v1.zip"
PROJECT_FILES = (
    "README.md",
    "src/Library.java",
    "src/Lending.java",
    "data/books.tsv",
    "tests/LibraryTests.java",
)
LENDING_STUB = b'''import java.util.List;

public final class Lending {
    static List<Library.Book> borrow(List<Library.Book> books, String id, String borrower) {
        // TODO: Validate the request and return a new list with the available book lent to the borrower.
        throw new UnsupportedOperationException("Borrow is incomplete");
    }
}
'''


def starter_files():
    files = {name: (REFERENCE / name).read_bytes().replace(b"\r\n", b"\n") for name in PROJECT_FILES}
    files["src/Lending.java"] = LENDING_STUB
    return files


def package_starter(check: bool):
    files = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            if zipped.namelist() != list(files):
                raise ValueError("Unexpected Java library starter ZIP members")
            if any(zipped.read(name) != contents for name, contents in files.items()):
                raise ValueError("Java library starter ZIP differs from reviewed sources")
    else:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
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
