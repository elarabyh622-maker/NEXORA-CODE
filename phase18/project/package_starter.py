"""Build or verify the deterministic Go tasks API starter ZIP."""

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference"
ARCHIVE = ROOT.parents[1] / "phase2/apps/web/public/projects/go-tasks-api-starter-v1.zip"
PROJECT_FILES = ("README.md", "go.mod", "main.go", "store.go", "complete.go", "main_test.go")
COMPLETE_STUB = b'''package main

func (s *Store) complete(id int) (Task, error) {
\t// TODO: Lock the store, find the task, reject a completed task, then complete it.
\treturn Task{}, ErrIncomplete
}
'''


def starter_files():
    files = {name: (REFERENCE / name).read_bytes().replace(b"\r\n", b"\n") for name in PROJECT_FILES}
    files["complete.go"] = COMPLETE_STUB
    return files


def package_starter(check: bool):
    files = starter_files()
    if check:
        with zipfile.ZipFile(ARCHIVE) as zipped:
            if zipped.namelist() != list(files):
                raise ValueError("Unexpected Go tasks API starter ZIP members")
            for entry in zipped.infolist():
                if (zipped.read(entry.filename) != files[entry.filename]
                        or entry.date_time != (2026, 11, 22, 0, 0, 0)
                        or entry.compress_type != zipfile.ZIP_DEFLATED
                        or entry.create_system != 3
                        or entry.external_attr != 0o100644 << 16):
                    raise ValueError("Go tasks API starter ZIP differs from reviewed sources")
    else:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, contents in files.items():
                entry = zipfile.ZipInfo(name, date_time=(2026, 11, 22, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                zipped.writestr(entry, contents, compresslevel=9)
    print(f"PASSED: {ARCHIVE.name} has {len(files)} reviewed members")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the existing starter ZIP")
    package_starter(parser.parse_args().check)
