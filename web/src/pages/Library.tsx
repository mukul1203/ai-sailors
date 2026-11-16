import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import BookFolder from "../components/BookFolder";
import type { LibraryBook } from "../types";

// The Play tab: only chapters a child may play (published books, approved beats).
export default function Library() {
  const navigate = useNavigate();
  const { data: missions, error, isPending } = useQuery({
    queryKey: ["missions"],
    queryFn: api.missions,
  });

  const byBook = new Map<number, LibraryBook>();
  for (const m of missions ?? []) {
    if (!byBook.has(m.book_id)) {
      byBook.set(m.book_id, { id: m.book_id, title: m.book, author: "", chapters: [] });
    }
    byBook.get(m.book_id)!.chapters.push({
      idx: m.chapter_idx, title: m.chapter, state: "playable", beats: m.beats,
    });
  }
  const books = [...byBook.values()];

  return (
    <section>
      <p className="lead">
        Open a book, pick a chapter, and play! Choose what you think happens next, and ask your
        sidekick anything about the story.
      </p>
      {error && <p className="error" role="alert">{error.message}</p>}
      <div className="library">
        {books.map((book) => (
          <BookFolder
            key={book.id} book={book} grownUp={false} alone={books.length === 1} busy={false}
            onPlay={(bookId, chapterIdx) => navigate(`/quest/${bookId}/${chapterIdx}`)}
          />
        ))}
      </div>
      {!isPending && !error && books.length === 0 && (
        <p className="note">
          No stories are ready yet. A grown-up can add and prepare one in the Books tab, then
          review and publish it in the Review tab.
        </p>
      )}
    </section>
  );
}
