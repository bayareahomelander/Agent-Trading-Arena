"""R18: due replicas launch concurrently against one deadline."""

from pathlib import Path

from .conftest import REPLICA_A1, REPLICA_B1, launch_barrier


def test_due_replica_launches_overlap(tmp_path: Path) -> None:
    result, _, runner, _, _ = launch_barrier(tmp_path, wrap_overlap=True)

    assert [item.replica_id for item in result.results] == [REPLICA_A1, REPLICA_B1]
    assert {replica for replica, _started in runner.starts} == {REPLICA_A1, REPLICA_B1}
    last_start = max(started for _replica, started in runner.starts)
    first_finish = min(finished for _replica, finished in runner.finishes)
    assert last_start <= first_finish
