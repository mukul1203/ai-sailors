import type { ReactNode } from "react";
import { readQuests } from "../quests";
import type { Chapter, ChapterState, LibraryBook } from "../types";

const STATE_TEXT: Record<ChapterState, string> = {
  playable: "Ready to play",
  prepared: "Prepared",
  not_prepared: "Not prepared yet",
  preparing: "Getting ready...",
  failed: "Could not prepare",
};

const STATE_ICON: Record<ChapterState, string> = {
  playable: "✅",
  prepared: "✅",
  not_prepared: "○",
  preparing: "",
  failed: "⚠️",
};

const OPEN_KEY = "storyquest.open";

function readOpen(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function rememberOpen(id: string, isOpen: boolean) {
  try {
    const open = readOpen();
    if (isOpen) open.add(id);
    else open.delete(id);
    localStorage.setItem(OPEN_KEY, JSON.stringify([...open]));
  } catch {
    // storage unavailable: the folder just won't be remembered
  }
}

interface Props {
  book: LibraryBook;
  grownUp: boolean;
  alone: boolean; // the only book on screen: start open
  busy: boolean;
  onPlay?: (bookId: number, chapterIdx: number) => void;
  onPrepare?: (bookId: number, chapterIdxs: number[]) => void;
}

function ChapterRow({
  book, chapter, grownUp, busy, onPlay, onPrepare,
}: { book: LibraryBook; chapter: Chapter } & Pick<Props, "grownUp" | "busy" | "onPlay" | "onPrepare">) {
  const counted = chapter.state === "playable" || chapter.state === "prepared";
  const detail = counted ? `${chapter.beats} parts` : chapter.message;
  const id = book.id as number;
  let action: ReactNode = null;
  if (chapter.state === "playable" && !grownUp) {
    action = <button onClick={() => onPlay?.(id, chapter.idx)}>Play</button>;
  } else if (grownUp && (chapter.state === "not_prepared" || chapter.state === "failed")) {
    action = (
      <button className="secondary" disabled={busy} onClick={() => onPrepare?.(id, [chapter.idx])}>
        {chapter.state === "failed" ? "Try again" : "Prepare this story"}
      </button>
    );
  }
  return (
    <li className="chapter">
      <div className="name">
        <span>{chapter.title}</span>
        {detail && <small>{detail}</small>}
      </div>
      {grownUp && (
        <span className={`chip-state ${chapter.state}`}>
          {chapter.state === "preparing"
            ? <span className="spinner" aria-hidden="true" />
            : `${STATE_ICON[chapter.state]} `}
          {STATE_TEXT[chapter.state]}
        </span>
      )}
      {action}
    </li>
  );
}

const COVERS = ["🐺", "🐯", "🐘", "🦁", "🐻", "🦊", "🐍"];

// The child's view of a book: a big cover card with chapter tiles.
function KidBook({ book, onPlay }: Pick<Props, "book" | "onPlay">) {
  const id = book.id as number;
  const saved = readQuests();
  const cover = COVERS[id % COVERS.length];
  return (
    <section className="kid-book">
      <h2><span className="cover" aria-hidden="true">{cover}</span> {book.title}</h2>
      {book.author && <p className="by">by {book.author}</p>}
      {book.summary && <p className="about">{book.summary}</p>}
      <ul className="tiles">
        {book.chapters.filter((c) => c.state === "playable").map((c, i) => {
          const started = Boolean(saved[`${id}:${c.idx}`]);
          return (
            <li key={c.idx}>
              <button className={`tile t${i % 4}`} onClick={() => onPlay?.(id, c.idx)}>
                <span className="num" aria-hidden="true">{i + 1}</span>
                <span className="tile-name">
                  {c.title}
                  <small>{"⭐".repeat(Math.min(c.beats ?? 0, 5))}</small>
                </span>
                <span className="go">{started ? "▶ Continue" : "▶ Let's go!"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// A book is a folder; its chapters are inside. Open/closed is remembered per book.
export default function BookFolder({ book, grownUp, alone, busy, onPlay, onPrepare }: Props) {
  const key = String(book.id);
  if (!grownUp) return <KidBook book={book} onPlay={onPlay} />;
  const todo = book.chapters.filter((c) => c.state === "not_prepared" || c.state === "failed");
  const published = book.status === "ready";
  const done = book.chapters.filter((c) => c.state === "playable" || c.state === "prepared").length;
  const total = book.chapters.length;
  const preparing = book.chapters.some((c) => c.state === "preparing");
  return (
    <details
      className="book"
      open={readOpen().has(key) || alone}
      onToggle={(e) => rememberOpen(key, e.currentTarget.open)}
    >
      <summary>
        <span className="book-title">
          <span aria-hidden="true">📘</span> {book.title}
          {book.id !== null && (
            <span className={`chip-state ${published ? "playable" : ""}`}>
              {published ? "🌟 Published" : "Not published"}
            </span>
          )}
        </span>
        <small>{book.author ? `by ${book.author}` : ""}</small>
        {total > 0 && (
          <span className="prep">
            <span
              className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={total}
              aria-valuenow={done} aria-label="Chapters prepared"
            >
              <span className="fill" style={{ width: `${(done / total) * 100}%` }} />
            </span>
            <span className="prep-text">{done} of {total} chapters prepared</span>
          </span>
        )}
        {preparing && (
          <span className="prep-note">
            ⏳ The model is writing the story parts. This takes a few minutes per chapter.
          </span>
        )}
      </summary>
      {book.error && <p className="error">{book.error}</p>}
      {book.summary && <p className="about">{book.summary}</p>}
      {book.content_notes && <p className="caution">Note for grown-ups: {book.content_notes}</p>}
      <ul className="chapters">
        {book.chapters.map((c) => (
          <ChapterRow
            key={c.idx} book={book} chapter={c} grownUp={grownUp}
            busy={busy} onPlay={onPlay} onPrepare={onPrepare}
          />
        ))}
      </ul>
      {grownUp && todo.length > 1 && book.id !== null && (
        <button
          className="secondary" disabled={busy}
          onClick={() => onPrepare?.(book.id as number, todo.map((c) => c.idx))}
        >
          Prepare all {todo.length} chapters
        </button>
      )}
    </details>
  );
}
