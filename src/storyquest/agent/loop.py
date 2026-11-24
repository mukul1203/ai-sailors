"""The agent loop (mode M5): plan, run tools, answer, then a critic checks the answer.

    router ─▶ planner ─▶ tools (1 to 3) ─▶ answer ─▶ code checks ─▶ critic ─▶ reply
                                             ▲                        │
                                             └──── one revision ◀─────┘

The guard and router run first, in turn.py, exactly as in the other modes; only story
questions reach this loop. The guardrails, each tested in tests/agent/test_loop.py:

- a question gets at most `AGENT_MAX_STEPS` steps (model calls and tool calls, router included)
  and `AGENT_TOKEN_BUDGET` tokens; past either cap the child gets a safe reply;
- a plan that cannot be read is asked for once more, then replaced by a plain book search;
- the question itself is always searched, so the planner's tools add to a plain search;
- a failing tool is skipped and the others still count;
- the answer must cite book sentences (as in M2S), then pass the code checks for film words
  and later names, then the critic, who may send it back once before the child gets a safe
  reply instead;
- a model error ends the turn with a friendly "ask me again", never a stack trace.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from storyquest.agent.context import AgentContext, Where
from storyquest.agent.critic import Critique, review
from storyquest.agent.generate import build_messages, generate
from storyquest.agent.grounding import schema_for, verify
from storyquest.agent.memory import PastTurn
from storyquest.agent.modes import Mode
from storyquest.agent.output_check import check_reply
from storyquest.agent.planner import MAX_CALLS, Plan, fallback_plan, make_plan
from storyquest.agent.replies import REPLIES
from storyquest.agent.tools import ToolCall, ToolOutput, run_tool
from storyquest.agent.trace import StepTrace, ToolTrace, TurnResult, timed
from storyquest.domain.position import Position
from storyquest.models.llm import LLMError
from storyquest.stores.search import SearchHit

MAX_REVISIONS = 1  # the critic may send an answer back this many times
MAX_PASSAGES = 8  # passages handed to the answer step, taken fairly from every tool's results


@dataclass
class Budget:
    """Steps and tokens spent on one question, against the caps from the settings."""

    max_steps: int
    max_tokens: int
    steps: int = 0
    tokens: int = 0

    def spend(self, tokens: int = 0) -> None:
        self.steps += 1
        self.tokens += tokens

    def exhausted(self) -> str | None:
        """Why no further step may run ("step_cap" or "token_budget"), or None."""
        if self.steps >= self.max_steps:
            return "step_cap"
        if self.tokens >= self.max_tokens:
            return "token_budget"
        return None


def calls_to_run(plan: Plan) -> list[ToolCall]:
    """The question itself is always searched first, then the planner's own calls, three at most.

    Measured on the dev split, the planner often chose a single name lookup ("Why does Shere
    Khan limp?" -> lookup_character("Shere Khan")), which returns a character's first mentions
    rather than the passage that answers, and the gold passage was found for 15 of 23 questions
    instead of 22. Searching the question first means the planner can only add to what a plain
    search finds, never replace it.
    """
    base = ToolCall("search_book", plan.question)
    extra = [c for c in plan.calls if c != base]
    return [base, *extra][:MAX_CALLS]


def merge_passages(outputs: Sequence[ToolOutput], limit: int = MAX_PASSAGES) -> list[SearchHit]:
    """Every tool's best passage first, then every tool's second, and so on, without repeats,
    so one tool's long result list cannot crowd out what the others found."""
    merged: list[SearchHit] = []
    seen: set[tuple[str, int, str]] = set()
    for rank in range(max((len(o.passages) for o in outputs), default=0)):
        for output in outputs:
            if rank < len(output.passages):
                hit = output.passages[rank]
                key = (hit.source, hit.chunk_id, hit.text)
                if key not in seen:
                    seen.add(key)
                    merged.append(hit)
    return merged[:limit]


@dataclass
class _Run:
    """Everything one question collects as it goes; `finish` turns it into a TurnResult."""

    ctx: AgentContext
    mode: Mode
    position: Position
    budget: Budget
    steps: list[StepTrace]
    flags: list[str]
    timings: dict[str, float]
    tool_calls: list[ToolTrace] = field(default_factory=list)
    passages: list[SearchHit] = field(default_factory=list)

    def record(self, step: StepTrace) -> None:
        self.steps.append(step)
        self.budget.spend(step.prompt_tokens + step.completion_tokens)

    def finish(self, reply: str, evidence: str = "", route: str = "story_question") -> TurnResult:
        return TurnResult(
            reply,
            route,
            self.mode.name,
            self.steps,
            self.passages,
            self.flags,
            evidence,
            tool_calls=self.tool_calls,
        )

    # --- 1. plan ---------------------------------------------------------------------------

    def plan(self, child_text: str, history: Sequence[PastTurn]) -> Plan:
        """The planner's plan; asked twice at most, then a plain search for the child's words."""
        for _ in range(2):
            if self.budget.exhausted():
                break
            try:
                with timed(self.timings, "planner"):
                    plan, step = make_plan(self.ctx.llm, self.ctx.book.title, child_text, history)
            except LLMError as e:
                self.flags.append(f"llm_error:planner:{e}")
                break
            self.record(step)
            if plan is not None:
                return plan
            self.flags.append("planner_unparsed")
        self.flags.append("planner_fallback")
        return fallback_plan(child_text)

    # --- 2. run the tools --------------------------------------------------------------------

    def gather(self, calls: Sequence[ToolCall]) -> list[SearchHit]:
        """Run the planned tool calls, within the step budget, and merge what they found."""
        outputs = []
        for call in calls:
            if stop := self.budget.exhausted():
                self.flags.append(f"{stop}:tools")
                break
            with timed(self.timings, "tools"):
                output, trace = run_tool(self.ctx, self.position, call)
            self.budget.spend()
            self.tool_calls.append(trace)
            if trace.error:
                self.flags.append(f"tool_error:{trace.tool}")
            self.flags.extend(f for f in output.flags if f not in self.flags)
            outputs.append(output)
        self.passages = merge_passages(outputs)
        return self.passages

    # --- 3. answer ---------------------------------------------------------------------------

    def answer(self, where: Where, question: str, feedback: str) -> tuple[str, str] | None:
        """A grounded answer and the sentences it cites, or None (with a flag saying why)."""
        messages = build_messages(self.ctx, self.mode, where, question, self.passages)
        if feedback:
            messages[-1]["content"] += (
                "\n\nA reviewer checked your last answer and found a problem: "
                f"{feedback}\nWrite a new answer that fixes it. Say less rather than add "
                "anything the cited sentences do not say."
            )
        with timed(self.timings, "generate"):
            result = generate(self.ctx, messages, schema=schema_for(self.passages))
        self.record(StepTrace.of("generate", messages, result))
        answer, problem, evidence = verify(result.text, self.passages)
        if answer is None:
            self.flags.append(f"ungrounded:{problem}")
            return None
        return answer, evidence

    # --- 4. criticise ------------------------------------------------------------------------

    def criticise(self, where: Where, question: str, evidence: str, answer: str) -> Critique:
        """The critic's verdict. An unreadable verdict or a model error lets the answer through,
        because it has already passed the grounding and code checks; the flag says so."""
        try:
            with timed(self.timings, "critic"):
                critique, step = review(
                    self.ctx.llm,
                    self.ctx.book.title,
                    where,
                    question,
                    "\n\n".join(p.text for p in self.passages),
                    evidence,
                    answer,
                )
        except LLMError as e:
            self.flags.append(f"llm_error:critic:{e}")
            return Critique(True)
        self.record(step)
        if critique is None:
            self.flags.append("critic_unparsed")
            return Critique(True)
        return critique


def run_agent(
    ctx: AgentContext,
    child_text: str,
    position: Position,
    mode: Mode,
    *,
    history: Sequence[PastTurn],
    steps: list[StepTrace],
    flags: list[str],
    timings: dict[str, float],
) -> TurnResult:
    """Answer one story question with the agent loop. `steps` and `flags` are the router's,
    which count against the budget too."""
    s = ctx.settings
    run = _Run(
        ctx, mode, position, Budget(s.agent_max_steps, s.agent_token_budget), [], flags, timings
    )
    for step in steps:
        run.record(step)

    plan = run.plan(child_text, history)
    if not run.gather(calls_to_run(plan)):
        run.flags.append("no_hits")
        return run.finish(REPLIES["unknown_yet"])

    where = ctx.where(position)
    # Only the child's own words may name later characters (the planner's rewrite must not),
    # so the spoiler check allows the words of this question and the earlier ones only.
    childs_words = " ".join([child_text, *(t.question for t in history)])
    feedback = ""
    for attempt in range(MAX_REVISIONS + 1):
        if stop := run.budget.exhausted():
            run.flags.append(stop)
            return run.finish(REPLIES["unknown_yet"])
        try:
            draft = run.answer(where, plan.question, feedback)
        except LLMError as e:
            run.flags.append(f"llm_error:generate:{e}")
            return run.finish(REPLIES["error"], route="error")
        if draft is None:
            return run.finish(REPLIES["unknown_yet"])
        reply, evidence = draft

        problems = check_reply(reply, childs_words, ctx.names, where.boundary)
        if problems:
            run.flags.extend(problems)
            return run.finish(REPLIES["careful"], evidence)

        if stop := run.budget.exhausted():
            run.flags.append(f"{stop}:critic_skipped")
            return run.finish(reply, evidence)
        critique = run.criticise(where, plan.question, evidence, reply)
        if critique.approved:
            if attempt:
                run.flags.append("critic_revised")
            return run.finish(reply, evidence)
        run.flags.append("critic_revise")
        feedback = critique.problem or "Use only facts that are in the book sentences."

    run.flags.append("critic_rejected")
    return run.finish(REPLIES["unknown_yet"])
