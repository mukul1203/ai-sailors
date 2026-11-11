from storyquest.domain.book import Book, Chapter
from storyquest.stores.content_repo import ContentRepo


def make_book(book_id: int = 236, title: str = "The Jungle Book") -> Book:
    return Book(id=book_id, title=title, author="Rudyard Kipling", raw_path="x", content_sha256="0")


def add_book_with_chapters(repo: ContentRepo, book_id: int = 236, chapters: int = 2) -> None:
    repo.upsert_book(make_book(book_id))
    repo.replace_chapters(
        book_id,
        [Chapter(i, f"Chapter {i}", "story", i * 1000, i * 1000 + 999) for i in range(chapters)],
    )
