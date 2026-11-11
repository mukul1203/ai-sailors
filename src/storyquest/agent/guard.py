def check_input(text: str, max_chars: int) -> str | None:
    """Returns the name of a canned reply if the message should not go any further."""
    if not text:
        return "empty"
    if len(text) > max_chars:
        return "too_long"
    return None
