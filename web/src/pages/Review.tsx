import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useFlash } from "../flash";
import type { ApproveBody, LibraryBook, ReviewBeat, ReviewChapter, ReviewView } from "../types";

type Stage = "published" | "none" | "not_reviewed" | "in_progress" | "reviewed";

const STAGE_TEXT: Record<Stage, string> = {
  published: "🌟 Published",
  reviewed: "✅ Reviewed, ready to publish",
  in_progress: "🟡 Review in progress",
  not_reviewed: "⚪ Not reviewed",
  none: "○ Nothing to review yet",
};
const STAGE_CLASS: Record<Stage, string> = {
  published: "playable", reviewed: "playable", in_progress: "preparing", not_reviewed: "", none: "",
};

// Where a book is in review, from its parts: none approved, some approved, all approved.
function stageOf(r: ReviewView | undefined): { stage: Stage; approved: number; total: number } {
  const beats = r?.chapters.flatMap((c) => c.beats.filter((b) => b.narration)) ?? [];
  const approved = beats.filter((b) => b.status === "approved").length;
  const total = beats.length;
  let stage: Stage = "not_reviewed";
  if (r?.status === "ready") stage = "published";
  else if (total === 0) stage = "none";
  else if (approved === total) stage = "reviewed";
  else if (approved > 0) stage = "in_progress";
  return { stage, approved, total };
}

// One card per book with its review stage; the selected book is highlighted.
function BookPicker({
  books, selected, onSelect,
}: { books: LibraryBook[]; selected: number | null; onSelect: (id: number) => void }) {
  const results = useQueries({
    queries: books.map((b) => ({
      queryKey: ["review", b.id],
      queryFn: () => api.review(b.id as number),
    })),
  });
  return (
    <div className="picker" role="group" aria-label="Books to review">
      {books.map((b, i) => {
        const { stage, approved, total } = stageOf(results[i]?.data);
        const loading = results[i]?.isPending;
        return (
          <button
            key={b.id} type="button" aria-pressed={b.id === selected}
            className={`pick-card${b.id === selected ? " on" : ""}`}
            onClick={() => onSelect(b.id as number)}
          >
            <span className="pick-title">{b.title}</span>
            <span className={`chip-state ${STAGE_CLASS[stage]}`}>
              {loading ? "Loading..." : STAGE_TEXT[stage]}
            </span>
            {!loading && total > 0 && stage !== "published" && (
              <span className="prep-text">{approved} of {total} parts approved</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function BeatCard({
  beat, onApprove, busy, pending,
}: { beat: ReviewBeat; onApprove: () => void; busy: boolean; pending: boolean }) {
  const approved = beat.status === "approved";
  const flagged = beat.flags.length > 0;
  const badge = approved ? "✅ Approved" : flagged ? "⚠️ Check this" : "⏳ Waiting";
  const cls = approved ? "playable" : flagged ? "failed" : "preparing";
  const body = !beat.narration ? (
    <p className="note">No text yet: <Link to="/books">prepare this chapter first</Link>.</p>
  ) : (
    <>
      {flagged && (
        <div className="callout" role="note">
          <b>Please check:</b>
          <ul className="flags">{beat.flags.map((f) => <li key={f}>{f}</li>)}</ul>
        </div>
      )}
      <p className="narration small">{beat.narration}</p>
      {beat.question && (
        <>
          <p className="question">❓ {beat.question}</p>
          <ul className="answers-list">
            {beat.cards.map((c) => (
              <li key={c.text} className={c.right ? "right" : "wrong"}>
                <span aria-hidden="true">{c.right ? "✓" : "✗"}</span>{" "}
                <span className="sr-only">{c.right ? "Right: " : "Wrong: "}</span>{c.text}
              </li>
            ))}
          </ul>
          {beat.hints.length > 0 && (
            <details className="hints">
              <summary>Hints ({beat.hints.length})</summary>
              <ol>{beat.hints.map((h) => <li key={h}>{h}</li>)}</ol>
            </details>
          )}
        </>
      )}
      {!approved && (
        <button className={flagged ? "secondary" : ""} disabled={busy} onClick={onApprove}>
          {pending ? "Approving..." : flagged ? "Approve anyway" : "Approve"}
        </button>
      )}
    </>
  );
  const head = (
    <>
      Part {beat.idx + 1}: {beat.title || "(no title)"}
      <span className={`chip-state ${cls}`}>{badge}</span>
    </>
  );
  if (approved) {
    // Approved parts fold up to one line; open them to re-read.
    return (
      <details className="card beat approved-beat">
        <summary>{head}</summary>
        {body}
      </details>
    );
  }
  return (
    <article className={`card beat${flagged ? " flagged" : ""}`}>
      <h3>{head}</h3>
      {body}
    </article>
  );
}

function ChapterFolder({
  chapter, published, defaultOpen, onlyAttention, onApprove, busy, pendingBody,
}: {
  chapter: ReviewChapter; published: boolean; defaultOpen: boolean; onlyAttention: boolean;
  onApprove: (body: ApproveBody) => void; busy: boolean; pendingBody?: ApproveBody;
}) {
  const total = chapter.beats.length;
  const approvedN = chapter.beats.filter((b) => b.status === "approved").length;
  const waiting = total - approvedN;
  const flagged = chapter.beats.filter((b) => b.flags.length && b.status !== "approved").length;
  const badge = total === 0
    ? "○ Not prepared"
    : flagged ? `⚠️ ${flagged} to check` : waiting ? `⏳ ${waiting} waiting` : "✅ All approved";
  const cls = total === 0 ? "" : flagged ? "failed" : waiting ? "preparing" : "playable";
  const shown = onlyAttention
    ? chapter.beats.filter((b) => b.status !== "approved" || b.flags.length > 0)
    : chapter.beats;
  return (
    <details className="book" open={defaultOpen || undefined}>
      <summary>
        <span className="book-title">
          {chapter.title}
          <span className={`chip-state ${cls}`}>{badge}</span>
        </span>
        {total > 0 && (
          <span className="prep">
            <span className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={approvedN}>
              <span className="fill" style={{ width: `${(approvedN / total) * 100}%` }} />
            </span>
            <span className="prep-text">{approvedN} of {total} parts approved</span>
          </span>
        )}
      </summary>
      {total === 0 && (
        <p className="note">Nothing to review yet. <Link to="/books">Prepare this chapter</Link> first.</p>
      )}
      {waiting > 0 && !published && (
        <button
          className="secondary" disabled={busy}
          onClick={() => onApprove({ chapter_idx: chapter.idx })}
        >
          {pendingBody && pendingBody.beat_idx === undefined && pendingBody.chapter_idx === chapter.idx
            ? "Approving..." : "Approve parts without a warning"}
        </button>
      )}
      {shown.map((beat) => (
        <BeatCard
          key={beat.idx} beat={beat} busy={busy}
          pending={pendingBody?.chapter_idx === chapter.idx && pendingBody.beat_idx === beat.idx}
          onApprove={() => onApprove({ chapter_idx: chapter.idx, beat_idx: beat.idx })}
        />
      ))}
      {onlyAttention && shown.length === 0 && total > 0 && (
        <p className="note">Nothing needs attention here. 🎉</p>
      )}
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
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [openAll, setOpenAll] = useState<boolean | null>(null);
  const [version, setVersion] = useState(0); // bumped so Expand/Collapse all re-applies
  const setAll = (open: boolean) => { setOpenAll(open); setVersion((v) => v + 1); };

  const beats = r?.chapters.flatMap((c) => c.beats) ?? [];
  const approvedN = beats.filter((b) => b.status === "approved").length;
  const waitingN = beats.length - approvedN;
  const flaggedN = beats.filter((b) => b.flags.length && b.status !== "approved").length;
  const stage = stageOf(r);
  const canApproveClean = waitingN - flaggedN > 0;

  return (
    <section className="review">
      <p className="lead">
        Read what the model wrote, approve it, then publish the book so children can play it.
      </p>
      {library.isSuccess && books.length === 0 && (
        <div className="empty">
          <div aria-hidden="true">📝</div>
          <p>No books to review yet. <Link to="/books">Add and prepare one</Link> first.</p>
        </div>
      )}
      {books.length > 0 && (
        <BookPicker books={books} selected={selected} onSelect={(id) => navigate(`/review/${id}`)} />
      )}
      {review.error && <p className="error" role="alert">{review.error.message}</p>}
      {review.isPending && selected !== null && <p className="note">Loading the parts...</p>}
      {r && (
        <div>
          <div className="card summary">
            <h2>
              {r.title}
              <span className={`chip-state ${STAGE_CLASS[stage.stage]}`}>{STAGE_TEXT[stage.stage]}</span>
              {!published && <span className="chip-state">Not published</span>}
            </h2>
            {beats.length > 0 && (
              <div className="prep">
                <span className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={beats.length} aria-valuenow={approvedN}>
                  <span className="fill" style={{ width: `${(approvedN / beats.length) * 100}%` }} />
                </span>
                <span className="prep-text">
                  {approvedN} of {beats.length} parts approved
                  {waitingN > 0 && ` · ${waitingN} waiting`}
                  {flaggedN > 0 && ` · ${flaggedN} with warnings`}
                </span>
              </div>
            )}
            {published ? (
              <p className="success">
                🎉 Children can play this book now. <Link to="/">Open the Play tab →</Link>
              </p>
            ) : (
              r.problems.length > 0 && (
                <>
                  <p>Before this book can be published:</p>
                  <ul className="checklist">
                    {r.problems.map((p) => <li key={p}><span aria-hidden="true">☐</span> {p}</li>)}
                  </ul>
                </>
              )
            )}
          </div>
          <div className="actionbar">
            {!published && (
              <>
                <button
                  className="secondary" disabled={busy || !canApproveClean}
                  onClick={() => approve.mutate({})}
                >
                  {approve.isPending && approve.variables?.chapter_idx === undefined
                    ? "Approving..." : "Approve every part without a warning"}
                </button>
                <button disabled={busy || r.problems.length > 0} onClick={() => publish.mutate()}>
                  {publish.isPending ? "Publishing..." : "Publish this book"}
                </button>
              </>
            )}
            <label className="toggle">
              <input
                type="checkbox" checked={onlyAttention}
                onChange={(e) => setOnlyAttention(e.target.checked)}
              />
              Only parts needing attention
            </label>
            <button className="link" onClick={() => setAll(true)}>Expand all</button>
            <button className="link" onClick={() => setAll(false)}>Collapse all</button>
          </div>
          {r.chapters.map((chapter) => (
            <ChapterFolder
              key={`${chapter.idx}-${version}`} chapter={chapter} published={published} busy={busy}
              onlyAttention={onlyAttention}
              pendingBody={approve.isPending ? approve.variables : undefined}
              defaultOpen={
                openAll ?? chapter.beats.some((b) => b.flags.length > 0 && b.status !== "approved")
              }
              onApprove={(body) => approve.mutate(body)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
