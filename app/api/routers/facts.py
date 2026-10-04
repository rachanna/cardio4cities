"""Evidence for one fact and the preserved snapshot of its source (LLD-4 §3.3, LLD-1 §7.1;
AT-12, AT-27). Any stored claim can be inspected: a rejected one is labelled "Reported, not
confirmed", so the panel can see what was turned away and why (DS-3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api import reading
from app.api.auth import Session, current_session
from app.api.errors import ApiError, dependency_unavailable
from app.api.schemas import (
    ConsistencyOut,
    EvidenceResponse,
    Passage,
    SnapshotOut,
    VerdictOut,
)
from app.ports.snapshots import SnapshotPort

router = APIRouter(tags=["facts"])
SessionDep = Annotated[Session, Depends(current_session)]
# A stored page is shown, never run: no scripts, nothing fetched from it
SNAPSHOT_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
CONTEXT_CHARS = 300  # each side of the quote: up to 600 characters of context (LLD-4 §3.3)


@router.get("/facts/{claim_id}/evidence", response_model=EvidenceResponse)
async def evidence(claim_id: str, request: Request, _: SessionDep) -> EvidenceResponse:
    store = reading.relational(request)
    fact = await store.research.stored_fact(claim_id)
    if fact is None:
        raise ApiError(404, "not_found", "That claim does not exist.")
    maker = await reading.card_maker(request)
    claim = fact.claim
    start = max(claim.span_start - CONTEXT_CHARS, 0)
    window = await store.research.source_text(
        claim.source_id, start, claim.span_end + CONTEXT_CHARS
    )
    passage = None
    if window is not None:
        passage = Passage(
            text=window,
            highlight_start=claim.span_start - start,
            highlight_end=min(claim.span_end - start, len(window)),
        )
    label_passages = {}
    for kind, (a, b) in claim.label_spans.items():  # stated outside the quote (BD-10)
        found = await store.research.source_text(claim.source_id, a, b)
        if found:
            label_passages[kind] = found
    snapshot = await store.sources.snapshot_ref(claim.source_id)
    consistency = await store.research.consistency(claim_id)
    verdict = fact.verdict
    return EvidenceResponse(
        card=maker.card(fact),
        quote=claim.quote,
        quote_lang=claim.quote_lang,
        quote_translation=claim.quote_translation,
        passage=passage,
        label_passages=label_passages,
        geography_fit=claim.geography_fit.model_dump(mode="json") if claim.geography_fit else None,
        verdict=VerdictOut(
            label=verdict.label.value,
            rationale=verdict.rationale,
            model=verdict.verifier_model,
            fallback_used=verdict.fallback_used,
            checker_prompt=verdict.prompt_version,
        )
        if verdict
        else None,
        snapshot=SnapshotOut(
            sha256=snapshot.sha256,
            size_bytes=snapshot.size_bytes,
            content_type=snapshot.content_type,
            url=f"/api/v1/snapshots/{claim.source_id}",
        )
        if snapshot
        else None,
        consistency=ConsistencyOut(
            outcome=consistency["outcome"],
            compared_with=list(consistency["compared_with"]),
            reason=consistency["reason"],
        )
        if consistency
        else None,
    )


@router.get("/snapshots/{source_id}")
async def snapshot(source_id: str, request: Request, _: SessionDep) -> Response:
    """The bytes as retrieved, whatever the live page says now (R-55, AT-27)."""
    ref = await reading.relational(request).sources.snapshot_ref(source_id)
    if ref is None:
        raise ApiError(404, "not_found", "No snapshot is stored for that source.")
    snapshots: SnapshotPort | None = request.app.state.container.snapshots
    if snapshots is None:
        raise dependency_unavailable("postgres", "The snapshot store is not available.")
    content, content_type = await snapshots.get(source_id)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "X-Snapshot-SHA256": ref.sha256,
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": SNAPSHOT_CSP,
        },
    )
