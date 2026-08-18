"""R1: reviewers can locate future runtime owners without runtime behavior."""

import importlib
from pathlib import Path

from arena_kernel.module_map import CONCEPT_OWNERS as KERNEL_CONCEPT_OWNERS
from arena_kernel.module_map import KERNEL_MODULES
from arena_runtime.module_map import CONCEPT_OWNERS, RUNTIME_MODULES


def test_minimal_runtime_modules_import() -> None:
    for name in ("arena_runtime", "arena_runtime.vocabulary", "arena_runtime.module_map"):
        importlib.import_module(name)


def test_runtime_modules_name_every_planned_owner_in_order() -> None:
    assert RUNTIME_MODULES == (
        "runner",
        "registration",
        "audit",
        "process",
        "isolation",
        "disposition",
        "orchestrator",
        "cli",
        "adapters",
    )


def test_every_runtime_owner_is_declared() -> None:
    declared = set(RUNTIME_MODULES)
    for owners in CONCEPT_OWNERS.values():
        assert owners, "concept must have at least one owner"
        assert set(owners) <= declared


def test_runtime_terms_have_planned_owners() -> None:
    assert CONCEPT_OWNERS["provider_adapter"] == ("adapters",)
    assert CONCEPT_OWNERS["runner_request"] == ("runner",)
    assert CONCEPT_OWNERS["preflight"] == ("adapters",)
    assert CONCEPT_OWNERS["runner_outcome"] == ("runner",)
    assert CONCEPT_OWNERS["session_reference"] == ("runner",)
    assert CONCEPT_OWNERS["decision_barrier"] == ("orchestrator",)
    assert CONCEPT_OWNERS["round_disposition"] == ("disposition",)
    assert CONCEPT_OWNERS["staged_commit"] == ("orchestrator",)
    assert CONCEPT_OWNERS["provider_artifact"] == ("audit",)


def test_product_execution_and_exchange_economics_have_separate_owners() -> None:
    assert CONCEPT_OWNERS["provider_adapter"] == ("adapters",)
    assert KERNEL_CONCEPT_OWNERS["fill_price"] == ("pricing",)
    assert KERNEL_CONCEPT_OWNERS["cash_movement"] == ("matching", "ledger")
    assert "arena_runtime" not in KERNEL_MODULES


def test_r1_does_not_create_future_behavior_modules() -> None:
    package_dir = Path(__file__).parents[2] / "src" / "arena_runtime"
    assert {path.name for path in package_dir.glob("*.py")} == {
        "__init__.py",
        "module_map.py",
        "vocabulary.py",
    }
    assert not (package_dir / "adapters").exists()
