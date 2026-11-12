"""An LLM judge for what string matching cannot check. It never sees the book itself.

Three questions, each in its own call so the 8B model keeps them apart:
1. Recall and forbidden content: which expected facts does the reply state, and does it contain
   any descriptive forbidden item. Sees the question, the reply and the statements only.
2. Claims: split the reply into separate factual claims. Sees the reply only.
3. Faithfulness and precision: is each claim supported by the passages the agent was given (said
   there, or following from them in one obvious step, which is reported as "inferred"), and which
   expected fact does it state, if any. Sees the passages, the claims and the facts.

Every "yes" must come with a quote, and the quote is checked in code: at least 80% of its words
must occur in the text it should come from (the reply for call 1, the passages for call 3). Models
often trim a quote ("he can go mad" for "He can also go mad"), so exact matching is too strict,
but invented text still fails. A verdict without a real quote counts as "no".
"""

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from storyquest.evaluation.items import GoldItem
from storyquest.ingestion.text import Cleaned
from storyquest.models.llm import LLMClient, Message

MAX_EVIDENCE_CHARS = 3000
MAX_TOKENS = 600
MAX_TOKENS_VERIFY = 1000  # the endpoint allows at most 1024 output tokens
MAX_CLAIMS = 8
_MIN_QUOTE = 4
_QUOTE_WORD_SHARE = 0.8  # share of the quote's words that must occur in the source text
_WORDS = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Claim:
    text: str
    supported: bool  # passes: the passages say it or it is inferred, with a verified quote
    quote: str  # the passage words the judge pointed at
    judge_said_yes: bool
    quote_ok: bool
    fact: int  # number of the expected fact this claim states, 0 for none
    inferred: bool = False  # counts as supported only because it follows from the quote


@dataclass(frozen=True)
class JudgeVerdict:
    facts_stated: list[bool]  # aligned with item.must_include (empty if not asked)
    forbidden_found: list[str]  # descriptive must_not_include entries the reply violates
    raw: str = ""
    fact_quotes: list[str] = field(default_factory=list)  # reply words backing each fact
    prompt: str = ""  # what call 1 was given
    fact_said: list[bool] = field(default_factory=list)  # what the judge answered per fact
    fact_quote_ok: list[bool] = field(default_factory=list)  # did the judge's quote check out
    claims: list[Claim] | None = None  # None: not analysed (no passages, or unreadable answer)
    claims_prompt: str = ""
    claims_raw: str = ""
    verify_prompt: str = ""
    verify_raw: str = ""

    @property
    def faithfulness(self) -> float | None:
        """Share of claims supported by the passages. 1.0 when the reply makes no claims."""
        if self.claims is None:
            return None
        return sum(c.supported for c in self.claims) / len(self.claims) if self.claims else 1.0

    @property
    def precision(self) -> float | None:
        """Share of claims that state an expected fact. None when there is nothing to compare."""
        if not self.claims or not self.facts_stated:
            return None
        return sum(bool(c.fact) and c.supported for c in self.claims) / len(self.claims)


def needs_judging(item: GoldItem, unchecked: list[str]) -> bool:
    answers = item.expected_behavior == "answer" and bool(item.must_include)
    return answers or bool(unchecked)


def evidence_text(item: GoldItem, cleaned: Cleaned) -> str:
    parts = []
    for first, last in item.gold_lines:
        start = cleaned.offset_of_line(first)
        end = cleaned.offset_of_line(last + 1)
        parts.append(cleaned.text[start:end].strip())
    return "\n...\n".join(parts)[:MAX_EVIDENCE_CHARS]


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def _normalise(text: str) -> str:
    table = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
    return re.sub(r"\s+", " ", text.translate(table)).strip().lower()


def _verified(quote: object, source: str) -> bool:
    """True if the quote is text from the source, allowing small edits by the judge."""
    text = _normalise(str(quote or ""))
    words = _WORDS.findall(text)
    if len(text) < _MIN_QUOTE or not words:
        return False
    in_source = set(_WORDS.findall(_normalise(source)))
    return sum(w in in_source for w in words) / len(words) >= _QUOTE_WORD_SHARE


def _pair(props: dict[str, Any], name: str) -> None:
    props[f"{name}_quote"] = {"type": "string"}  # the quote comes first, then the verdict
    props[name] = {"type": "boolean"}


def _template(name: str) -> str:
    return (files("storyquest.evaluation") / "prompts" / name).read_text()


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _read(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def build_request(
    item: GoldItem, reply: str, unchecked: list[str]
) -> tuple[list[Message], dict[str, Any]]:
    """Call 1: which statements the reply makes and which forbidden things it contains."""
    props: dict[str, Any] = {}
    sections = {"facts_section": "", "forbidden_section": ""}
    if item.expected_behavior == "answer" and item.must_include:
        for i in range(1, len(item.must_include) + 1):
            _pair(props, f"fact_{i}")
        sections["facts_section"] = (
            "\nStatements. For each number N, first fill fact_N_quote, then fact_N.\n"
            "- fact_N is true only if the REPLY itself says it. Saying it in other words counts "
            '("causes trouble" says "makes mischief").\n'
            "- fact_N is false if the REPLY does not say it, or only hints at it.\n"
            'Example, for a different question. Reply: "Bagheera is a black panther." '
            "Statements: 1. is a panther 2. has a soft voice. Correct answer: fact_1_quote "
            '"Bagheera is a black panther", fact_1 true, fact_2_quote "", fact_2 false, because '
            "the reply never mentions his voice.\n\nStatements:\n"
            + _numbered(item.must_include)
            + "\n"
        )
    if unchecked:
        for i in range(1, len(unchecked) + 1):
            _pair(props, f"forbidden_{i}")
        sections["forbidden_section"] = (
            "\nForbidden content. For each number N, first fill forbidden_N_quote, then "
            "forbidden_N.\n"
            "- forbidden_N is true only if the REPLY itself contains or does what item N "
            'describes (item "any specific color" is true only if the reply names a color).\n'
            "- A reply that politely refuses, deflects or says it does not know does not contain "
            "it, so forbidden_N is false.\n\nItems:\n" + _numbered(unchecked) + "\n"
        )
    prompt = _template("judge.txt").format(question=item.input, reply=reply, **sections)
    return [{"role": "user", "content": prompt}], _schema(props)


def build_claims_request(item: GoldItem, reply: str) -> tuple[list[Message], dict[str, Any]]:
    """Call 2: split the reply into separate factual claims."""
    prompt = _template("claims.txt").format(question=item.input, reply=reply)
    schema = _schema(
        {"claims": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_CLAIMS}}
    )
    return [{"role": "user", "content": prompt}], schema


def build_verify_request(
    item: GoldItem, claims: list[str], passages: list[str]
) -> tuple[list[Message], dict[str, Any]]:
    """Call 3: is each claim supported by the passages, and which expected fact does it state."""
    props: dict[str, Any] = {}
    facts = item.must_include if item.expected_behavior == "answer" else []
    for i in range(1, len(claims) + 1):
        props[f"claim_{i}_quote"] = {"type": "string"}
        props[f"claim_{i}_supported"] = {"type": "boolean"}
        props[f"claim_{i}_inferred"] = {"type": "boolean"}
        if facts:
            props[f"claim_{i}_fact"] = {"type": "integer", "minimum": 0, "maximum": len(facts)}
    shown = "\n\n".join(f"Passage {i}:\n{p}" for i, p in enumerate(passages, 1))
    if facts:
        fact_block = "\nExpected facts (for claim_N_fact):\n" + _numbered(facts) + "\n"
        fact_rule = (
            "- claim_N_fact: the number of the expected fact the claim states, or 0 if it states "
            "none of them.\n"
        )
        example = (
            ' Expected facts: 1. Mia owns a kite. Correct: claim_1_quote "Mia has a red kite", '
            "claim_1_supported true, claim_1_inferred false, claim_1_fact 1; "
            'claim_2_quote "Mia has a red kite", claim_2_supported false, claim_2_inferred true, '
            'claim_2_fact 0; claim_3_quote "", claim_3_supported false, claim_3_inferred false, '
            "claim_3_fact 0."
        )
    else:
        fact_block, fact_rule = "", ""
        example = (
            ' Correct: claim_1_quote "Mia has a red kite", claim_1_supported true, '
            'claim_1_inferred false; claim_2_quote "Mia has a red kite", claim_2_supported false, '
            'claim_2_inferred true; claim_3_quote "", claim_3_supported false, '
            "claim_3_inferred false."
        )
    prompt = _template("verify.txt").format(
        question=item.input,
        passages=shown,
        claims=_numbered(claims),
        fact_block=fact_block,
        fact_rule=fact_rule,
        example=example,
    )
    return [{"role": "user", "content": prompt}], _schema(props)


def _analyse_claims(
    llm: LLMClient, item: GoldItem, reply: str, passages: list[str]
) -> dict[str, Any]:
    """Calls 2 and 3. Returns the fields of JudgeVerdict that describe the claims."""
    out: dict[str, Any] = {}
    c_messages, c_schema = build_claims_request(item, reply)
    c_result = llm.chat(c_messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=c_schema)
    out.update(claims_prompt=c_messages[0]["content"], claims_raw=c_result.text)
    c_data = _read(c_result.text)
    listed = c_data.get("claims") if c_data else None
    if not isinstance(listed, list):
        return out
    texts = list(dict.fromkeys(str(c).strip() for c in listed if str(c).strip()))[:MAX_CLAIMS]
    if not texts:
        return {**out, "claims": []}
    v_messages, v_schema = build_verify_request(item, texts, passages)
    v_result = llm.chat(
        v_messages, max_tokens=MAX_TOKENS_VERIFY, temperature=0.0, json_schema=v_schema
    )
    out.update(verify_prompt=v_messages[0]["content"], verify_raw=v_result.text)
    v_data = _read(v_result.text)
    if v_data is None:
        return out
    source = "\n".join(passages)
    claims = []
    for i, text in enumerate(texts, 1):
        said = bool(v_data.get(f"claim_{i}_supported"))
        said_inferred = not said and bool(v_data.get(f"claim_{i}_inferred"))
        quote = str(v_data.get(f"claim_{i}_quote") or "")
        ok = _verified(quote, source)
        fact = v_data.get(f"claim_{i}_fact")
        claims.append(
            Claim(
                text,
                (said or said_inferred) and ok,
                quote,
                said or said_inferred,
                ok,
                fact if isinstance(fact, int) else 0,
                inferred=said_inferred and ok,
            )
        )
    return {**out, "claims": claims}


def judge_item(
    llm: LLMClient, item: GoldItem, reply: str, passages: list[str], unchecked: list[str]
) -> JudgeVerdict | None:
    """None when the judge's answer to call 1 is not valid JSON; the caller keeps the keyword check.

    `passages` are the texts the agent was given. Without them, claims are not analysed.
    """
    fields: dict[str, Any] = {}
    facts: list[bool] = []
    found: list[str] = []
    if needs_judging(item, unchecked):
        messages, schema = build_request(item, reply, unchecked)
        result = llm.chat(messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=schema)
        data = _read(result.text)
        if data is None:
            return None

        def yes(name: str) -> bool:
            return bool(data.get(name)) and _verified(data.get(f"{name}_quote"), reply)

        n_facts = len(item.must_include) if item.expected_behavior == "answer" else 0
        facts = [yes(f"fact_{i}") for i in range(1, n_facts + 1)]
        found = [t for i, t in enumerate(unchecked, 1) if yes(f"forbidden_{i}")]
        fields = {
            "raw": result.text,
            "prompt": messages[0]["content"],
            "fact_quotes": [str(data.get(f"fact_{i}_quote") or "") for i in range(1, n_facts + 1)],
            "fact_said": [bool(data.get(f"fact_{i}")) for i in range(1, n_facts + 1)],
            "fact_quote_ok": [
                _verified(data.get(f"fact_{i}_quote"), reply) for i in range(1, n_facts + 1)
            ],
        }
    if passages and reply.strip():
        fields.update(_analyse_claims(llm, item, reply, passages))
    return JudgeVerdict(facts, found, **fields)
