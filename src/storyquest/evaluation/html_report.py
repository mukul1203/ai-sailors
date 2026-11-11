"""A single self-contained HTML page for one run, optionally compared with another run."""

from collections import Counter
from html import escape
from statistics import mean

from storyquest.evaluation.runner import Row, pass_rates

_CSS = """
body{font:15px/1.5 -apple-system,Segoe UI,sans-serif;margin:2rem auto;max-width:980px;color:#222;padding:0 1rem}
h1{margin:0 0 .2rem}h2{margin:2rem 0 .6rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}
.sub{color:#666;font-size:13px}.cards{display:flex;flex-wrap:wrap;gap:.8rem;margin:1rem 0}
.card{border:1px solid #ddd;border-radius:8px;padding:.6rem 1rem;min-width:140px}
.card b{display:block;font-size:22px}.card span{color:#666;font-size:12px}
table{border-collapse:collapse;width:100%}td,th{padding:.3rem .5rem;text-align:left;border-bottom:1px solid #eee}
.bar{background:#eee;border-radius:4px;height:10px;width:160px}.bar i{display:block;height:10px;border-radius:4px;background:#3a8}
.bad{color:#b33}.ok{color:#2a7}details{border:1px solid #e3e3e3;border-radius:6px;margin:.4rem 0;padding:.3rem .7rem}
summary{cursor:pointer}pre{white-space:pre-wrap;background:#f6f6f6;padding:.5rem;border-radius:4px}
.tag{font-size:12px;border-radius:4px;padding:0 .4rem;background:#fde;color:#a22}.k{color:#666;width:150px}
"""


def _pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)}%" if b else "-"


def _bar(a: int, b: int) -> str:
    width = round(100 * a / b) if b else 0
    return f'<div class="bar"><i style="width:{width}%"></i></div>'


def _card(value: str, label: str) -> str:
    return f'<div class="card"><b>{escape(value)}</b><span>{escape(label)}</span></div>'


def _judge_html(j: Row | None) -> str:
    if not j:
        return "not judged"
    parts = []
    for d in j.get("fact_details", []):
        mark = (
            '<span class="ok">stated</span>' if d["stated"] else '<span class="bad">MISSING</span>'
        )
        quote = f' &mdash; <i>"{escape(d["quote"])}"</i>' if d["quote"] else ""
        parts.append(f"<li>{mark}: {escape(d['fact'])}{quote}</li>")
    out = f"<ul>{''.join(parts)}</ul>" if parts else ""
    if j["contradicts_book"]:
        quote = escape(j.get("contradiction_quote") or "")
        out += f'<div class="bad">Contradicts or invents beyond the book: <i>"{quote}"</i></div>'
    else:
        out += '<div class="ok">No contradiction with the book found</div>'
    if j["forbidden_found"]:
        out += (
            '<div class="bad">Forbidden content: '
            + escape("; ".join(j["forbidden_found"]))
            + "</div>"
        )
    if j.get("evidence"):
        out += f"<details><summary>Book text the judge used</summary><pre>{escape(j['evidence'])}</pre></details>"
    return out


def _item(r: Row) -> str:
    tag = "" if r["passed"] else f' <span class="tag">{escape(str(r["label"]))}</span>'
    passages = ", ".join(f"ch{p['chapter']} B{p['beat'] + 1}.{p['idx']}" for p in r["passages"])
    facts = r["fact_coverage"]
    rows = [
        ("Expected", r["expected"]),
        ("Route", r["route"]),
        ("Reply", None),
        ("Retrieval hit", r["retrieval_hit"]),
        ("Facts", "-" if facts is None else f"{facts:.2f} (share of required facts the reply states)"),
        ("Forbidden terms", ", ".join(r["violations"]) or "none"),
        ("Not checked by code", ", ".join(r["unchecked"]) or "none"),
        ("Judge", None),
        ("Flags", ", ".join(r["flags"]) or "none"),
        ("Passages", passages or "none"),
        ("Cost", f"{r['calls']} calls, {r['prompt_tokens']}+{r['completion_tokens']} tokens, {r['latency_s']}s"),
    ]  # fmt: skip
    special = {"Reply": f"<pre>{escape(r['reply'])}</pre>", "Judge": _judge_html(r.get("judge"))}
    body = "".join(
        f'<tr><td class="k">{k}</td><td>'
        + (special[k] if k in special else escape(str(v)))
        + "</td></tr>"
        for k, v in rows
    )
    title = f"{escape(r['id'])} {escape(r['position'])} &mdash; {escape(r['input'][:90])}"
    return f"<details><summary>{title}{tag}</summary><table>{body}</table></details>"


def render_html(config: Row, rows: list[Row], baseline: tuple[Row, list[Row]] | None = None) -> str:
    ran = [r for r in rows if not r["skipped"]]
    skipped = [r for r in rows if r["skipped"]]
    passed = sum(bool(r["passed"]) for r in ran)
    with_gold = [r for r in ran if r["retrieval_hit"] is not None]
    hits = sum(bool(r["retrieval_hit"]) for r in with_gold)
    coverage = [r["fact_coverage"] for r in ran if r["fact_coverage"] is not None]
    judged = bool(config.get("judged"))

    cards = [
        _card(f"{passed}/{len(ran)} ({_pct(passed, len(ran))})", "pass rate"),
        _card(f"{hits}/{len(with_gold)}", f"gold passage in top {config['retrieval_top_k']}"),
        _card(f"{mean(coverage):.2f}" if coverage else "-", "fact coverage, " + ("LLM judge" if judged else "keyword proxy")),
        _card(f"{mean(r['calls'] for r in ran):.1f}" if ran else "-", "model calls per item"),
        _card(f"{mean(r['latency_s'] for r in ran):.1f}s" if ran else "-", "time per item"),
    ]  # fmt: skip

    base_rates = pass_rates(baseline[1]) if baseline else {}
    head = "<tr><th>Category</th><th></th><th>Passed</th>"
    head += (
        f"<th>{escape(baseline[0]['mode'])} baseline</th><th>Change</th></tr>"
        if baseline
        else "</tr>"
    )
    cat_rows = []
    for cat, (p, n) in pass_rates(rows).items():
        extra = ""
        if baseline:
            bp, bn = base_rates.get(cat, (0, 0))
            delta = round(100 * p / n - 100 * bp / bn) if n and bn else 0
            cls = "ok" if delta > 0 else "bad" if delta < 0 else ""
            extra = f'<td>{bp}/{bn}</td><td class="{cls}">{delta:+d} pts</td>'
        cat_rows.append(f"<tr><td>{cat}</td><td>{_bar(p, n)}</td><td>{p}/{n}</td>{extra}</tr>")

    causes = Counter(r["label"] for r in ran if not r["passed"])
    cause_list = "".join(f"<li>{escape(str(k))}: {v}</li>" for k, v in causes.most_common())
    failures = "".join(_item(r) for r in ran if not r["passed"])
    passes = "".join(_item(r) for r in ran if r["passed"])

    changes = ""
    if baseline:
        was = {r["id"]: bool(r["passed"]) for r in baseline[1] if not r["skipped"]}
        now = {r["id"]: bool(r["passed"]) for r in ran}
        fixed = sorted(i for i in now if now[i] and was.get(i) is False)
        broke = sorted(i for i in now if not now[i] and was.get(i) is True)
        changes = (
            f"<h2>Compared with {escape(baseline[0]['mode'])}</h2>"
            f'<p class="ok">Now passing: {escape(", ".join(fixed) or "none")}</p>'
            f'<p class="bad">Newly failing: {escape(", ".join(broke) or "none")}</p>'
        )

    note = (
        f"Judged by {escape(str(config['judge_model']))}, the same model that wrote the replies."
        if judged
        else "Facts are scored with a keyword proxy and descriptive forbidden content is not checked yet."
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>Eval {escape(config['mode'])}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Mode {escape(config['mode'])} on the {escape(config['split'])} split</h1>"
        f"<div class='sub'>{escape(config['model'])} &middot; commit {escape(config['git_commit'])} "
        f"&middot; golden set {escape(config['golden_sha256'])} &middot; {len(ran)} items run, "
        f"{len(skipped)} skipped &middot; {escape(config['started'])}</div>"
        f"<div class='cards'>{''.join(cards)}</div><p class='sub'>{note}</p>"
        f"<h2>By category</h2><table>{head}{''.join(cat_rows)}</table>"
        f"<h2>Why items failed</h2><ul>{cause_list or '<li>nothing failed</li>'}</ul>"
        f"{changes}<h2>Failures ({len(ran) - passed})</h2>{failures or '<p>None.</p>'}"
        f"<h2>Passed ({passed})</h2>{passes or '<p>None.</p>'}"
        f"<h2>Skipped ({len(skipped)})</h2><ul>"
        + "".join(f"<li>{escape(r['id'])}: {escape(str(r['skipped']))}</li>" for r in skipped)
        + "</ul></body></html>"
    )
