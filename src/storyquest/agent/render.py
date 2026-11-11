"""A readable text view of one turn, for the command line."""

from storyquest.agent.context import AgentContext
from storyquest.agent.trace import TurnResult
from storyquest.domain.position import Position


def render_turn(
    ctx: AgentContext, position: Position, question: str, result: TurnResult, *, verbose: bool
) -> str:
    where = ctx.where(position)
    out = [
        f"Mode {result.mode} | {ctx.book.title} | child at chapter {position.chapter_idx} "
        f"({where.chapter_title}), beat B{position.beat_idx + 1}"
        + (f" ({where.beat_title})" if where.beat_title else ""),
        f"Child: {question}",
        f"Route: {result.route}",
    ]
    if result.passages:
        out.append(f"Passages given to the model ({len(result.passages)}):")
        for h in result.passages:
            snippet = " ".join(h.text.split())[:90]
            out.append(
                f"  ch{h.chapter_idx} B{h.beat_idx + 1}.{h.idx}  score {h.score:.2f}  {snippet}…"
            )
    out += ["", f"Reply: {result.reply}", ""]
    for s in result.steps:
        cached = " (cached)" if s.cached else ""
        out.append(
            f"[{s.name}] {s.prompt_tokens}+{s.completion_tokens} tokens, {s.latency_s:.1f}s{cached}"
        )
    if result.flags:
        out.append(f"Flags: {', '.join(result.flags)}")
    if verbose:
        for s in result.steps:
            out += ["", f"----- {s.name}: messages sent -----"]
            for m in s.messages:
                out += [f"[{m['role']}]", m["content"], ""]
            out += [f"----- {s.name}: model output -----", s.output]
    return "\n".join(out)
