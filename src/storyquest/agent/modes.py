from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    """Which agent stages are switched on. One pipeline, different settings."""

    name: str
    title: str
    retrieval: bool
    grounded: bool = False  # the model must pick evidence sentences; code looks them up
    hybrid: bool = False  # search by keywords and by meaning (embeddings), then fuse
    entities: bool = False  # add the cards of characters, places and terms the child names
    rerank: bool = False


MODES = {
    "M0": Mode("M0", "Plain model, no book", retrieval=False),
    "M1": Mode("M1", "Retrieval", retrieval=True),
    "M1S": Mode("M1S", "Retrieval + sentence evidence", retrieval=True, grounded=True),
    "M2": Mode("M2", "Hybrid retrieval", retrieval=True, hybrid=True),
    "M2S": Mode(
        "M2S", "Hybrid retrieval + sentence evidence", retrieval=True, grounded=True, hybrid=True
    ),
    "M3": Mode("M3", "Hybrid retrieval + entity cards", True, hybrid=True, entities=True),
    "M3S": Mode(
        "M3S",
        "Hybrid retrieval + entity cards + sentence evidence",
        retrieval=True,
        grounded=True,
        hybrid=True,
        entities=True,
    ),
    "M4": Mode(
        "M4",
        "Hybrid retrieval + entity cards + cross-encoder reranking",
        retrieval=True,
        hybrid=True,
        entities=True,
        rerank=True,
    ),
    "M4S": Mode(
        "M4S",
        "Hybrid retrieval + entity cards + reranking + sentence evidence",
        retrieval=True,
        grounded=True,
        hybrid=True,
        entities=True,
        rerank=True,
    ),
}


def get_mode(name: str) -> Mode:
    try:
        return MODES[name.upper()]
    except KeyError:
        raise ValueError(f"Unknown mode {name!r}; choose from {', '.join(MODES)}") from None


_GENERATE = (
    "Answer with evidence: every sentence in the passages is numbered. The model lists up "
    "to 3 sentence numbers as its evidence, then answers. Code looks the sentences up. If "
    'the model lists none, the reply is "I don\'t know that yet".'
)
_GENERATE_PLAIN = (
    "Answer: the model writes 2 to 4 simple sentences using only the passages it was given."
)


def describe_steps(mode: Mode, top_k: int) -> list[str]:
    """What the agent does in this mode, in order, in plain words."""
    steps = [
        "Guard: an empty message, or one that is too long, gets a fixed reply. No model is used.",
        "Router: a small model call labels the message (story question, feelings, off topic, "
        "unsafe, injection or personal). Anything except a story question gets a fixed, "
        "pre-written reply and the turn ends here.",
    ]
    if mode.retrieval:
        how = (
            "BM25 keyword ranking and embedding (meaning) similarity, combined by reciprocal "
            "rank fusion"
            if mode.hybrid
            else "BM25 keyword ranking"
        )
        if mode.rerank:
            how += ", then cross-encoder reranking"
        steps.append(
            f"Retrieve: search the book for the {top_k} best-matching passages ({how}). Only "
            "text the child has already read can be found, which prevents spoilers. If nothing "
            'matches, the reply is "I don\'t know that yet".'
        )
        if mode.entities:
            steps.append(
                "Entity cards: if the message names a character, place or term from the book, "
                "its short card (written during ingestion from the first passage that mentions "
                "it) is added as an extra passage, up to 2. Cards the child has not reached yet "
                "are never used."
            )
        steps.append(_GENERATE if mode.grounded else _GENERATE_PLAIN)
    else:
        steps.append(
            "Answer: the model writes 2 to 4 simple sentences from its own memory of the book. "
            "It is not given any passages."
        )
    steps.append(
        "Output check: if the reply mentions films or cartoons the child did not mention, or a "
        "name that only appears later in the book, it is replaced by a safe reply."
    )
    return steps
