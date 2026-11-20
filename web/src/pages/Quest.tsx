import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useFlash } from "../flash";
import { readQuests, saveQuest } from "../quests";
import type { SessionView } from "../types";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

// "Read to me": the browser's built-in speech, no extra library.
function ReadAloud({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;
  useEffect(() => () => { if (supported) window.speechSynthesis.cancel(); }, [supported, text]);
  if (!supported) return null;
  function toggle() {
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.9;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    setSpeaking(true);
  }
  return (
    <button
      type="button" className="read" onClick={toggle}
      aria-label={speaking ? "Stop reading" : "Read to me"} title={speaking ? "Stop" : "Read to me"}
    >
      <svg viewBox="0 0 24 24" width="1.3em" height="1.3em" fill="currentColor" aria-hidden="true">
        {speaking ? (
          <rect x="6" y="6" width="12" height="12" rx="2" />
        ) : (
          <path d="M3 9v6h4l5 4V5L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z" />
        )}
      </svg>
    </button>
  );
}

const HINT_WORDS = 10;

// The first 10 words of the hint; "Show more" opens the rest (only offered for longer hints).
function Hint({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const words = text.split(/\s+/).filter(Boolean);
  const long = words.length > HINT_WORDS;
  const shown = open || !long ? text : `${words.slice(0, HINT_WORDS).join(" ")}…`;
  return (
    <p className="hint">
      <span className="hint-text">🧭 Hint: {shown}</span>
      {long && (
        <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </p>
  );
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
    <section className="kid">
      <article className="card finish">
        <div className="trophy" aria-hidden="true">🏆</div>
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
      <section className="kid">
        <div className="toolbar left"><Link className="link" to="/">&larr; All stories</Link></div>
        <p className="lead">📖 Opening your story...</p>
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

  function ask(event: FormEvent) {
    event.preventDefault();
    void submitQuestion(question);
  }

  async function submitQuestion(raw: string) {
    const text = raw.trim();
    if (!text || busy || questionsLeft <= 0) return;
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

  const suggestions = [
    ...beat.vocabulary.slice(0, 2).map((w) => `What does "${w}" mean?`),
    "Why did that happen?",
  ];

  return (
    <section className="kid">
      <div className="toolbar left"><Link className="link" to="/">&larr; All stories</Link></div>
      <div className="progress" aria-live="polite">
        <span>{view.chapter}: part {progress.beat} of {progress.total}</span>
        <div
          className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={progress.total}
          aria-valuenow={progress.beat}
        >
          <div className="fill" style={{ width: `${(progress.beat / progress.total) * 100}%` }} />
        </div>
      </div>
      <div className="quest-grid">
        <div className="quest-story">
        <article className="card story" key={progress.beat}>
          <div className="story-head">
            <h2>{beat.title}</h2>
            <ReadAloud text={`${beat.title}. ${beat.narration}`} />
          </div>
          <p className="narration">{beat.narration}</p>
          <Chips items={beat.clues} prefix="🔍 " />
          <Chips items={beat.vocabulary} prefix="📖 " words />
        </article>
        </div>
        <div className="quest-side">
        <div className="card choice">
          <h3>🤔 {beat.choice.prompt}</h3>
          {view.hint && <Hint key={view.hint} text={view.hint} />}
          <div className="cards">
            {beat.choice.cards.map((card, i) => (
              <button
                key={card.id}
                className={`choice-btn c${i % 4}${tried.has(card.id) ? " tried" : ""}`}
                disabled={busy || tried.has(card.id)}
                onClick={() => choose(card.id)}
              >
                <span className="letter" aria-hidden="true">{LETTERS[i] ?? i + 1}</span>
                {card.text}
              </button>
            ))}
          </div>
          {feedback && <p className="feedback" key={feedback}>💡 {feedback}</p>}
        </div>

        <form className="card ask" autoComplete="off" onSubmit={ask}>
          <label htmlFor="question"><span className="avatar" aria-hidden="true">🐘</span> Ask Dumbo about the story</label>
          {questionsLeft > 0 && (
            <div className="suggest">
              {suggestions.map((s, i) => (
                <span key={s}>
                  <button type="button" disabled={busy} onClick={() => void submitQuestion(s)}>{s}</button>
                  {i < suggestions.length - 1 && ", "}
                </span>
              ))}
            </div>
          )}
          <div className="row">
            <input
              id="question" maxLength={300} required placeholder="Why does Shere Khan limp?"
              value={question} onChange={(e) => setQuestion(e.target.value)}
              disabled={questionsLeft <= 0}
            />
            <button type="submit" disabled={busy || questionsLeft <= 0}>Ask</button>
          </div>
          <p className="note">
            {questionsLeft > 0
              ? <>Questions left: <span aria-label={`${questionsLeft} left`}>{"💛".repeat(questionsLeft)}</span></>
              : "No questions left: back to the quest!"}
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
        </div>
      </div>
    </section>
  );
}
