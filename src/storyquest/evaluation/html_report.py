"""One self-contained HTML page that explains the evaluation and compares the modes that were run."""

from collections import Counter
from html import escape
from statistics import mean

from storyquest.agent.modes import MODES, describe_steps
from storyquest.evaluation.glossary import (
    BEHAVIOUR,
    CATEGORY_MEANING,
    FAILURE_CAUSES,
    LEGEND,
    Row,
    category_name,
    explain,
    explain_flag,
    pct,
    where,
)
from storyquest.evaluation.runner import (
    CATEGORY_ORDER,
    fact_evidence_counts,
    faithfulness_counts,
    mean_precision,
    pass_rates,
)

Run = tuple[Row, list[Row]]

_CSS = """
body{font:15px/1.55 -apple-system,Segoe UI,sans-serif;margin:2rem auto;max-width:1300px;color:#222;padding:0 1.2rem}
h1{margin:0 0 .2rem}h2{margin:2.4rem 0 .6rem;border-bottom:2px solid #ddd;padding-bottom:.2rem}h3{margin:.2rem 0}
.sub{color:#666;font-size:13px}.note{background:#f3f7fb;border-left:4px solid #6a9bd1;padding:.6rem 1rem;margin:1rem 0}
nav a{margin-right:1rem}.cols{display:flex;flex-wrap:wrap;gap:1rem}.col{flex:1 1 280px;border:1px solid #ddd;border-radius:8px;padding:.6rem 1rem}
table{border-collapse:collapse;width:100%}td,th{padding:.3rem .5rem;text-align:left;border-bottom:1px solid #eee;vertical-align:top}
th{background:#fafafa}.num{white-space:nowrap}.bar{background:#eee;border-radius:4px;height:8px;width:100px;display:inline-block}
.bar i{display:block;height:8px;border-radius:4px;background:#3a8}.ok{color:#1d7a46}.bad{color:#b33}.dim{color:#888}
details{border:1px solid #e3e3e3;border-radius:6px;margin:.5rem 0;padding:.3rem .8rem}summary{cursor:pointer}
pre{white-space:pre-wrap;background:#f6f6f6;padding:.5rem;border-radius:4px;margin:.3rem 0;font:13px/1.45 ui-monospace,Menlo,monospace}
.panel{flex:1 1 300px;border:1px solid #ddd;border-top:5px solid #ccc;border-radius:6px;padding:.5rem .9rem;min-width:300px}
.panel.pass{border-top-color:#2a9d5c}.panel.fail{border-top-color:#d6453d}
.badge{font-size:12px;font-weight:700;border-radius:4px;padding:1px 8px;color:#fff}.badge.pass{background:#2a9d5c}.badge.fail{background:#d6453d}
.tag{font-size:12px;border-radius:4px;padding:0 .4rem;background:#fde;color:#a22;margin-left:.3rem}
.lbl{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#777;margin-top:.7rem}.why{margin:.4rem 0}
.passage{border-left:3px solid #ccc;padding-left:.6rem;margin:.5rem 0}.passage.gold{border-left-color:#2a9d5c}
.pmeta{font-size:12px;color:#555}ol.steps{padding-left:1.2rem;margin:.3rem 0}ol.steps li{margin:.25rem 0}
.differs{background:#fff4d6;color:#7a5b00;border-radius:4px;padding:0 .4rem;font-size:12px;margin-left:.4rem}
"""


def _bar(a: int, b: int) -> str:
    width = round(100 * a / b) if b else 0
    return f'<span class="bar"><i style="width:{width}%"></i></span>'


def _rate(p: int, n: int) -> str:
    return f"{p}/{n} ({round(100 * p / n)}%)" if n else "n/a"


def _mode_info(config: Row) -> tuple[str, list[str]]:
    mode = MODES.get(config["mode"])
    if mode is None:
        return config["mode"], []
    return mode.title, describe_steps(mode, int(config["retrieval_top_k"]))


def _modes_section(runs: list[Run]) -> str:
    cards = []
    for config, _ in runs:
        title, steps = _mode_info(config)
        items = "".join(f"<li>{escape(s)}</li>" for s in steps)
        cards.append(
            f"<div class='col'><h3>{escape(config['mode'])} &mdash; {escape(title)}</h3>"
            f"<ol class='steps'>{items}</ol></div>"
        )
    return (
        "<h2 id='modes'>1. The modes compared</h2><p>Each mode is a different way of building the "
        "agent. They all start the same way; the steps after that are what differ.</p>"
        f"<div class='cols'>{''.join(cards)}</div>"
    )


def _summary_section(runs: list[Run]) -> str:
    head = "".join(f"<th>{escape(c['mode'])}</th>" for c, _ in runs)
    rows = [f"<tr><th>Measure</th>{head}</tr>"]

    def line(label: str, cells: list[str], hint: str = "") -> None:
        sub = f"<div class='sub'>{escape(hint)}</div>" if hint else ""
        body = "".join(f"<td class='num'>{c}</td>" for c in cells)
        rows.append(f"<tr><td>{label}{sub}</td>{body}</tr>")

    cells = []
    for _, rs in runs:
        ran = [r for r in rs if not r["skipped"]]
        p = sum(bool(r["passed"]) for r in ran)
        cells.append(f"<b>{_rate(p, len(ran))}</b> {_bar(p, len(ran))}")
    line("<b>Overall pass rate</b>", cells, "Questions where the agent did the right thing")

    cats = [c for c in CATEGORY_ORDER if any(r["category"] == c for _, rs in runs for r in rs)]
    for cat in cats:
        cells = []
        for _, rs in runs:
            p, n = pass_rates(rs).get(cat, (0, 0))
            cells.append(f"{_rate(p, n)} {_bar(p, n)}")
        line(
            f"{escape(category_name(cat))} <span class='dim'>({cat})</span>",
            cells,
            CATEGORY_MEANING.get(cat, ""),
        )

    cells = []
    for config, rs in runs:
        ran = [r for r in rs if not r["skipped"]]
        gold = [r for r in ran if r["retrieval_hit"] is not None]
        mode = MODES.get(config["mode"])
        if mode is not None and not mode.retrieval:
            cells.append("<span class='dim'>no search</span>")
        else:
            cells.append(_rate(sum(bool(r["retrieval_hit"]) for r in gold), len(gold)))
    line("Search found the answer passage", cells, "Of questions with a marked answer passage")

    cells = []
    for config, rs in runs:
        mode = MODES.get(config["mode"])
        if mode is not None and not mode.retrieval:
            cells.append("<span class='dim'>no search</span>")
            continue
        found, total = fact_evidence_counts(rs)
        cells.append(_rate(found, total))
    line(
        "Search found each fact's evidence",
        cells,
        "Of the expected facts that have marked evidence lines (a fact can sit in a different passage)",
    )

    cells = []
    for _, rs in runs:
        cov = [
            r["fact_coverage"] for r in rs if not r["skipped"] and r["fact_coverage"] is not None
        ]
        cells.append(pct(mean(cov)) if cov else "n/a")
    line("Recall: required facts stated (average)", cells, "Answer questions only")

    cells = []
    for config, rs in runs:
        mode = MODES.get(config["mode"])
        if mode is not None and not mode.retrieval:
            cells.append("<span class='dim'>no passages</span>")
            continue
        ok, analysed = faithfulness_counts(rs)
        cells.append(_rate(ok, analysed))
    line(
        "<b>Faithful:</b> replies fully supported by their passages",
        cells,
        "Every claim must be supported by the passages the model was given (100% required)",
    )

    cells = []
    for _, rs in runs:
        precision = mean_precision(rs)
        cells.append(pct(precision) if precision is not None else "n/a")
    line(
        "Precision (average)",
        cells,
        "Share of the reply's claims that state an expected fact. Reported, not required",
    )

    cells = []
    for _, rs in runs:
        ran = [r for r in rs if not r["skipped"]]
        cells.append(f"{mean(r['calls'] for r in ran):.1f}" if ran else "n/a")
    line("Model calls per question", cells)
    cells = []
    for _, rs in runs:
        ran = [r for r in rs if not r["skipped"]]
        cells.append(f"{mean(r['latency_s'] for r in ran):.1f}s" if ran else "n/a")
    line("Time per question", cells)

    counts = [
        Counter(r["label"] for r in rs if not r["skipped"] and not r["passed"]) for _, rs in runs
    ]
    causes = sorted({k for c in counts for k in c}, key=lambda k: -sum(c[k] for c in counts))
    cause_rows = [f"<tr><th>Why items failed</th>{head}</tr>"]
    for k in causes:
        meaning = escape(FAILURE_CAUSES.get(str(k), ""))
        cells_html = "".join(f"<td class='num'>{c[k] or '&ndash;'}</td>" for c in counts)
        cause_rows.append(
            f"<tr><td><b>{escape(str(k))}</b><div class='sub'>{meaning}</div></td>{cells_html}</tr>"
        )
    return (
        "<h2 id='summary'>2. Results at a glance</h2>"
        f"<table>{''.join(rows)}</table><br><table>{''.join(cause_rows)}</table>"
    )


def _legend_section() -> str:
    rows = "".join(
        f"<tr><td class='num'><b>{escape(t)}</b></td><td>{escape(m)}</td></tr>" for t, m in LEGEND
    )
    return f"<h2 id='legend'>3. Legend: what the terms mean</h2><table>{rows}</table>"


def _judge_html(r: Row) -> str:
    if r.get("judge_error"):
        return (
            "<div class='lbl'>Judge</div><p class='bad'>The judge's answer could not be read "
            f"({escape(r['judge_error'])}), so facts fall back to the keyword check.</p>"
        )
    j = r.get("judge")
    if not j:
        cov = r.get("fact_coverage")
        if cov is None:
            return ""
        return f"<div class='lbl'>Required facts</div><p>Keyword check only (no judge): {pct(cov)} stated.</p>"
    out = ["<div class='lbl'>Required facts, as judged</div><ul>"]
    for d in j.get("fact_details", []):
        quote = f"&ldquo;{escape(d['quote'])}&rdquo;" if d.get("quote") else ""
        if d["stated"]:
            mark = "<span class='ok'>&#10003; stated</span>"
            why = f" &mdash; judge pointed at <i>{quote}</i> in the reply"
        elif d.get("judge_said_yes") and not d.get("quote_ok"):
            mark = "<span class='bad'>&#10007; not counted</span>"
            why = (
                f" &mdash; the judge said yes, but the words it pointed at (<i>{quote}</i>) are not in "
                "the reply (fewer than 80% of them match), so the check counted it as no"
            )
        else:
            mark = "<span class='bad'>&#10007; not stated</span>"
            why = " &mdash; the judge said the reply does not say this"
        out.append(f"<li>{mark}: {escape(d['fact'])}{why}</li>")
    out.append("</ul>")
    out.append(_claims_html(r, j))
    if j.get("forbidden_found"):
        out.append(
            f"<p class='bad'>Forbidden content found: {escape('; '.join(j['forbidden_found']))}</p>"
        )
    out.append(_judge_steps_html(j))
    return "".join(out)


def _claims_html(r: Row, j: Row) -> str:
    claims = j.get("claims")
    head = "<div class='lbl'>Claims in the reply, checked against the passages</div>"
    if claims is None:
        return (
            head
            + "<p class='dim'>Not analysed: the model had no passages, or the judge's answer could not be read.</p>"
        )
    if not claims:
        return head + "<p>The reply makes no factual claims, so there is nothing to check.</p>"
    facts = r.get("must_include", [])
    body = []
    for c in claims:
        quote = f"&ldquo;{escape(c['quote'])}&rdquo;" if c.get("quote") else ""
        if c["supported"] and c.get("inferred"):
            sup = f"<span class='ok'>&#10003; inferred</span>, not stated outright: follows from <i>{quote}</i>"
        elif c["supported"]:
            sup = f"<span class='ok'>&#10003; supported</span> by <i>{quote}</i>"
        elif c.get("judge_said_yes") and not c.get("quote_ok"):
            sup = f"<span class='bad'>&#10007; not counted</span>: the judge said yes, but <i>{quote}</i> is not in the passages"
        else:
            sup = "<span class='bad'>&#10007; not supported</span>: no passage says this"
        n = c.get("fact") or 0
        if n and n <= len(facts):
            fact = f"states an expected fact (judge's pick: {n}. {escape(facts[n - 1])})"
        else:
            fact = "<span class='dim'>extra: not one of the expected facts</span>" if facts else ""
        body.append(f"<tr><td>{escape(c['text'])}</td><td>{sup}</td><td>{fact}</td></tr>")
    ok = sum(c["supported"] for c in claims)
    inferred = sum(bool(c.get("inferred")) for c in claims)
    verdict = "ok" if ok == len(claims) else "bad"
    summary = f"<p class='{verdict}'><b>Faithfulness: {ok} of {len(claims)} claims supported</b> (all are required)"
    if inferred:
        summary += f" ({inferred} inferred, please check)"
    if r.get("precision") is not None:
        summary += (
            f" &middot; Precision: {pct(r['precision'])} of the claims state an expected fact"
        )
    return (
        head
        + summary
        + "</p><table><tr><th>Claim</th><th>Supported by the passages?</th><th>Expected fact?</th></tr>"
        + "".join(body)
        + "</table>"
    )


def _judge_steps_html(j: Row) -> str:
    if not j.get("prompt") and not j.get("claims_prompt"):
        return ""
    parts = [
        "<details><summary>How the judge decided (what it received and what it answered)</summary>"
        "<ol class='steps'>"
        "<li><b>Recall.</b> The judge gets the question, the reply and the required facts. For each fact it copies the "
        "words from the reply that say it, then answers true or false. Paraphrases count. Code checks that at least "
        "80% of the copied words occur in the reply, otherwise the answer becomes false.</li>"
        "<li><b>Claims.</b> A second call splits the reply into separate factual claims.</li>"
        "<li><b>Faithfulness and precision.</b> A third call gets the passages the model was given, the claims and "
        "the required facts. For each claim it copies the supporting words from the passages (code checks they are "
        "there), says whether the passages support it or it follows from them in one obvious step (inferred), and which "
        "required fact it states, if any. Faithfulness is the share of supported or inferred claims and must be 100%. Precision is the share of claims that state a required "
        "fact.</li></ol>"
    ]
    for title, key in (
        ("Recall prompt", "prompt"),
        ("Recall raw answer", "raw"),
        ("Claims prompt", "claims_prompt"),
        ("Claims raw answer", "claims_raw"),
        ("Faithfulness prompt", "verify_prompt"),
        ("Faithfulness raw answer", "verify_raw"),
    ):
        if j.get(key):
            parts.append(f"<div class='lbl'>{title}</div><pre>{escape(j[key])}</pre>")
    return "".join(parts) + "</details>"


def _ranking(p: Row) -> str:
    """How a passage was found: BM25 score, or the keyword and meaning ranks in hybrid modes."""
    if p.get("source") == "entity":
        return "entity card: a short description made from the book during ingestion"
    kw, dense = p.get("bm25_rank"), p.get("dense_rank")
    if kw is None and dense is None:
        return f"BM25 score {p['score']}"
    found = [
        f"keywords #{kw}" if kw else "not in the keyword results",
        f"meaning #{dense}" if dense else "not in the meaning results",
    ]
    return "ranked by " + ", ".join(found) + f" (fused score {p['score']:.4f})"


def _passages_html(r: Row, retrieves: bool) -> str:
    if not retrieves:
        return (
            "<div class='lbl'>Passages</div><p class='dim'>This mode does not search the book.</p>"
        )
    ps = r.get("passages", [])
    if not ps:
        return "<div class='lbl'>Passages</div><p class='dim'>None were retrieved.</p>"
    blocks = []
    for n, p in enumerate(ps, 1):
        gold = bool(p.get("has_gold"))
        tick = (
            " &mdash; <span class='ok'>&#10003; contains the answer passage</span>" if gold else ""
        )
        text = escape(p.get("text") or "(text not saved in this older run)")
        blocks.append(
            f"<div class='passage{' gold' if gold else ''}'><div class='pmeta'>Passage {n} &middot; "
            f"chapter {p['chapter'] + 1}, part B{p['beat'] + 1} &middot; {_ranking(p)}{tick}</div><pre>{text}</pre></div>"
        )
    opened = "" if r["passed"] else " open"
    return f"<details{opened}><summary>Passages retrieved ({len(ps)}), click to read</summary>{''.join(blocks)}</details>"


def _steps_html(r: Row, retrieves: bool, grounded: bool) -> str:
    route = r["route"]
    steps = []
    if route in ("empty", "too_long"):
        steps.append(
            f"Guard: the message was {route.replace('_', ' ')}, so a fixed reply was sent. No model was used."
        )
    elif route == "error":
        steps.append("A model call failed, so a gentle error reply was sent.")
    elif route != "story_question":
        steps.append(
            f"Router: labelled the message <b>{escape(route)}</b>, so a fixed reply was sent and nothing else ran."
        )
    else:
        steps.append(
            "Router: labelled the message <b>story_question</b>, so the agent went on to answer."
        )
        if retrieves:
            n = len(r.get("passages", []))
            hit = r.get("retrieval_hit")
            found = {
                True: "The passage with the answer is among them.",
                False: "The passage with the answer is <b>not</b> among them.",
                None: "No answer passage is marked for this question.",
            }[hit]
            steps.append(
                f"Search: found {n} passage(s) (listed below). {found}"
                if n
                else "Search: nothing matched, so no answer was written."
            )
            found_facts = r.get("fact_found")
            if n and found_facts:
                missing = [r["must_include"][i] for i, ok in enumerate(found_facts) if not ok]
                steps.append(
                    f"Expected facts whose evidence is among the passages: "
                    f"<b>{sum(found_facts)} of {len(found_facts)}</b>"
                    + (f". Not found: {escape('; '.join(missing))}" if missing else "")
                )
        else:
            steps.append("Answer: written from the model's own memory of the book.")
        if grounded and r.get("passages"):
            ev = r.get("evidence")
            steps.append(
                f"Evidence the model pointed at: <i>&ldquo;{escape(ev)}&rdquo;</i>"
                if ev
                else "Evidence: the model gave none that could be used."
            )
    flags = [explain_flag(f) for f in r.get("flags", [])]
    steps.append("Checks: " + escape("; ".join(flags)) if flags else "Checks: nothing to report.")
    return (
        "<div class='lbl'>How the agent got here</div><ol class='steps'>"
        + "".join(f"<li>{s}</li>" for s in steps)
        + "</ol>"
    )


def _panel(config: Row, r: Row | None) -> str:
    mode = MODES.get(config["mode"])
    retrieves = bool(mode and mode.retrieval)
    grounded = bool(mode and mode.grounded)
    name = escape(config["mode"])
    if r is None or r["skipped"]:
        return f"<div class='panel'><b>{name}</b><p class='dim'>Not run.</p></div>"
    cls, word = ("pass", "PASS") if r["passed"] else ("fail", "FAIL")
    tag = "" if r["passed"] else f"<span class='tag'>{escape(str(r['label']))}</span>"
    why = escape(explain(r, int(config["retrieval_top_k"])))
    return (
        f"<div class='panel {cls}'><b>{name}</b> <span class='badge {cls}'>{word}</span>{tag}"
        f"<p class='why'>{why}</p><div class='lbl'>Reply</div><pre>{escape(r['reply'])}</pre>"
        f"{_steps_html(r, retrieves, grounded)}{_passages_html(r, retrieves)}{_judge_html(r)}"
        f"<div class='sub'>{r['calls']} model call(s), {r['prompt_tokens']}+{r['completion_tokens']} tokens, {r['latency_s']}s</div></div>"
    )


def _fact_source(r: Row, i: int) -> str:
    """Where in the book an expected fact comes from, when the golden set says so."""
    evidence = r.get("fact_evidence") or []
    if i >= len(evidence):
        return ""
    e = evidence[i]
    return (
        f" <span class='sub'>(book lines {escape(e['lines'])}: "
        f"<i>&ldquo;{escape(e['quote'])}&rdquo;</i>)</span>"
    )


def _item(item_id: str, per_mode: list[tuple[Row, Row | None]]) -> str:
    rows = [r for _, r in per_mode if r is not None]
    r0 = rows[0]
    verdicts = {bool(r["passed"]) for r in rows if not r["skipped"]}
    differs = len(verdicts) > 1
    marks = " ".join(
        f"<span class='{'ok' if r['passed'] else 'bad'}'>{escape(c['mode'])} {'&#10003;' if r['passed'] else '&#10007;'}</span>"
        for c, r in per_mode
        if r is not None and not r["skipped"]
    )
    gold = next((r.get("gold_text") for r in rows if r.get("gold_text")), "")
    facts = "".join(
        f"<li>{escape(f)}{_fact_source(r0, i)}</li>"
        for i, f in enumerate(r0.get("must_include", []))
    )
    banned = ", ".join(r0.get("must_not_include", []))
    meta = (
        f"<p><b>Child asks:</b> &ldquo;{escape(r0['input'])}&rdquo;<br>"
        f"<b>Child is at:</b> {escape(where(r0))}<br>"
        f"<b>A good agent should:</b> {escape(str(BEHAVIOUR.get(r0['expected'], r0['expected'])))}</p>"
        + (
            f"<div class='lbl'>Required facts (meaning, not exact words)</div><ul>{facts}</ul>"
            if facts
            else ""
        )
        + (f"<div class='lbl'>Must not contain</div><p>{escape(banned)}</p>" if banned else "")
        + (
            f"<details><summary>Book text that holds the answer</summary><pre>{escape(gold)}</pre></details>"
            if gold
            else ""
        )
    )
    panels = "".join(_panel(c, r) for c, r in per_mode)
    opened = " open" if differs else ""
    tag = "<span class='differs'>modes differ</span>" if differs else ""
    title = f"<b>{escape(item_id)}</b> &middot; {escape(r0['input'][:80])} &nbsp; {marks}{tag}"
    return f"<details id='item-{escape(item_id)}'{opened}><summary>{title}</summary>{meta}<div class='cols'>{panels}</div></details>"


def _items_section(runs: list[Run]) -> str:
    by_mode = [{r["id"]: r for r in rs} for _, rs in runs]
    ids = list(dict.fromkeys(r["id"] for _, rs in runs for r in rs))
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    first = {r["id"]: r for _, rs in runs for r in reversed(rs)}
    ids.sort(key=lambda i: (order.get(first[i]["category"], 99), i))
    runnable = [i for i in ids if any(not m.get(i, {"skipped": True})["skipped"] for m in by_mode)]
    skipped = [i for i in ids if i not in runnable]

    blocks, differing = [], []
    current = ""
    for i in runnable:
        cat = first[i]["category"]
        if cat != current:
            current = cat
            blocks.append(
                f"<h3 id='cat-{cat}'>{escape(category_name(cat))} <span class='dim'>({cat})</span></h3><p class='sub'>{escape(CATEGORY_MEANING.get(cat, ''))}</p>"
            )
        per_mode = [(c, m.get(i)) for (c, _), m in zip(runs, by_mode, strict=True)]
        verdicts = {bool(r["passed"]) for _, r in per_mode if r is not None and not r["skipped"]}
        if len(verdicts) > 1:
            differing.append(f"<a href='#item-{escape(i)}'>{escape(i)}</a>")
        blocks.append(_item(i, per_mode))
    diff = (
        f"<p><b>Questions where the modes disagree ({len(differing)}):</b> {', '.join(differing)}. These are opened for you below.</p>"
        if len(runs) > 1
        else ""
    )
    skip_rows = "".join(
        f"<li>{escape(i)}: {escape(str(first[i]['skipped']))}</li>" for i in skipped
    )
    return (
        "<h2 id='items'>4. Every question, one by one</h2>"
        "<p>Click a question to see what the child asked, what a good agent should do, what each mode replied, "
        "and how it got there (the search results and the checks).</p>"
        f"{diff}{''.join(blocks)}"
        + (f"<h3>Skipped ({len(skipped)})</h3><ul>{skip_rows}</ul>" if skipped else "")
    )


def render_report(runs: list[Run]) -> str:
    config = runs[0][0]
    ran = [r for r in runs[0][1] if not r["skipped"]]
    skipped = [r for r in runs[0][1] if r["skipped"]]
    judged = all(c.get("judged") for c, _ in runs)
    judge_note = (
        f"Facts were judged by {escape(str(config.get('judge_model', 'the model')))}, the same model that writes the replies, so treat small differences with care."
        if judged
        else "The judge was not used, so facts were checked with a simple keyword match and some forbidden-content rules were not checked."
    )
    modes = ", ".join(escape(c["mode"]) for c, _ in runs)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>StoryQuest evaluation</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>StoryQuest evaluation: {modes}</h1>"
        f"<div class='sub'>{escape(config['model'])} &middot; {escape(config['split'])} split &middot; "
        f"{len(ran)} questions run, {len(skipped)} skipped &middot; commit {escape(config['git_commit'])} &middot; "
        f"golden set {escape(config['golden_sha256'])} &middot; {escape(config['started'])}</div>"
        "<div class='note'><b>What this is.</b> A set of questions a child might ask about <i>The Jungle Book</i>, "
        "each with a known right behaviour (answer correctly, say it does not know yet, refuse politely, and so on). "
        "Every mode below answers the same questions, and each answer is scored. "
        f"{judge_note}</div>"
        "<nav><a href='#modes'>1. Modes</a><a href='#summary'>2. Results</a>"
        "<a href='#legend'>3. Legend</a><a href='#items'>4. Questions</a></nav>"
        f"{_modes_section(runs)}{_summary_section(runs)}{_legend_section()}{_items_section(runs)}"
        "</body></html>"
    )
