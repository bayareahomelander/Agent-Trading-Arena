"""B1: locked baseline replica ids are the four README baselines."""

from arena_kernel.baselines import BASELINE_PRODUCT_ID, BASELINE_REPLICA_IDS


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


def test_unknown_replica_id_is_not_a_locked_baseline() -> None:
    assert "SPY" not in BASELINE_REPLICA_IDS
