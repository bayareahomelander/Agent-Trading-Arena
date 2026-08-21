"""E8: CLI constructs registered vendors and adapters without waiting."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena_kernel.workspace import write_replica_workspace
from arena_runtime.cli import EXIT_OK, EXIT_USAGE, main
from arena_runtime.orchestrator import published_snapshot_checksum
from tests.r21.conftest import (
    DEADLINE,
    HOLD_DECISION,
    cash_book,
    empty_fills,
    evaluation_snapshot,
)
from tests.r23.conftest import SESSION, VENDOR_DIR, write_book
from tests.r3.conftest import valid_registration

_ROUND_ID = "2026-08-17-morning"
_AWARE = "2026-08-17T10:00:00-04:00"


def _request(workspace: Path, replica_id: str = "product-a-1") -> dict[str, object]:
    return {
        "product_id": "product-a",
        "replica_id": replica_id,
        "round_id": _ROUND_ID,
        "workspace": str(workspace.resolve()),
        "deadline": DEADLINE.isoformat(),
    }


def _script(replica_id: str = "product-a-1") -> dict[str, object]:
    return {
        "product_id": "product-a",
        "replica_id": replica_id,
        "round_id": _ROUND_ID,
        "preflight_started_at": "2026-08-17T09:58:00-04:00",
        "preflight_finished_at": "2026-08-17T09:59:00-04:00",
        "run_started_at": _AWARE,
        "run_finished_at": "2026-08-17T10:05:00-04:00",
        "outcome": "completed",
        "exit_status": 0,
        "decision_text": HOLD_DECISION.decode("utf-8"),
    }


def _registration(adapter_id: str = "fake") -> dict[str, object]:
    registration = valid_registration()
    registration["adapter_id"] = adapter_id
    registration["replica_ids"] = ["product-a-1", "product-a-2"]
    return registration


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_legacy_fake_preflight_still_prints_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    spec = _write_json(
        tmp_path / "preflight.json",
        {
            "archive": str((tmp_path / "archive").resolve()),
            "registrations": [_registration()],
            "duties": [
                {
                    "product_id": "product-a",
                    "replica_id": "product-a-1",
                    "status": "active",
                }
            ],
            "requests": [_request(workspace)],
            "fake_scripts": [_script()],
            "product_ids": ["product-a"],
            "common_data_status": "available",
            "decided_at": "2026-08-17T09:59:30-04:00",
        },
    )

    assert main(["preflight", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "ready"


def test_legacy_fake_run_round_still_prints_committed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    season = (tmp_path / "season").resolve()
    workspace = season / "replicas" / "product-a-1"
    book = cash_book()
    snapshot = evaluation_snapshot(book)
    write_replica_workspace(
        workspace,
        rules_md="# rules\n",
        prompt_md="prompt\n",
        clock=snapshot.clock,
        portfolio=book,
        fills=empty_fills(),
        snapshot=snapshot,
    )
    spec = _write_json(
        tmp_path / "run.json",
        {
            "archive": str((tmp_path / "archive").resolve()),
            "books_root": str((tmp_path / "books").resolve()),
            "staging_root": str((tmp_path / "staging").resolve()),
            "snapshot": str((workspace / "state/market/snapshot.json").resolve()),
            "requests": [_request(workspace)],
            "books": {
                "product-a-1": str((workspace / "state/portfolio.json").resolve())
            },
            "fake_scripts": [_script()],
            "product_ids": ["product-a"],
            "wait": False,
            "preflight": {
                "round_id": _ROUND_ID,
                "ready": True,
                "reason_codes": [],
                "due_replica_ids": ["product-a-1"],
                "preflight_results": [
                    {
                        "product_id": "product-a",
                        "replica_id": "product-a-1",
                        "round_id": _ROUND_ID,
                        "ready": True,
                        "started_at": "2026-08-17T09:58:00-04:00",
                        "finished_at": "2026-08-17T09:59:00-04:00",
                    }
                ],
            },
            "snapshot_checksum": published_snapshot_checksum(workspace),
            "common_data_status": "available",
            "published_at": "2026-08-17T10:16:00-04:00",
        },
    )

    assert main(["run-round", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "committed"


@pytest.mark.parametrize(
    ("adapter_id", "adapter_name", "store_name", "store_dir"),
    [
        ("codex", "CodexAdapter", "CodexSessionStore", "codex-sessions"),
        (
            "grok_build",
            "GrokBuildAdapter",
            "GrokBuildSessionStore",
            "grok-sessions",
        ),
    ],
)
def test_subscription_adapter_is_constructed_per_replica_and_routed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    adapter_id: str,
    adapter_name: str,
    store_name: str,
    store_dir: str,
) -> None:
    season = (tmp_path / "season").resolve()
    replica_ids = ("product-a-1", "product-a-2")
    workspaces = {
        replica_id: season / "replicas" / replica_id for replica_id in replica_ids
    }
    for workspace in workspaces.values():
        workspace.mkdir(parents=True)
    registration = _registration(adapter_id)
    captured: dict[str, object] = {"launches": [], "adapters": []}

    def fake_prepare(
        root: Path, replica_id: str, *, host_environment: object
    ) -> object:
        assert host_environment is not None
        captured["launches"].append((root, replica_id))  # type: ignore[union-attr]
        return SimpleNamespace(replica_id=replica_id)

    def fake_store(root: Path) -> object:
        captured["store_root"] = root
        return SimpleNamespace(root=root)

    class BoundAdapter:
        def __init__(
            self,
            registration_arg: object,
            launch: object,
            *,
            archive: object,
            session_store: object,
        ) -> None:
            self.replica_id = launch.replica_id
            captured["adapters"].append(  # type: ignore[union-attr]
                (registration_arg, launch, archive, session_store)
            )

        def preflight(self, request: object) -> str:
            assert request.replica_id == self.replica_id
            return self.replica_id

        def run(self, request: object) -> str:
            return self.preflight(request)

    def fake_preflight_round(**kwargs: object) -> object:
        requests = kwargs["requests"]
        runner = kwargs["runners"]["product-a"]
        assert [runner.preflight(request) for request in requests] == list(replica_ids)
        return SimpleNamespace(ready=True)

    monkeypatch.setattr("arena_runtime.cli.prepare_replica_launch", fake_prepare)
    monkeypatch.setattr(f"arena_runtime.cli.{store_name}", fake_store)
    monkeypatch.setattr(f"arena_runtime.cli.{adapter_name}", BoundAdapter)
    monkeypatch.setattr("arena_runtime.cli.preflight_round", fake_preflight_round)
    monkeypatch.setattr(
        "arena_runtime.cli.FakeRunner",
        lambda *_args, **_kwargs: pytest.fail("fake runner was constructed"),
    )
    spec = _write_json(
        tmp_path / f"{adapter_id}.json",
        {
            "archive": str((tmp_path / "archive").resolve()),
            "season_root": str(season),
            "workspaces": {
                replica_id: str(workspace.resolve())
                for replica_id, workspace in workspaces.items()
            },
            "registrations": [registration],
            "duties": [
                {
                    "product_id": "product-a",
                    "replica_id": replica_id,
                    "status": "active",
                }
                for replica_id in replica_ids
            ],
            "requests": [
                _request(workspaces[replica_id], replica_id)
                for replica_id in replica_ids
            ],
            "adapters": {"product-a": adapter_id},
            "common_data_status": "available",
            "decided_at": "2026-08-17T09:59:30-04:00",
        },
    )

    assert main(["preflight", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "ready"
    assert captured["launches"] == [
        (season, "product-a-1"),
        (season, "product-a-2"),
    ]
    assert len(captured["adapters"]) == 2  # type: ignore[arg-type]
    store_root = captured["store_root"]
    assert store_root == tmp_path / "runtime-state" / store_dir
    assert all(
        not store_root.is_relative_to(workspace) for workspace in workspaces.values()
    )


def test_close_accepts_fixture_vendor_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    books_root = (tmp_path / "books").resolve()
    write_book(books_root, cash_book())
    spec = _write_json(
        tmp_path / "close.json",
        {
            "books_root": str(books_root),
            "vendor": {"kind": "fixture", "root": str(VENDOR_DIR)},
            "session_date": SESSION.isoformat(),
            "replica_ids": ["product-a-1"],
            "marked_at": "2026-11-02T16:00:00-05:00",
        },
    )

    assert main(["close", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "marked"


def test_close_constructs_aggregates_vendor_from_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    books = (tmp_path / "books").resolve()
    books.mkdir()
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_vendor(**kwargs: object) -> object:
        captured["vendor_options"] = kwargs
        return sentinel

    def fake_close(**kwargs: object) -> object:
        captured["close_vendor"] = kwargs["vendor"]
        return SimpleNamespace(status="marked")

    monkeypatch.delenv("ARENA_VENDOR_API_KEY", raising=False)
    monkeypatch.setattr("arena_runtime.cli.AggregatesVendor", fake_vendor)
    monkeypatch.setattr("arena_runtime.cli.mark_official_close", fake_close)
    spec = _write_json(
        tmp_path / "aggregates-close.json",
        {
            "books_root": str(books),
            "universe": ["AAA", "SPY"],
            "vendor": {
                "kind": "aggregates",
                "base_url": "https://example.test",
                "timeout": 7,
            },
            "session_date": SESSION.isoformat(),
            "replica_ids": ["product-a-1"],
            "marked_at": "2026-11-02T16:00:00-05:00",
        },
    )

    assert main(["close", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "marked"
    assert captured["close_vendor"] is sentinel
    assert captured["vendor_options"] == {
        "base_url": "https://example.test",
        "symbols": ("AAA", "SPY"),
        "timeout": 7,
        "api_key": None,
    }


def test_unknown_adapter_is_usage_before_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "arena_runtime.cli.FakeRunner",
        lambda *_args, **_kwargs: pytest.fail("runner was constructed"),
    )
    spec = _write_json(
        tmp_path / "bad-adapter.json",
        {"adapters": {"product-a": "unknown"}},
    )

    assert main(["preflight", "--spec", str(spec)]) == EXIT_USAGE
    assert "adapters.product-a" in capsys.readouterr().err


def test_vendor_key_path_inside_replica_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    books = (tmp_path / "books").resolve()
    books.mkdir()
    season = (tmp_path / "season").resolve()
    workspace = season / "replicas" / "product-a-1"
    workspace.mkdir(parents=True)
    key_path = workspace / "vendor.key"
    key_path.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        "arena_runtime.cli.AggregatesVendor",
        lambda **_kwargs: pytest.fail("vendor was constructed"),
    )
    spec = _write_json(
        tmp_path / "bad-key-path.json",
        {
            "books_root": str(books),
            "season_root": str(season),
            "workspaces": {"product-a-1": str(workspace)},
            "universe": ["AAA"],
            "vendor": {
                "kind": "aggregates",
                "base_url": "https://example.test",
                "api_key_path": str(key_path),
            },
            "session_date": SESSION.isoformat(),
            "replica_ids": ["product-a-1"],
            "marked_at": "2026-11-02T16:00:00-05:00",
        },
    )

    assert main(["close", "--spec", str(spec)]) == EXIT_USAGE
    assert "vendor.api_key_path" in capsys.readouterr().err


def test_cli_still_does_not_wait_or_open_http_in_e8() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "src" / "arena_runtime" / "cli.py"
    ).read_text(encoding="utf-8")

    assert "sleep(" not in source
    assert "urlopen(" not in source
