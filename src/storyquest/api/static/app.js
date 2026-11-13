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

const SCREENS = ["home", "quest", "finish", "books", "review"];
const TAB_OF = { home: "play", quest: "play", finish: "play", books: "books", review: "review" };
let current = "";

function show(screen) {
  for (const id of SCREENS) $(id).hidden = id !== screen;
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === TAB_OF[screen]);
  }
  if (screen !== "books") stopPolling();
  if (screen !== current) showNotice("");
  current = screen;
}

function showNotice(message) {
  $("notice").textContent = message || "";
  $("notice").hidden = !message;
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

function chapterRow(book, chapter, grownUp) {
  const row = el("li", undefined, "chapter");
  const name = el("div", undefined, "name");
  name.append(el("span", chapter.title));
  const detail = chapter.state === "playable" ? `${chapter.beats} parts` : chapter.message;
  if (detail) name.append(el("small", detail));
  row.append(name);
  if (grownUp) row.append(el("span", STATE_TEXT[chapter.state], `chip-state ${chapter.state}`));

  if (chapter.state === "playable" && !grownUp) {
    const play = el("button", "Play");
    play.addEventListener("click", () => startQuest(book.id, chapter.idx));
    row.append(play);
  } else if (grownUp && (chapter.state === "not_prepared" || chapter.state === "failed")) {
    const label = chapter.state === "failed" ? "Try again" : "Prepare this story";
    const prepare = el("button", label, "secondary");
    prepare.addEventListener("click", () =>
      guarded(async () => {
        await queuePrepare(book.id, [chapter.idx]);
        await loadBooks();
      })
    );
    row.append(prepare);
  }
  return row;
}

function queuePrepare(bookId, chapterIdxs) {
  return Promise.all(
    chapterIdxs.map((idx) =>
      api(`/api/library/${bookId}/chapters/${idx}/prepare`, { method: "POST" })
    )
  );
}

function bookFolder(book, open, grownUp) {
  const folder = el("details", undefined, "book");
  folder.open = open;
  const title = el("summary", book.title);
  title.append(el("small", book.author ? `by ${book.author}` : ""));
  if (grownUp && book.id !== null) {
    const published = book.status === "ready";
    title.append(
      el("span", published ? "Published" : "Not published", `chip-state ${published ? "playable" : ""}`)
    );
  }
  folder.append(title);
  folder.addEventListener("toggle", () => rememberOpen(String(book.id), folder.open));
  if (book.error) folder.append(el("p", book.error, "error"));
  if (book.summary) folder.append(el("p", book.summary, "about"));
  if (book.content_notes) folder.append(el("p", `Note for grown-ups: ${book.content_notes}`, "caution"));
  const list = el("ul", undefined, "chapters");
  for (const chapter of book.chapters) list.append(chapterRow(book, chapter, grownUp));
  folder.append(list);
  const todo = book.chapters.filter((c) => c.state === "not_prepared" || c.state === "failed");
  if (grownUp && todo.length > 1) {
    const all = el("button", `Prepare all ${todo.length} chapters`, "secondary");
    all.addEventListener("click", () =>
      guarded(async () => {
        await queuePrepare(book.id, todo.map((c) => c.idx));
        await loadBooks();
      })
    );
    folder.append(all);
  }
  return folder;
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

// ---- play tab: only chapters a child may play ----

async function loadHome() {
  localStorage.removeItem(SAVED);
  show("home");
  const missions = await api("/api/missions");
  const byBook = new Map();
  for (const m of missions) {
    if (!byBook.has(m.book_id)) {
      byBook.set(m.book_id, { id: m.book_id, title: m.book, author: "", chapters: [] });
    }
    byBook.get(m.book_id).chapters.push({
      idx: m.chapter_idx,
      title: m.chapter,
      state: "playable",
      beats: m.beats,
    });
  }
  const books = [...byBook.values()];
  const open = openBooks();
  $("library").replaceChildren(
    ...books.map((book) => bookFolder(book, open.has(String(book.id)) || books.length === 1, false))
  );
  $("empty").hidden = books.length > 0;
}

// ---- books tab: add a book, prepare its chapters ----

async function loadBooks() {
  show("books");
  const books = await api("/api/library");
  const open = openBooks();
  $("books-list").replaceChildren(
    ...books.map((book) => bookFolder(book, open.has(String(book.id)) || books.length === 1, true))
  );
  $("books-empty").hidden = books.length > 0;
  stopPolling();
  const preparing = books.some((b) => b.chapters.some((c) => c.state === "preparing"));
  if (preparing) {
    pollTimer = setTimeout(() => {
      if (!busy && !$("books").hidden) loadBooks().catch((e) => showError(e.message));
    }, POLL_MS);
  }
}

$("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const file = $("add-file").files[0];
    if (!file) return;
    const out = await api("/api/admin/books", {
      method: "POST",
      body: {
        gutenberg_id: Number($("add-id").value),
        title: $("add-title").value.trim(),
        author: $("add-author").value.trim(),
        summary: $("add-summary").value.trim(),
        content_notes: $("add-notes").value.trim(),
        text: await file.text(),
      },
    });
    $("add-form").reset();
    $("add-form").closest("details").open = false;
    await loadBooks();
    showNotice(`Added "${out.title}". Prepare its chapters below, then review it.`);
  });
});

// ---- review tab: read, approve, publish ----

async function loadReview() {
  show("review");
  const books = (await api("/api/library")).filter((b) => b.id !== null);
  const select = $("review-book");
  const keep = select.value;
  select.replaceChildren(
    ...books.map((b) => {
      const option = el("option", b.status === "ready" ? `${b.title} (published)` : b.title);
      option.value = String(b.id);
      return option;
    })
  );
  $("review-empty").hidden = books.length > 0;
  $("review-body").replaceChildren();
  $("review-body").dataset.shown = "";
  if (!books.length) return;
  if ([...select.options].some((o) => o.value === keep)) select.value = keep;
  await renderReview(Number(select.value));
}

function approve(bookId, body) {
  return guarded(async () => {
    const out = await api(`/api/admin/books/${bookId}/approve`, { method: "POST", body });
    await renderReview(bookId);
    let text = `${out.approved} approved.`;
    if (out.flagged_left) text += ` ${out.flagged_left} with warnings are left: read them and approve one by one.`;
    if (out.empty_left) text += ` ${out.empty_left} have no text yet: prepare the chapter first.`;
    showNotice(text);
  });
}

function publishBook(bookId) {
  return guarded(async () => {
    const out = await api(`/api/admin/books/${bookId}/publish`, { method: "POST" });
    await renderReview(bookId);
    showNotice(
      out.published
        ? "Published! Children can now play it from the Play tab."
        : `Not published yet: ${out.problems.join("; ")}`
    );
  });
}

function beatCard(bookId, chapterIdx, beat) {
  const card = el("article", undefined, `card beat ${beat.flags.length ? "flagged" : ""}`);
  const head = el("h3", `Part ${beat.idx + 1}: ${beat.title || "(no title)"}`);
  head.append(el("span", beat.status, `chip-state ${beat.status === "approved" ? "playable" : ""}`));
  card.append(head);
  if (!beat.narration) {
    card.append(el("p", "No text yet: prepare this chapter first.", "note"));
    return card;
  }
  if (beat.flags.length) {
    const flags = el("ul", undefined, "flags");
    for (const f of beat.flags) flags.append(el("li", f));
    card.append(flags);
  }
  card.append(el("p", beat.narration, "narration small"));
  if (beat.question) {
    card.append(el("p", beat.question, "question"));
    const cards = el("ul", undefined, "answers-list");
    for (const c of beat.cards) cards.append(el("li", `${c.right ? "Right: " : "Wrong: "}${c.text}`, c.right ? "right" : ""));
    card.append(cards);
    if (beat.hints.length) card.append(el("p", `Hints: ${beat.hints.join(" / ")}`, "note"));
  }
  if (beat.status !== "approved") {
    const ok = el("button", beat.flags.length ? "Approve despite the warning" : "Approve", "secondary");
    ok.addEventListener("click", () => approve(bookId, { chapter_idx: chapterIdx, beat_idx: beat.idx }));
    card.append(ok);
  }
  return card;
}

async function renderReview(bookId) {
  const r = await api(`/api/admin/books/${bookId}/review`);
  const body = $("review-body");
  const wasOpen = new Set([...body.querySelectorAll("details[open]")].map((d) => d.dataset.chapter));
  const first = !body.dataset.shown;
  const published = r.status === "ready";

  const top = el("div", undefined, "card");
  const title = el("h2", r.title);
  title.append(el("span", published ? "Published" : "Not published", `chip-state ${published ? "playable" : ""}`));
  top.append(title);
  if (!published) {
    if (r.problems.length) {
      top.append(el("p", "Before this book can be published:"));
      const list = el("ul", undefined, "problems");
      for (const p of r.problems) list.append(el("li", p));
      top.append(list);
    }
    const actions = el("div", undefined, "actions");
    const all = el("button", "Approve every part without a warning", "secondary");
    all.addEventListener("click", () => approve(bookId, {}));
    const publish = el("button", "Publish this book");
    publish.disabled = r.problems.length > 0;
    publish.addEventListener("click", () => publishBook(bookId));
    actions.append(all, publish);
    top.append(actions);
  }

  const chapters = r.chapters.map((chapter) => {
    const waiting = chapter.beats.filter((b) => b.status !== "approved").length;
    const flagged = chapter.beats.filter((b) => b.flags.length && b.status !== "approved").length;
    const details = el("details", undefined, "book");
    details.dataset.chapter = String(chapter.idx);
    details.open = wasOpen.has(String(chapter.idx)) || (first && flagged > 0);
    const summary = el("summary", chapter.title);
    summary.append(
      el("small", chapter.beats.length
        ? `${chapter.beats.length} parts, ${waiting} waiting for approval, ${flagged} with warnings`
        : "Not prepared yet")
    );
    details.append(summary);
    if (waiting > 0 && !published) {
      const some = el("button", "Approve parts without a warning", "secondary");
      some.addEventListener("click", () => approve(bookId, { chapter_idx: chapter.idx }));
      details.append(some);
    }
    for (const beat of chapter.beats) details.append(beatCard(bookId, chapter.idx, beat));
    return details;
  });
  body.dataset.shown = "1";
  body.replaceChildren(top, ...chapters);
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

$("again-btn").addEventListener("click", () => guarded(loadHome));
$("books-refresh").addEventListener("click", () => guarded(loadBooks));
$("review-book").addEventListener("change", () =>
  guarded(async () => {
    $("review-body").dataset.shown = "";
    await renderReview(Number($("review-book").value));
  })
);

const OPEN_TAB = { play: () => start(), books: loadBooks, review: loadReview };
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => guarded(OPEN_TAB[tab.dataset.tab]));
}

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
