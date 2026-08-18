"""D1: reviewers can find owners without reading later deliverables."""

import importlib

from arena_kernel.module_map import CONCEPT_OWNERS, KERNEL_MODULES


def test_kernel_modules_are_the_planned_set_in_order() -> None:
    assert KERNEL_MODULES == (
        "types",
        "schema",
        "workspace",
        "validate",
        "pricing",
        "matching",
        "ledger",
        "replay",
        "baselines",
        "calendar",
        "marketdata",
    )


def test_every_kernel_module_is_importable() -> None:
    for name in KERNEL_MODULES:
        importlib.import_module(f"arena_kernel.{name}")


def test_fill_price_lives_in_pricing() -> None:
    assert CONCEPT_OWNERS["fill_price"] == ("pricing",)


def test_order_allowed_lives_in_validate() -> None:
    assert CONCEPT_OWNERS["order_allowed"] == ("validate",)


def test_cash_movement_lives_in_matching_and_ledger() -> None:
    assert CONCEPT_OWNERS["cash_movement"] == ("matching", "ledger")


def test_every_owner_is_a_declared_kernel_module() -> None:
    declared = set(KERNEL_MODULES)
    for owners in CONCEPT_OWNERS.values():
        assert owners, "concept must have at least one owner"
        assert set(owners) <= declared
