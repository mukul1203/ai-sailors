import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import BookFolder from "../components/BookFolder";
import { useFlash } from "../flash";

const POLL_MS = 3000;

// Grown-ups: add a book, then prepare its chapters (the model writes the story parts).
export default function Books() {
  const queryClient = useQueryClient();
  const { setNotice, setError, clear } = useFlash();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ id: "", title: "", author: "", summary: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);

  const library = useQuery({
    queryKey: ["library"],
    queryFn: api.library,
    // keep refreshing while any chapter is being prepared
    refetchInterval: (query) =>
      query.state.data?.some((b) => b.chapters.some((c) => c.state === "preparing"))
        ? POLL_MS
        : false,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["library"] });

  const prepare = useMutation({
    mutationFn: ({ bookId, chapterIdxs }: { bookId: number; chapterIdxs: number[] }) =>
      Promise.all(chapterIdxs.map((idx) => api.prepare(bookId, idx))),
    onMutate: clear,
    onSuccess: refresh,
    onError: (e: Error) => setError(e.message),
  });

  const add = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a .txt file first.");
      return api.addBook({
        gutenberg_id: Number(form.id),
        title: form.title.trim(),
        author: form.author.trim(),
        summary: form.summary.trim(),
        content_notes: form.notes.trim(),
        text: await file.text(),
      });
    },
    onMutate: clear,
    onSuccess: async (out) => {
      setForm({ id: "", title: "", author: "", summary: "", notes: "" });
      setFile(null);
      setAdding(false);
      await refresh();
      setNotice(`Added "${out.title}". Prepare its chapters below, then review it.`);
    },
    onError: (e: Error) => setError(e.message),
  });

  const books = library.data ?? [];
  const busy = prepare.isPending || add.isPending;
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section>
      <p className="lead">
        For grown-ups: add a book, then prepare its chapters. The model writes the story parts and
        questions; you check them in the Review tab.
      </p>
      <details className="card add" open={adding} onToggle={(e) => setAdding(e.currentTarget.open)}>
        <summary>Add a book from Project Gutenberg</summary>
        <form className="form" autoComplete="off" onSubmit={submit}>
          <label>Gutenberg number
            <input type="number" min={1} required value={form.id} onChange={set("id")} />
          </label>
          <label>Title
            <input maxLength={200} required value={form.title} onChange={set("title")} />
          </label>
          <label>Author
            <input maxLength={200} required value={form.author} onChange={set("author")} />
          </label>
          <label>Summary
            <input maxLength={2000} value={form.summary} onChange={set("summary")} />
          </label>
          <label>Notes for grown-ups
            <input maxLength={1000} value={form.notes} onChange={set("notes")} />
          </label>
          <label>Plain-text file (.txt)
            <input
              type="file" accept=".txt,text/plain" required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={busy}>Add the book</button>
        </form>
      </details>
      <div className="toolbar">
        <button className="link" onClick={() => { clear(); library.refetch(); }}>
          Look for new books
        </button>
      </div>
      {library.error && <p className="error" role="alert">{library.error.message}</p>}
      <div className="library">
        {books.map((book) => (
          <BookFolder
            key={book.id ?? book.title} book={book} grownUp alone={books.length === 1} busy={busy}
            onPrepare={(bookId, chapterIdxs) => prepare.mutate({ bookId, chapterIdxs })}
          />
        ))}
      </div>
      {library.isSuccess && books.length === 0 && (
        <p className="note">
          No books yet. Add one above, or put a folder in the books folder (see the README).
        </p>
      )}
    </section>
  );
}
