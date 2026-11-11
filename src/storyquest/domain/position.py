from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Position:
    """How far a child has read: a chapter and a beat within it (both zero-based)."""

    chapter_idx: int
    beat_idx: int

    def can_see(self, chapter_idx: int, beat_idx: int) -> bool:
        """Text up to and including the current beat is allowed; anything later is a spoiler."""
        return (chapter_idx, beat_idx) <= (self.chapter_idx, self.beat_idx)
