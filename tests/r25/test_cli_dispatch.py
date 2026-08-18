"""R25: each command invokes its owning runtime operation."""

import json
from pathlib import Path
from types import SimpleNamespace

from arena_runtime.cli import (
    EXIT_DEFERRED,
    EXIT_OK,
    EXIT_PAUSED,
    EXIT_USAGE,
    main,
)


def test_missing_spec_fails_before_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    called = {"preflight": False, "close": False}

    monkeypatch.setattr(
        "arena_runtime.cli.preflight_round",
        lambda **_kwargs: called.__setitem__("preflight", True),
    )
    monkeypatch.setattr(
        "arena_runtime.cli.mark_official_close",
        lambda **_kwargs: called.__setitem__("close", True),
    )

    code = main(["preflight", "--spec", str(tmp_path / "missing.json")])

    assert code == EXIT_USAGE
    assert called == {"preflight": False, "close": False}
    assert "spec not found" in capsys.readouterr().err


def test_preflight_command_invokes_preflight_round(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    spec = tmp_path / "preflight.json"
    spec.write_text("{}", encoding="utf-8")
    captured: dict = {}

    def fake_load(_path):
        return {"marker": "preflight"}

    def fake_cmd(args):
        captured["spec"] = args.spec
        print("ready")
        return EXIT_OK

    monkeypatch.setattr("arena_runtime.cli.cmd_preflight", fake_cmd)
    code = main(["preflight", "--spec", str(spec)])
    assert code == EXIT_OK
    assert captured["spec"] == spec
    assert capsys.readouterr().out.strip() == "ready"


def test_run_round_command_invokes_run_round_handler(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    spec = tmp_path / "round.json"
    spec.write_text("{}", encoding="utf-8")

    def fake_cmd(args):
        print("committed")
        return EXIT_OK

    monkeypatch.setattr("arena_runtime.cli.cmd_run_round", fake_cmd)
    assert main(["run-round", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "committed"


def test_close_command_invokes_mark_official_close(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    books = tmp_path / "books"
    vendor = tmp_path / "vendor"
    books.mkdir()
    vendor.mkdir()
    spec = tmp_path / "close.json"
    spec.write_text(
        json.dumps(
            {
                "books_root": str(books),
                "vendor": str(vendor),
                "session_date": "2026-11-02",
                "replica_ids": ["product-a-1"],
                "marked_at": "2026-11-02T16:00:00-05:00",
            }
        ),
        encoding="utf-8",
    )
    called: dict = {}

    def fake_close(**kwargs):
        called.update(kwargs)
        return SimpleNamespace(status="marked")

    monkeypatch.setattr("arena_runtime.cli.mark_official_close", fake_close)
    code = main(["close", "--spec", str(spec)])
    assert code == EXIT_OK
    assert called["books_root"] == books.resolve()
    assert called["session_date"].isoformat() == "2026-11-02"
    assert capsys.readouterr().out.strip() == "marked"


def test_close_deferred_uses_deferred_exit_status(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    books = tmp_path / "books"
    vendor = tmp_path / "vendor"
    books.mkdir()
    vendor.mkdir()
    spec = tmp_path / "close.json"
    spec.write_text(
        json.dumps(
            {
                "books_root": str(books),
                "vendor": str(vendor),
                "session_date": "2026-11-04",
                "replica_ids": ["product-a-1"],
                "marked_at": "2026-11-04T16:00:00-05:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "arena_runtime.cli.mark_official_close",
        lambda **_kwargs: SimpleNamespace(status="deferred"),
    )
    assert main(["close", "--spec", str(spec)]) == EXIT_DEFERRED
    assert capsys.readouterr().out.strip() == "deferred"


def test_paused_preflight_uses_paused_exit_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = tmp_path / "preflight.json"
    spec.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "arena_runtime.cli.cmd_preflight",
        lambda _args: (print("paused") or EXIT_PAUSED),
    )
    assert main(["preflight", "--spec", str(spec)]) == EXIT_PAUSED
