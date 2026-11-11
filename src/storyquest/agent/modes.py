from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    """Which agent stages are switched on. One pipeline, different settings."""

    name: str
    retrieval: bool


MODES = {
    "M0": Mode("M0", retrieval=False),  # plain model: no book passages
    "M1": Mode("M1", retrieval=True),  # BM25 retrieval of passages up to the child's position
}


def get_mode(name: str) -> Mode:
    try:
        return MODES[name.upper()]
    except KeyError:
        raise ValueError(f"Unknown mode {name!r}; choose from {', '.join(MODES)}") from None
