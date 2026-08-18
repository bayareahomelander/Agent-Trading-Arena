"""R20: a later agent write cannot change staged bytes."""

from pathlib import Path

from arena_kernel.workspace import OUTBOX_DECISION_FILE

from .conftest import DECISION_A, collect, make_result, make_workspace, write_decision


def test_later_outbox_write_does_not_change_staged_bytes(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1", DECISION_A)
    result = make_result(payload=DECISION_A)
    collection = collect(
        tmp_path,
        (result,),
        workspaces={"product-a-1": workspace},
    )
    staged = collection.records[0].staged_path
    assert staged is not None

    write_decision(workspace, b"mutated after the barrier closed")

    assert (workspace / OUTBOX_DECISION_FILE).read_bytes() == (
        b"mutated after the barrier closed"
    )
    assert staged.read_bytes() == DECISION_A
