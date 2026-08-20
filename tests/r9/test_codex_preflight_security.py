"""R9: preflight never reads or archives Codex credential-cache contents."""

from pathlib import Path

from arena_runtime.adapters.codex import CodexAdapter

from .conftest import make_case


def test_synthetic_auth_cache_secret_never_reaches_archive(tmp_path: Path) -> None:
    adapter, request, archive, _, _ = make_case(tmp_path)
    assert isinstance(adapter, CodexAdapter)
    credential_store = tmp_path / "codex-credentials"
    credential_store.mkdir()
    synthetic_secret = b"oauth-secret-never-read-123456789"
    (credential_store / "auth.json").write_bytes(synthetic_secret)

    adapter.preflight(request)

    archived = b"".join(
        path.read_bytes() for path in archive.root.rglob("*") if path.is_file()
    )
    assert synthetic_secret not in archived


def test_codex_preflight_source_does_not_open_auth_cache() -> None:
    module = Path(CodexAdapter.__module__.replace(".", "/") + ".py")
    source_path = Path(__file__).parents[2] / "src" / module
    source = source_path.read_text(encoding="utf-8")

    assert "auth.json" not in source
    assert "credential_store.read" not in source
    assert "OPENAI_API_KEY" not in source
    assert "CODEX_API_KEY" not in source
