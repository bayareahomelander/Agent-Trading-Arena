"""R8: only agent/ and outbox/ are writable during launch."""

import json
import stat
from pathlib import Path

from arena_runtime.isolation import (
    enforce_workspace_permissions,
    prepare_replica_launch,
    run_isolated_process,
)

from .conftest import argv, deadline, make_season, sanitized_host_environment


def test_permission_guard_marks_only_agent_and_outbox_writable(
    tmp_path: Path,
) -> None:
    season = make_season(tmp_path)
    launch = prepare_replica_launch(
        season,
        "product-a-1",
        host_environment=sanitized_host_environment(),
    )

    with enforce_workspace_permissions(launch):
        assert not stat.S_IMODE((launch.workspace / "RULES.md").stat().st_mode) & (
            stat.S_IWUSR
        )
        assert not stat.S_IMODE(
            (launch.workspace / "state" / "portfolio.json").stat().st_mode
        ) & stat.S_IWUSR
        assert stat.S_IMODE((launch.workspace / "agent").stat().st_mode) & stat.S_IWUSR
        assert stat.S_IMODE((launch.workspace / "outbox").stat().st_mode) & stat.S_IWUSR


def test_child_can_write_agent_and_outbox_but_not_frozen_state(
    tmp_path: Path,
) -> None:
    season = make_season(tmp_path)
    launch = prepare_replica_launch(
        season,
        "product-a-1",
        host_environment=sanitized_host_environment(),
    )

    facts = run_isolated_process(
        launch,
        argv("write-scope"),
        deadline=deadline(),
    )
    report = json.loads(facts.stdout)

    assert (launch.workspace / "agent" / "notes" / "child.txt").read_text(
        encoding="utf-8"
    ) == "agent write\n"
    assert (launch.workspace / "outbox" / "decision.json").read_text(
        encoding="utf-8"
    ) == "decision bytes\n"
    assert report == {
        "rules_write": False,
        "state_write": False,
        "state_create": False,
        "root_create": False,
    }
    assert (launch.workspace / "RULES.md").read_text(encoding="utf-8") == (
        "frozen rules\n"
    )
    assert (
        launch.workspace / "state" / "portfolio.json"
    ).read_text(encoding="utf-8") == '{}\n'
    assert not (launch.workspace / "state" / "new.json").exists()
    assert not (launch.workspace / "unexpected.txt").exists()


def test_original_modes_are_restored_after_launch(tmp_path: Path) -> None:
    season = make_season(tmp_path)
    launch = prepare_replica_launch(
        season,
        "product-a-1",
        host_environment=sanitized_host_environment(),
    )
    rules = launch.workspace / "RULES.md"
    before = stat.S_IMODE(rules.stat().st_mode)

    run_isolated_process(launch, argv("report"), deadline=deadline())

    assert stat.S_IMODE(rules.stat().st_mode) == before
    rules.write_text("frozen rules\n", encoding="utf-8")
    (launch.workspace / "state" / "after-launch.json").write_text(
        '{}\n',
        encoding="utf-8",
    )
    (launch.workspace / "after-launch.txt").write_text(
        "restored\n",
        encoding="utf-8",
    )
