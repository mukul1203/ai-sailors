"use strict";

// All text from the server goes in through textContent, never innerHTML.
const $ = (id) => document.getElementById(id);
const SAVED = "storyquest.session";
const OPEN = "storyquest.open";
const POLL_MS = 3000;
let busy = false;
let pollTimer = null;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function show(screen) {
  for (const id of ["home", "quest", "finish"]) $(id).hidden = id !== screen;
  $("home-btn").hidden = screen === "home";
  if (screen !== "home") stopPolling();
}

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

async function api(path, options) {
  const init = options ? { ...options } : {};
  if (init.body) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(init.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (e) {
    throw new Error("Cannot reach the story server. Is it running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.error ? data.error.message : "Something went wrong. Try again!";
    throw Object.assign(new Error(message), { status: response.status });
  }
  return data;
}

async function guarded(action) {
  if (busy) return;
  busy = true;
  showError("");
  try {
    await action();
  } catch (e) {
    showError(e.message);
  } finally {
    busy = false;
  }
}

// ---- library: books are folders, chapters are inside ----

function openBooks() {
  try {
    return new Set(JSON.parse(localStorage.getItem(OPEN) || "[]"));
  } catch (e) {
    return new Set();
  }
}

function rememberOpen(id, isOpen) {
  const books = openBooks();
  if (isOpen) books.add(id);
  else books.delete(id);
  localStorage.setItem(OPEN, JSON.stringify([...books]));
}

const STATE_TEXT = {
  playable: "Ready to play",
  not_prepared: "Not prepared yet",
  preparing: "Getting ready...",
  failed: "Could not prepare",
};

function chapterRow(book, chapter) {
  const row = el("li", undefined, "chapter");
  const name = el("div", undefined, "name");
  name.append(el("span", chapter.title));
  const detail = chapter.state === "playable" ? `${chapter.beats} parts` : chapter.message;
  if (detail) name.append(el("small", detail));
  row.append(name, el("span", STATE_TEXT[chapter.state], `chip-state ${chapter.state}`));

  if (chapter.state === "playable") {
    const play = el("button", "Play");
    play.addEventListener("click", () => startQuest(book.id, chapter.idx));
    row.append(play);
  } else if (chapter.state === "not_prepared" || chapter.state === "failed") {
    const label = chapter.state === "failed" ? "Try again" : "Prepare this story";
    const prepare = el("button", label, "secondary");
    prepare.addEventListener("click", () =>
      guarded(async () => {
        await api(`/api/library/${book.id}/chapters/${chapter.idx}/prepare`, { method: "POST" });
        await loadHome();
      })
    );
    row.append(prepare);
  }
  return row;
}

function bookFolder(book, open) {
  const folder = el("details", undefined, "book");
  folder.open = open;
  const title = el("summary", book.title);
  title.append(el("small", book.author ? `by ${book.author}` : ""));
  folder.append(title);
  folder.addEventListener("toggle", () => rememberOpen(String(book.id), folder.open));
  if (book.error) folder.append(el("p", book.error, "error"));
  if (book.summary) folder.append(el("p", book.summary, "about"));
  if (book.content_notes) folder.append(el("p", `Note for grown-ups: ${book.content_notes}`, "caution"));
  const list = el("ul", undefined, "chapters");
  for (const chapter of book.chapters) list.append(chapterRow(book, chapter));
  folder.append(list);
  return folder;
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

async function loadHome() {
  localStorage.removeItem(SAVED);
  show("home");
  const books = await api("/api/library");
  const open = openBooks();
  const box = $("library");
  box.replaceChildren(
    ...books.map((book) => bookFolder(book, open.has(String(book.id)) || books.length === 1))
  );
  $("empty").hidden = books.length > 0;
  stopPolling();
  const preparing = books.some((b) => b.chapters.some((c) => c.state === "preparing"));
  if (preparing) {
    pollTimer = setTimeout(() => {
      if (!busy) loadHome().catch((e) => showError(e.message));
    }, POLL_MS);
  }
}

async function startQuest(bookId, chapterIdx) {
  return guarded(async () => {
    const view = await api("/api/sessions", {
      method: "POST",
      body: { book_id: bookId, chapter_idx: chapterIdx },
    });
    localStorage.setItem(SAVED, view.id);
    render(view);
  });
}

// ---- the quest ----

function chips(node, items) {
  node.replaceChildren(...items.map((t) => el("span", t)));
}

function banner(node, text) {
  node.textContent = text || "";
  node.hidden = !text;
}

function render(view, feedback) {
  $("answers").replaceChildren();
  if (view.status === "completed") {
    localStorage.removeItem(SAVED);
    const s = view.summary;
    $("finish-text").textContent =
      `You finished "${view.chapter}" in ${view.book}: ${s.beats_completed} parts, ` +
      `${s.first_try} guessed right the first time, ` +
      `${s.questions_asked} question${s.questions_asked === 1 ? "" : "s"} asked.`;
    chips($("finish-words"), s.vocabulary);
    show("finish");
    return;
  }
  show("quest");
  const { beat, progress } = view;
  $("progress").textContent = `${view.chapter}: part ${progress.beat} of ${progress.total}`;
  banner($("feedback"), feedback);
  banner($("hint"), view.hint ? `Hint: ${view.hint}` : "");
  $("beat-title").textContent = beat.title;
  $("narration").textContent = beat.narration;
  chips($("clues"), beat.clues.map((c) => `Clue: ${c}`));
  chips($("words"), beat.vocabulary.map((w) => `Word: ${w}`));
  $("choice-prompt").textContent = beat.choice.prompt;
  const tried = new Set(view.wrong_cards || []);
  $("cards").replaceChildren(
    ...beat.choice.cards.map((card) => {
      const button = el("button", card.text, tried.has(card.id) ? "tried" : "");
      button.disabled = tried.has(card.id);
      button.addEventListener("click", () => choose(view.id, card.id));
      return button;
    })
  );
  setQuestionsLeft(view.questions_left);
  window.scrollTo({ top: 0 });
}

function setQuestionsLeft(left) {
  $("questions-left").textContent = left > 0 ? `${left} questions left` : "No questions left: back to the quest!";
  $("question").disabled = left <= 0;
  $("ask-btn").disabled = left <= 0;
}

function choose(sessionId, cardId) {
  return guarded(async () => {
    const view = await api(`/api/sessions/${sessionId}/choice`, {
      method: "POST",
      body: { card_id: cardId },
    });
    render(view, view.feedback);
  });
}

$("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("question").value.trim();
  const sessionId = localStorage.getItem(SAVED);
  if (!text || !sessionId) return;
  guarded(async () => {
    $("ask-btn").disabled = true;
    const q = el("div", text, "q");
    $("answers").prepend(q);
    $("question").value = "";
    try {
      const out = await api(`/api/sessions/${sessionId}/ask`, { method: "POST", body: { text } });
      const a = el("div", out.reply, "a");
      a.append(el("span", out.back, "back"));
      q.after(a);
      setQuestionsLeft(out.questions_left);
    } catch (e) {
      q.remove();
      throw e;
    } finally {
      $("ask-btn").disabled = false;
    }
  });
});

$("home-btn").addEventListener("click", () => guarded(loadHome));
$("again-btn").addEventListener("click", () => guarded(loadHome));
$("refresh-btn").addEventListener("click", () => guarded(loadHome));

async function start() {
  const saved = localStorage.getItem(SAVED);
  if (saved) {
    try {
      render(await api(`/api/sessions/${saved}`));
      return;
    } catch (e) {
      localStorage.removeItem(SAVED);
    }
  }
  await loadHome();
}

guarded(start);
