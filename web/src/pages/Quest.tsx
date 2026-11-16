import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useFlash } from "../flash";
import type { SessionView } from "../types";

const QUESTS_KEY = "storyquest.quests"; // "book:chapter" -> session id, so Play resumes a quest

function readQuests(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(QUESTS_KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function saveQuest(key: string, sessionId: string) {
  try {
    localStorage.setItem(QUESTS_KEY, JSON.stringify({ ...readQuests(), [key]: sessionId }));
  } catch {
    // storage unavailable: the quest just won't resume
  }
}

interface Exchange {
  id: number;
  q: string;
  a?: { reply: string; back: string };
}

function Chips({ items, prefix, words }: { items: string[]; prefix: string; words?: boolean }) {
  return (
    <div className={`chips${words ? " words" : ""}`}>
      {items.map((t) => <span key={t}>{prefix}{t}</span>)}
    </div>
  );
}

function Finish({ view }: { view: SessionView }) {
  const s = view.summary!;
  return (
    <section>
      <article className="card">
        <h2>Quest complete!</h2>
        <p>
          You finished "{view.chapter}" in {view.book}: {s.beats_completed} parts,{" "}
          {s.first_try} guessed right the first time, {s.questions_asked}{" "}
          question{s.questions_asked === 1 ? "" : "s"} asked.
        </p>
        <Chips items={s.vocabulary} prefix="" words />
        <Link to="/"><button>Play another story</button></Link>
      </article>
    </section>
  );
}

export default function Quest() {
  const { bookId, chapterIdx } = useParams();
  const { setError, clear } = useFlash();
  const [view, setView] = useState<SessionView | null>(null);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [questionsLeft, setQuestionsLeft] = useState(0);
  const nextId = useRef(0);

  // Resume this chapter's saved quest if it is still active, otherwise begin a new one.
  useEffect(() => {
    let cancelled = false;
    const book = Number(bookId);
    const chapter = Number(chapterIdx);
    const key = `${book}:${chapter}`;
    (async () => {
      try {
        let first: SessionView | null = null;
        const saved = readQuests()[key];
        if (saved) {
          try {
            const existing = await api.session(saved);
            if (existing.status === "active") first = existing;
          } catch {
            // the saved quest is gone: begin a new one
          }
        }
        if (!first) {
          first = await api.startSession(book, chapter);
          saveQuest(key, first.id);
        }
        if (cancelled) return;
        setView(first);
        setQuestionsLeft(first.questions_left);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [bookId, chapterIdx, setError]);

  // New part: scroll up and drop the previous part's questions.
  const beatKey = view?.progress.beat;
  useEffect(() => {
    setExchanges([]);
    window.scrollTo({ top: 0 });
  }, [beatKey]);

  if (!view) {
    return (
      <section>
        <div className="toolbar left"><Link className="link" to="/">&larr; All stories</Link></div>
      </section>
    );
  }
  if (view.status === "completed" || !view.beat) return <Finish view={view} />;

  const { beat, progress } = view;
  const tried = new Set(view.wrong_cards ?? []);

  async function choose(cardId: string) {
    if (busy) return;
    setBusy(true);
    clear();
    try {
      const next = await api.choose(view!.id, cardId);
      setView(next);
      setFeedback(next.feedback ?? "");
      setQuestionsLeft(next.questions_left);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    const id = nextId.current++;
    setBusy(true);
    clear();
    setExchanges((list) => [{ id, q: text }, ...list]);
    setQuestion("");
    try {
      const out = await api.ask(view!.id, text);
      setExchanges((list) => list.map((x) => (x.id === id ? { ...x, a: out } : x)));
      setQuestionsLeft(out.questions_left);
    } catch (e) {
      setExchanges((list) => list.filter((x) => x.id !== id));
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="toolbar left"><Link className="link" to="/">&larr; All stories</Link></div>
      <div className="progress" aria-live="polite">
        {view.chapter}: part {progress.beat} of {progress.total}
      </div>
      {feedback && <p className="feedback">{feedback}</p>}
      {view.hint && <p className="hint">Hint: {view.hint}</p>}
      <article className="card">
        <h2>{beat.title}</h2>
        <p className="narration">{beat.narration}</p>
        <Chips items={beat.clues} prefix="Clue: " />
        <Chips items={beat.vocabulary} prefix="Word: " words />
      </article>

      <div className="card choice">
        <h3>{beat.choice.prompt}</h3>
        <div className="cards">
          {beat.choice.cards.map((card) => (
            <button
              key={card.id}
              className={tried.has(card.id) ? "tried" : ""}
              disabled={busy || tried.has(card.id)}
              onClick={() => choose(card.id)}
            >
              {card.text}
            </button>
          ))}
        </div>
      </div>

      <form className="card ask" autoComplete="off" onSubmit={ask}>
        <label htmlFor="question">Ask your sidekick about the story</label>
        <div className="row">
          <input
            id="question" maxLength={300} required placeholder="Why does Shere Khan limp?"
            value={question} onChange={(e) => setQuestion(e.target.value)}
            disabled={questionsLeft <= 0}
          />
          <button type="submit" disabled={busy || questionsLeft <= 0}>Ask</button>
        </div>
        <p className="note">
          {questionsLeft > 0 ? `${questionsLeft} questions left` : "No questions left: back to the quest!"}
        </p>
        <div className="answers" aria-live="polite">
          {exchanges.map((x) => (
            <div key={x.id} style={{ display: "contents" }}>
              <div className="q">{x.q}</div>
              {x.a && (
                <div className="a">
                  {x.a.reply}
                  <span className="back">{x.a.back}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </form>
    </section>
  );
}
