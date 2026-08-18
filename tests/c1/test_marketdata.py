"""C1: bar fetches live in marketdata; no vendor client yet."""

import importlib

from arena_kernel.marketdata import MARKETDATA_MEANINGS, MARKETDATA_TERMS
from arena_kernel.module_map import CONCEPT_OWNERS, KERNEL_MODULES


def test_kernel_modules_includes_marketdata() -> None:
    assert "marketdata" in KERNEL_MODULES


def test_marketdata_module_is_importable() -> None:
    module = importlib.import_module("arena_kernel.marketdata")
    assert module.MARKETDATA_MEANINGS["vendor"] == (
        "The single frozen market-data source for a tape"
    )


def test_bar_fetches_live_in_marketdata() -> None:
    assert CONCEPT_OWNERS["bar_fetch"] == ("marketdata",)


def test_holidays_do_not_live_in_marketdata() -> None:
    assert CONCEPT_OWNERS["holiday"] != ("marketdata",)
    assert CONCEPT_OWNERS["bar_fetch"] != ("calendar",)


def test_locked_marketdata_terms_are_the_c1_vendor_names() -> None:
    assert MARKETDATA_TERMS == (
        "vendor",
        "common_data_unavailable",
    )
    assert set(MARKETDATA_MEANINGS) == set(MARKETDATA_TERMS)


def test_vendor_is_the_single_frozen_source_for_a_tape() -> None:
    assert (
        MARKETDATA_MEANINGS["vendor"]
        == "The single frozen market-data source for a tape"
    )


def test_common_data_unavailable_means_no_snapshot_and_no_fills() -> None:
    assert MARKETDATA_MEANINGS["common_data_unavailable"] == (
        "Vendor cannot supply the common snapshot; no fills"
    )
    assert (
        MARKETDATA_MEANINGS["common_data_unavailable"]
        != MARKETDATA_MEANINGS["vendor"]
    )


def test_unknown_term_is_not_a_locked_marketdata_name() -> None:
    assert "holiday" not in MARKETDATA_MEANINGS
    assert "http" not in MARKETDATA_MEANINGS
    assert "nyse" not in MARKETDATA_TERMS
