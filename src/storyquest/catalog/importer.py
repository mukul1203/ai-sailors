"""Catalog import: register books from folders of raw.txt plus book.yaml."""

import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from storyquest.domain.book import Book
from storyquest.stores.content_repo import ContentRepo


class CatalogError(Exception):
    pass


def import_books(conn: sqlite3.Connection, data_dir: Path, source: Path) -> list[Book]:
    """Verify each book folder, copy its text under data_dir, and upsert its record."""
    repo = ContentRepo(conn)
    imported: list[Book] = []
    for folder in sorted(p for p in source.iterdir() if (p / "book.yaml").is_file()):
        meta: dict[str, Any] = yaml.safe_load((folder / "book.yaml").read_text())
        raw = folder / "raw.txt"
        if not raw.is_file():
            raise CatalogError(f"{folder.name}: raw.txt is missing")
        data = raw.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != meta["sha256"]:
            raise CatalogError(f"{folder.name}: raw.txt does not match the sha256 in book.yaml")

        book_id = int(meta["gutenberg_id"])
        relative = f"books/{book_id}/raw.txt"
        dest = data_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or dest.read_bytes() != data:
            shutil.copyfile(raw, dest)

        book = Book(
            id=book_id,
            title=str(meta["title"]),
            author=str(meta["author"]),
            raw_path=relative,
            content_sha256=sha,
            language=str(meta.get("language", "en")),
            age_band=str(meta.get("age_band", "")),
            summary=str(meta.get("summary", "")),
            content_notes=str(meta.get("content_notes", "")),
            visibility=str(meta.get("visibility", "listed")),
        )
        repo.upsert_book(book)
        imported.append(book)
    return imported
