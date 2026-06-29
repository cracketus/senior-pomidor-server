from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Photo
from app.services import resolve_photo_storage_dir, resolve_stored_photo_path
from app.validation import ValidationError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report missing and orphaned uploaded photo files.")
    parser.add_argument("--storage-dir", default=settings.photo_storage_dir)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    storage_dir = resolve_photo_storage_dir(args.storage_dir)
    expected_paths: set[Path] = set()
    missing: list[str] = []

    with SessionLocal() as db:
        photos = db.scalars(select(Photo)).all()
        for photo in photos:
            try:
                path = resolve_stored_photo_path(str(storage_dir), photo.storage_path)
            except ValidationError:
                missing.append(f"{photo.photo_id}: unsafe stored path {photo.storage_path}")
                continue
            expected_paths.add(path)
            if not path.is_file():
                missing.append(f"{photo.photo_id}: missing {path}")

    actual_paths = set(storage_dir.rglob("*.jpg")) if storage_dir.exists() else set()
    orphans = sorted(actual_paths - expected_paths)

    for item in missing:
        print(f"MISSING {item}")
    for path in orphans:
        print(f"ORPHAN {path}")

    if missing or orphans:
        print(f"photo storage check failed: missing={len(missing)} orphan={len(orphans)}", file=sys.stderr)
        return 1
    print("photo storage check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
