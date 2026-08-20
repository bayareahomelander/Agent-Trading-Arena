"""Round kinds used by round ids."""

from arena_kernel.vocabulary import ROUND_KINDS


def test_round_kinds_are_morning_and_late() -> None:
    assert ROUND_KINDS == ("morning", "late")
