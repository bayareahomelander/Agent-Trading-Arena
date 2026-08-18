from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")
