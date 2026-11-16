import type { ReactNode } from "react";
import type { Chapter, ChapterState, LibraryBook } from "../types";

const STATE_TEXT: Record<ChapterState, string> = {
  playable: "Ready to play",
  prepared: "Prepared",
  not_prepared: "Not prepared yet",
  preparing: "Getting ready...",
  failed: "Could not prepare",
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
      {grownUp && <span className={`chip-state ${chapter.state}`}>{STATE_TEXT[chapter.state]}</span>}
      {action}
    </li>
  );
}

// A book is a folder; its chapters are inside. Open/closed is remembered per book.
export default function BookFolder({ book, grownUp, alone, busy, onPlay, onPrepare }: Props) {
  const key = String(book.id);
  const todo = book.chapters.filter((c) => c.state === "not_prepared" || c.state === "failed");
  const published = book.status === "ready";
  return (
    <details
      className="book"
      open={readOpen().has(key) || alone}
      onToggle={(e) => rememberOpen(key, e.currentTarget.open)}
    >
      <summary>
        {book.title}
        <small>{book.author ? `by ${book.author}` : ""}</small>
        {grownUp && book.id !== null && (
          <span className={`chip-state ${published ? "playable" : ""}`}>
            {published ? "Published" : "Not published"}
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
