"use strict";

// All text from the server goes in through textContent, never innerHTML.
const $ = (id) => document.getElementById(id);
const SAVED = "storyquest.session";
let busy = false;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function show(screen) {
  for (const id of ["home", "quest", "finish"]) $(id).hidden = id !== screen;
  $("home-btn").hidden = screen === "home";
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

async function loadHome() {
  localStorage.removeItem(SAVED);
  show("home");
  const missions = await api("/api/missions");
  const box = $("missions");
  box.replaceChildren();
  $("empty").hidden = missions.length > 0;
  for (const m of missions) {
    const button = el("button", `${m.book}: ${m.chapter}`);
    button.append(el("small", `${m.beats} parts`));
    button.addEventListener("click", () =>
      guarded(async () => {
        const view = await api("/api/sessions", {
          method: "POST",
          body: { book_id: m.book_id, chapter_idx: m.chapter_idx },
        });
        localStorage.setItem(SAVED, view.id);
        render(view);
      })
    );
    box.append(button);
  }
}

function chips(node, items) {
  node.replaceChildren(...items.map((t) => el("span", t)));
}

function render(view, feedback) {
  $("answers").replaceChildren();
  if (view.status === "completed") {
    localStorage.removeItem(SAVED);
    const s = view.summary;
    $("finish-text").textContent =
      `You finished "${view.chapter}" in ${view.book}: ${s.beats_completed} parts, ` +
      `${s.questions_asked} question${s.questions_asked === 1 ? "" : "s"} asked.`;
    chips($("finish-words"), s.vocabulary);
    show("finish");
    return;
  }
  show("quest");
  const { beat, progress } = view;
  $("progress").textContent = `${view.chapter}: part ${progress.beat} of ${progress.total}`;
  $("feedback").textContent = feedback || "";
  $("feedback").hidden = !feedback;
  $("beat-title").textContent = beat.title;
  $("narration").textContent = beat.narration;
  chips($("clues"), beat.clues.map((c) => `Clue: ${c}`));
  chips($("words"), beat.vocabulary.map((w) => `Word: ${w}`));
  $("choice-prompt").textContent = beat.choice.prompt;
  $("cards").replaceChildren(
    ...beat.choice.cards.map((card) => {
      const button = el("button", card.text);
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
