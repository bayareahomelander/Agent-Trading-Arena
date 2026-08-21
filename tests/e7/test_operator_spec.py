"""E7: stable one-round operator contract without E8 construction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena_kernel.schema.errors import SchemaError
from arena_runtime.cli import EXIT_USAGE, main
from arena_runtime.operator_spec import (
    ADAPTER_IDS,
    VENDOR_KINDS,
    dump_operator_spec,
    parse_operator_spec,
)
from tests.r3.conftest import valid_registration

_REPO = Path(__file__).resolve().parents[2]
_CALENDAR = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
_VENDOR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"


def _valid_spec(tmp_path: Path) -> dict[str, object]:
    registration = valid_registration()
    registration["adapter_id"] = "fake"
    season = (tmp_path / "season").resolve()
    return {
        "schema_version": "1",
        "archive": str((tmp_path / "archive").resolve()),
        "books_root": str((tmp_path / "books").resolve()),
        "staging_root": str((tmp_path / "staging").resolve()),
        "season_root": str(season),
        "workspaces": {
            "product-a-1": str((season / "replicas" / "product-a-1").resolve()),
            "product-a-2": str((season / "replicas" / "product-a-2").resolve()),
        },
        "calendar": str(_CALENDAR.resolve()),
        "universe": ["AAA", "SPY"],
        "vendor": {"kind": "fixture", "root": str(_VENDOR.resolve())},
        "registrations": [registration],
        "duties": [
            {
                "product_id": "product-a",
                "replica_id": "product-a-1",
                "status": "active",
            },
            {
                "product_id": "product-a",
                "replica_id": "product-a-2",
                "status": "active",
            },
        ],
        "adapters": {"product-a": "fake"},
        "round_id": "2026-11-02-morning",
        "timestamps": {
            "round_start": "2026-11-02T10:00:00-05:00",
            "deadline": "2026-11-02T10:15:00-05:00",
            "reference_minute": "2026-11-02T10:16:00-05:00",
            "decided_at": "2026-11-02T09:59:30-05:00",
            "published_at": "2026-11-02T10:16:00-05:00",
            "marked_at": "2026-11-02T16:00:00-05:00",
        },
    }


def test_valid_spec_dump_parse_is_stable(tmp_path: Path) -> None:
    first = parse_operator_spec(_valid_spec(tmp_path))
    first_dump = dump_operator_spec(first)
    second = parse_operator_spec(first_dump)

    assert second == first
    assert dump_operator_spec(second) == first_dump
    assert first_dump.endswith("\n")
    assert first.vendor.kind == "fixture"
    assert first.adapters == (("product-a", "fake"),)
    assert first.universe == ("AAA", "SPY")
    assert first.round_id == "2026-11-02-morning"


def test_universe_may_be_an_absolute_path(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    universe = (tmp_path / "universe.json").resolve()
    payload["universe"] = str(universe)

    assert parse_operator_spec(payload).universe == universe


def test_unknown_vendor_kind_fails_with_field_path(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    payload["vendor"] = {"kind": "other"}

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "vendor.kind"
    assert VENDOR_KINDS == ("fixture", "aggregates")


def test_relative_books_root_is_rejected(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    payload["books_root"] = "books"

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "books_root"


def test_naive_timestamp_is_rejected_with_nested_path(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    payload["timestamps"]["deadline"] = "2026-11-02T10:15:00"  # type: ignore[index]

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "timestamps.deadline"


def test_legacy_nested_naive_timestamp_is_also_rejected(tmp_path: Path) -> None:
    payload = {
        "books_root": str((tmp_path / "books").resolve()),
        "requests": [
            {
                "workspace": str((tmp_path / "season" / "replicas" / "a").resolve()),
                "deadline": "2026-11-02T10:15:00",
            }
        ],
    }

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "requests.0.deadline"


def test_unknown_adapter_id_is_rejected(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    payload["adapters"] = {"product-a": "unknown"}

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "adapters.product-a"
    assert ADAPTER_IDS == ("fake", "codex", "grok_build")


def test_registration_adapter_id_is_also_restricted(tmp_path: Path) -> None:
    payload = _valid_spec(tmp_path)
    payload["registrations"][0]["adapter_id"] = "unknown"  # type: ignore[index]

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "registrations.0.adapter_id"


def test_api_key_product_authentication_is_still_rejected_by_r3(
    tmp_path: Path,
) -> None:
    payload = _valid_spec(tmp_path)
    payload["registrations"][0]["authentication_method"] = "api_key"  # type: ignore[index]

    with pytest.raises(SchemaError) as exc:
        parse_operator_spec(payload)

    assert exc.value.path == "registrations.0.authentication_method"


def test_legacy_r25_defaults_to_fixture_and_fake(tmp_path: Path) -> None:
    vendor = (tmp_path / "vendor").resolve()
    parsed = parse_operator_spec(
        {
            "books_root": str((tmp_path / "books").resolve()),
            "vendor": str(vendor),
            "product_ids": ["product-a"],
            "marked_at": "2026-11-02T16:00:00-05:00",
        }
    )

    assert parsed.vendor.kind == "fixture"
    assert parsed.vendor.options == (("root", vendor),)
    assert parsed.adapters == (("product-a", "fake"),)


def test_legacy_r25_may_add_adapter_mapping_incrementally(tmp_path: Path) -> None:
    parsed = parse_operator_spec(
        {
            "books_root": str((tmp_path / "books").resolve()),
            "product_ids": ["product-a"],
            "adapters": {"product-a": "fake"},
            "marked_at": "2026-11-02T16:00:00-05:00",
        }
    )

    assert parsed.vendor.kind == "fixture"
    assert parsed.adapters == (("product-a", "fake"),)


def test_cli_rejects_unknown_vendor_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    spec_path = tmp_path / "close.json"
    spec_path.write_text(
        json.dumps(
            {
                "books_root": str(books.resolve()),
                "vendor": {"kind": "unknown"},
                "session_date": "2026-11-02",
                "replica_ids": ["product-a-1"],
                "marked_at": "2026-11-02T16:00:00-05:00",
            }
        ),
        encoding="utf-8",
    )
    called = False

    def fail_if_called(**_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("arena_runtime.cli.mark_official_close", fail_if_called)

    assert main(["close", "--spec", str(spec_path)]) == EXIT_USAGE
    assert called is False
    assert "vendor.kind" in capsys.readouterr().err


def test_operator_spec_does_not_construct_e8_objects() -> None:
    source = (_REPO / "src" / "arena_runtime" / "operator_spec.py").read_text(
        encoding="utf-8"
    )

    assert "AggregatesVendor(" not in source
    assert "CodexAdapter(" not in source
    assert "GrokBuildAdapter(" not in source
    assert "FixtureVendor(" not in source
    assert "sleep(" not in source
