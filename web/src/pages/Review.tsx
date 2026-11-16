import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useFlash } from "../flash";
import type { ApproveBody, ReviewBeat, ReviewChapter } from "../types";

function BeatCard({
  beat, onApprove, busy,
}: { beat: ReviewBeat; onApprove: () => void; busy: boolean }) {
  const approved = beat.status === "approved";
  return (
    <article className={`card beat${beat.flags.length ? " flagged" : ""}`}>
      <h3>
        Part {beat.idx + 1}: {beat.title || "(no title)"}
        <span className={`chip-state ${approved ? "playable" : ""}`}>{beat.status}</span>
      </h3>
      {!beat.narration ? (
        <p className="note">No text yet: prepare this chapter first.</p>
      ) : (
        <>
          {beat.flags.length > 0 && (
            <ul className="flags">{beat.flags.map((f) => <li key={f}>{f}</li>)}</ul>
          )}
          <p className="narration small">{beat.narration}</p>
          {beat.question && (
            <>
              <p className="question">{beat.question}</p>
              <ul className="answers-list">
                {beat.cards.map((c) => (
                  <li key={c.text} className={c.right ? "right" : ""}>
                    {c.right ? "Right: " : "Wrong: "}{c.text}
                  </li>
                ))}
              </ul>
              {beat.hints.length > 0 && <p className="note">Hints: {beat.hints.join(" / ")}</p>}
            </>
          )}
          {!approved && (
            <button className="secondary" disabled={busy} onClick={onApprove}>
              {beat.flags.length ? "Approve despite the warning" : "Approve"}
            </button>
          )}
        </>
      )}
    </article>
  );
}

function ChapterFolder({
  chapter, published, defaultOpen, onApprove, busy,
}: {
  chapter: ReviewChapter; published: boolean; defaultOpen: boolean;
  onApprove: (body: ApproveBody) => void; busy: boolean;
}) {
  const waiting = chapter.beats.filter((b) => b.status !== "approved").length;
  const flagged = chapter.beats.filter((b) => b.flags.length && b.status !== "approved").length;
  return (
    <details className="book" open={defaultOpen || undefined}>
      <summary>
        {chapter.title}
        <small>
          {chapter.beats.length
            ? `${chapter.beats.length} parts, ${waiting} waiting for approval, ${flagged} with warnings`
            : "Not prepared yet"}
        </small>
      </summary>
      {waiting > 0 && !published && (
        <button
          className="secondary" disabled={busy}
          onClick={() => onApprove({ chapter_idx: chapter.idx })}
        >
          Approve parts without a warning
        </button>
      )}
      {chapter.beats.map((beat) => (
        <BeatCard
          key={beat.idx} beat={beat} busy={busy}
          onApprove={() => onApprove({ chapter_idx: chapter.idx, beat_idx: beat.idx })}
        />
      ))}
    </details>
  );
}

// Grown-ups: read what the model wrote, approve it, then publish the book.
export default function Review() {
  const { bookId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setNotice, setError, clear } = useFlash();

  const library = useQuery({ queryKey: ["library"], queryFn: api.library });
  const books = (library.data ?? []).filter((b) => b.id !== null);
  const selected = bookId ? Number(bookId) : (books[0]?.id ?? null);

  const review = useQuery({
    queryKey: ["review", selected],
    queryFn: () => api.review(selected as number),
    enabled: selected !== null,
  });

  const reload = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["review", selected] }),
      queryClient.invalidateQueries({ queryKey: ["library"] }),
      queryClient.invalidateQueries({ queryKey: ["missions"] }),
    ]);
  };

  const approve = useMutation({
    mutationFn: (body: ApproveBody) => api.approve(selected as number, body),
    onMutate: clear,
    onSuccess: async (out) => {
      await reload();
      let text = `${out.approved} approved.`;
      if (out.flagged_left) {
        text += ` ${out.flagged_left} with warnings are left: read them and approve one by one.`;
      }
      if (out.empty_left) {
        text += ` ${out.empty_left} have no text yet: prepare the chapter first.`;
      }
      setNotice(text);
    },
    onError: (e: Error) => setError(e.message),
  });

  const publish = useMutation({
    mutationFn: () => api.publish(selected as number),
    onMutate: clear,
    onSuccess: async (out) => {
      await reload();
      let text = out.published
        ? "Published! Children can now play it from the Play tab."
        : `Not published yet: ${out.problems.join("; ")}`;
      if (out.embedding_error) {
        text += ` Embeddings stopped early (${out.embedding_error}); run make embed to finish them.`;
      }
      setNotice(text);
    },
    onError: (e: Error) => setError(e.message),
  });

  const busy = approve.isPending || publish.isPending;
  const r = review.data;
  const published = r?.status === "ready";

  return (
    <section>
      <p className="lead">
        For grown-ups: read what the model wrote, approve it, then publish the book so children
        can play it.
      </p>
      {library.isSuccess && books.length === 0 && <p className="note">No books to review yet.</p>}
      {books.length > 0 && (
        <label className="pick">Book
          <select
            value={selected ?? ""}
            onChange={(e) => navigate(`/review/${e.target.value}`)}
          >
            {books.map((b) => (
              <option key={b.id} value={b.id as number}>
                {b.status === "ready" ? `${b.title} (published)` : b.title}
              </option>
            ))}
          </select>
        </label>
      )}
      {review.error && <p className="error" role="alert">{review.error.message}</p>}
      {r && (
        <div>
          <div className="card">
            <h2>
              {r.title}
              <span className={`chip-state ${published ? "playable" : ""}`}>
                {published ? "Published" : "Not published"}
              </span>
            </h2>
            {!published && (
              <>
                {r.problems.length > 0 && (
                  <>
                    <p>Before this book can be published:</p>
                    <ul className="problems">{r.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                  </>
                )}
                <div className="actions">
                  <button className="secondary" disabled={busy} onClick={() => approve.mutate({})}>
                    Approve every part without a warning
                  </button>
                  <button disabled={busy || r.problems.length > 0} onClick={() => publish.mutate()}>
                    Publish this book
                  </button>
                </div>
              </>
            )}
          </div>
          {r.chapters.map((chapter) => (
            <ChapterFolder
              key={chapter.idx} chapter={chapter} published={published} busy={busy}
              defaultOpen={chapter.beats.some((b) => b.flags.length > 0 && b.status !== "approved")}
              onApprove={(body) => approve.mutate(body)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
