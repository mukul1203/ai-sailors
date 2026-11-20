import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
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

  // Which step of the workflow the grown-up is on.
  const real = books.filter((b) => b.id !== null);
  const anyPrepared = real.some((b) =>
    b.chapters.some((c) => c.state === "playable" || c.state === "prepared"));
  const allPublished = real.length > 0 && real.every((b) => b.status === "ready");
  const step = real.length === 0 ? 1 : allPublished ? 4 : anyPrepared ? 3 : 2;
  const STEPS = ["Add", "Prepare", "Review", "Publish"];
  const HINTS = [
    "Add a book from Project Gutenberg below.",
    "Choose “Prepare this story” on a chapter. The model writes the story parts.",
    "Check the parts in the Review tab and approve them.",
    "All books are published. Children can play them in the Play tab.",
  ];

  return (
    <section className="admin">
      <ol className="steps" aria-label="Steps">
        {STEPS.map((name, i) => (
          <li key={name} className={i + 1 < step ? "done" : i + 1 === step ? "now" : ""}>
            <span className="dot">{i + 1 < step ? "✓" : i + 1}</span> {name}
          </li>
        ))}
      </ol>
      <p className="lead">
        {HINTS[step - 1]}{" "}
        {step === 3 && <Link to="/review">Go to Review →</Link>}
      </p>
      <details className="card add" open={adding} onToggle={(e) => setAdding(e.currentTarget.open)}>
        <summary>＋ Add a book from Project Gutenberg</summary>
        <form className="form" autoComplete="off" onSubmit={submit}>
          <label>Gutenberg number
            <input type="number" min={1} required value={form.id} onChange={set("id")} />
            <small>
              The number in the book's web address, e.g. 236 for gutenberg.org/ebooks/236.
            </small>
          </label>
          <label>Title
            <input maxLength={200} required value={form.title} onChange={set("title")} />
          </label>
          <label>Author
            <input maxLength={200} required value={form.author} onChange={set("author")} />
          </label>
          <label>Summary
            <textarea rows={3} maxLength={2000} value={form.summary} onChange={set("summary")} />
          </label>
          <label>Notes for grown-ups
            <textarea rows={2} maxLength={1000} value={form.notes} onChange={set("notes")} />
          </label>
          <label>Plain-text file (.txt)
            <input
              type="file" accept=".txt,text/plain" required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            {file && <small>Chosen: {file.name}</small>}
          </label>
          <button type="submit" disabled={busy}>{add.isPending ? "Adding..." : "Add the book"}</button>
        </form>
      </details>
      <div className="toolbar">
        <a
          className="link" href="https://www.gutenberg.org/" target="_blank" rel="noopener noreferrer"
        >
          Look for new books ↗
        </a>
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
        <div className="empty">
          <div aria-hidden="true">📚</div>
          <p>
            No books yet. Add one above, or put a folder in the <b>books</b> folder (see the
            README).
          </p>
        </div>
      )}
    </section>
  );
}
