"""C1: holidays live in calendar; no session math yet."""

import importlib

from arena_kernel.calendar import CALENDAR_MEANINGS, CALENDAR_TERMS
from arena_kernel.module_map import CONCEPT_OWNERS, KERNEL_MODULES


def test_kernel_modules_includes_calendar() -> None:
    assert "calendar" in KERNEL_MODULES


def test_calendar_module_is_importable() -> None:
    module = importlib.import_module("arena_kernel.calendar")
    assert module.CALENDAR_MEANINGS["holiday"] == (
        "Calendar date with no session and no rounds"
    )


def test_holidays_live_in_calendar() -> None:
    assert CONCEPT_OWNERS["holiday"] == ("calendar",)


def test_locked_calendar_terms_are_the_c1_session_names() -> None:
    assert CALENDAR_TERMS == (
        "trading_day",
        "holiday",
        "scheduled_close",
        "reference_minute",
    )
    assert set(CALENDAR_MEANINGS) == set(CALENDAR_TERMS)


def test_trading_day_is_a_regular_or_early_close_session() -> None:
    assert (
        CALENDAR_MEANINGS["trading_day"]
        == "Calendar date with a regular or early-close session"
    )


def test_holiday_is_a_date_with_no_session_and_no_rounds() -> None:
    assert (
        CALENDAR_MEANINGS["holiday"]
        == "Calendar date with no session and no rounds"
    )
    assert CALENDAR_MEANINGS["holiday"] != CALENDAR_MEANINGS["trading_day"]


def test_scheduled_close_is_the_official_end_of_that_session() -> None:
    assert CALENDAR_MEANINGS["scheduled_close"] == (
        "Official end of that session (16:00 regular; earlier on early-close days)"
    )


def test_reference_minute_is_the_first_complete_eligible_bar_after_deadline() -> None:
    assert CALENDAR_MEANINGS["reference_minute"] == (
        "First complete eligible one-minute bar after the round deadline"
    )


def test_unknown_term_is_not_a_locked_calendar_name() -> None:
    assert "weekend" not in CALENDAR_MEANINGS
    assert "vendor" not in CALENDAR_MEANINGS
    assert "bar_fetch" not in CALENDAR_TERMS
