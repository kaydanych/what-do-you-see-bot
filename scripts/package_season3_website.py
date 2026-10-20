"""Package the updated homepage and generated Season 3 gallery for upload.

The ZIP overlays an existing website. It leaves Season 2 and any other files
on the host alone. Replace the hosted /season3/ directory before uploading it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


HOME = Path(__file__).resolve().parents[1] / "finale-lab"


def package(gallery: Path, output: Path, *, home: Path = HOME) -> int:
    if not (gallery / "index.html").is_file() or not (gallery / "private" / "index.html").is_file():
        raise ValueError("Use a generated Season 3 gallery with a private directory index")
    homepage = (home / "index.html").read_text(encoding="utf-8")
    if 'href="season3/"' not in homepage:
        raise ValueError("Homepage does not link to Season 3")
    paths = sorted(path for path in gallery.rglob("*") if path.is_file())
    if any(path.suffix in {".csv", ".db", ".json", ".zip"} for path in paths):
        raise ValueError("Generated gallery contains a private data file")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name in ("index.html", "styles.css"):
            archive.write(home / name, name)
        for path in paths:
            archive.write(path, "season3/" + path.relative_to(gallery).as_posix())
    return len(paths) + 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gallery", type=Path, help="Generated Season 3 web root")
    parser.add_argument("--output", type=Path, required=True, help="New overlay ZIP under data/")
    args = parser.parse_args()
    count = package(args.gallery, args.output)
    print(f"Packaged {count} website files in {args.output}")


if __name__ == "__main__":
    main()
