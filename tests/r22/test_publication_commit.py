"""R22: two ready candidates publish both books, fills, and events."""

from pathlib import Path

from arena_runtime.audit import parse_audit_event
from arena_runtime.orchestrator import reconstruct_published_round

from .conftest import dumps_for, publish, two_candidate_evaluation


def test_two_ready_candidates_publish_both_books(tmp_path: Path) -> None:
    candidates, _collection, book_a, book_b, _snapshot = two_candidate_evaluation(
        tmp_path / "eval"
    )
    assert candidates.publishable is True

    publication, books_root, archive = publish(tmp_path, candidates)

    assert publication.committed is True
    assert publication.published_replica_ids == ("product-a-1", "product-b-1")
    for candidate in candidates.candidates:
        expected = dumps_for(candidate)
        live = books_root / candidate.replica_id
        assert (live / "portfolio.json").read_text(encoding="utf-8") == expected["portfolio"]
        assert (live / "fills.json").read_text(encoding="utf-8") == expected["fills"]
        assert (live / "events.jsonl").read_text(encoding="utf-8") == expected["events"]
    assert book_a.positions == ()
    assert book_b.positions == ()

    events = [
        parse_audit_event(line).event_type
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events == ["commit_started", "commit_completed"]


def test_replay_from_committed_archive_reproduces_books_and_events(
    tmp_path: Path,
) -> None:
    candidates, _collection, _book_a, _book_b, _snapshot = two_candidate_evaluation(
        tmp_path / "eval"
    )
    publication, books_root, _archive = publish(tmp_path, candidates)

    reconstructed = reconstruct_published_round(books_root, candidates.round_id)

    assert publication.committed_root is not None
    assert reconstructed == {
        candidate.replica_id: dumps_for(candidate)
        for candidate in candidates.candidates
    }
    for replica_id, payload in reconstructed.items():
        live = books_root / replica_id
        assert (live / "portfolio.json").read_text(encoding="utf-8") == payload["portfolio"]
        assert (live / "events.jsonl").read_text(encoding="utf-8") == payload["events"]
