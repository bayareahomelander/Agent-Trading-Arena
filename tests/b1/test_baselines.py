"""B1: reviewers can tell the four baselines apart without reading B3–B6."""

import importlib

from arena_kernel.baselines import (
    BASELINE_MEANINGS,
    BASELINE_PRODUCT_ID,
    BASELINE_REPLICA_IDS,
)
from arena_kernel.module_map import CONCEPT_OWNERS, KERNEL_MODULES


def test_kernel_modules_includes_baselines() -> None:
    assert "baselines" in KERNEL_MODULES


def test_baselines_module_is_importable() -> None:
    module = importlib.import_module("arena_kernel.baselines")
    assert module.BASELINE_PRODUCT_ID == "baseline"


def test_non_agent_baseline_lives_in_baselines() -> None:
    assert CONCEPT_OWNERS["non_agent_baseline"] == ("baselines",)


def test_baseline_product_id_is_baseline_not_a_contestant() -> None:
    assert BASELINE_PRODUCT_ID == "baseline"
    assert BASELINE_PRODUCT_ID != "product-a"


def test_locked_replica_ids_are_the_four_readme_baselines() -> None:
    assert BASELINE_REPLICA_IDS == (
        "baseline:cash",
        "baseline:spy_buy_and_hold",
        "baseline:equal_weight",
        "baseline:seeded_random",
    )
    assert set(BASELINE_MEANINGS) == set(BASELINE_REPLICA_IDS)


def test_cash_baseline_holds_starting_cash() -> None:
    assert BASELINE_MEANINGS["baseline:cash"] == "Holds starting cash"


def test_spy_buy_and_hold_is_spy_at_first_window_only() -> None:
    meaning = BASELINE_MEANINGS["baseline:spy_buy_and_hold"]
    assert meaning == "SPY at first window only"
    assert meaning != BASELINE_MEANINGS["baseline:cash"]
    assert meaning != BASELINE_MEANINGS["baseline:equal_weight"]
    assert meaning != BASELINE_MEANINGS["baseline:seeded_random"]


def test_equal_weight_is_equal_notionals_at_first_window_without_rebalance() -> None:
    assert (
        BASELINE_MEANINGS["baseline:equal_weight"]
        == "Equal notionals at first window, no rebalance"
    )


def test_seeded_random_is_seeded_allocations_at_each_window() -> None:
    assert (
        BASELINE_MEANINGS["baseline:seeded_random"]
        == "Seeded allocations at each window"
    )


def test_unknown_replica_id_is_not_a_locked_baseline() -> None:
    assert "baseline:unknown" not in BASELINE_MEANINGS
    assert "cash" not in BASELINE_MEANINGS
    assert "SPY" not in BASELINE_REPLICA_IDS
