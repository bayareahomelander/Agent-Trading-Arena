"""D1: stable names match the Phase A plan and README."""

from arena_kernel.vocabulary import ROUND_KINDS, STABLE_TERMS


def test_stable_terms_include_every_planned_name() -> None:
    assert set(STABLE_TERMS) == {
        "product",
        "replica",
        "round",
        "snapshot",
        "decision",
        "paper_exchange",
        "ledger",
        "bar",
        "fill",
    }


def test_product_means_named_subscribed_agent_system() -> None:
    assert STABLE_TERMS["product"] == "Named subscribed agent system"


def test_replica_is_one_isolated_portfolio_of_a_product() -> None:
    assert "isolated" in STABLE_TERMS["replica"]
    assert "product" in STABLE_TERMS["replica"]


def test_round_is_a_sealed_morning_or_late_window() -> None:
    assert "sealed" in STABLE_TERMS["round"]
    assert ROUND_KINDS == ("morning", "late")


def test_decision_is_the_replica_outbox_file() -> None:
    assert "outbox/decision.json" in STABLE_TERMS["decision"]


def test_ledger_is_append_only_and_not_agent_editable() -> None:
    meaning = STABLE_TERMS["ledger"]
    assert "Append-only" in meaning
    assert "cannot edit" in meaning
