"""Every claim status change goes through `claim_index.set_status`, so the retrieval
indexes always follow Postgres (CHG-01, LLD-5 §4.2, AT-39 plumbing)."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "app" / "workflow"


def test_only_the_claim_index_module_writes_claim_status() -> None:
    writers = [
        p.relative_to(WORKFLOW).as_posix()
        for p in WORKFLOW.rglob("*.py")
        if "set_claim_status(" in p.read_text(encoding="utf-8")
    ]
    assert writers == ["claim_index.py"]
