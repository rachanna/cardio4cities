"""Questions about a researched city (LLD-4 §3.4, LLD-5; D3-2). Answers come only from
confirmed facts of the city's latest run, checked by code before they are returned, and
are stored with their retrieval trace (AT-46). The graph switch is for admins (R-88)."""

import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api import reading
from app.api.asking import ask_deps
from app.api.auth import COOKIE_NAME, Session, admin_session, current_session
from app.api.errors import ApiError, dependency_unavailable
from app.api.limits import FailureLimiter
from app.api.schemas import AnswerSentenceOut, AnswerTraceResponse, AskRequest, AskResponse
from app.ports.errors import PortError
from app.query.pipeline import answer_question
from app.workflow.budget import BudgetExhaustedError
from app.workflow.ids import new_id

log = logging.getLogger(__name__)
router = APIRouter(tags=["questions"])
SessionDep = Annotated[Session, Depends(current_session)]
AdminDep = Annotated[Session, Depends(admin_session)]
ASK_WINDOW_S = 60.0  # limits.ask_per_min is per minute (LLD-4 §5.1)


def _ask_limiter(request: Request) -> FailureLimiter:
    limiter: FailureLimiter | None = getattr(request.app.state, "ask_limiter", None)
    if limiter is None:
        per_min = request.app.state.container.settings.config.limits.ask_per_min
        limiter = request.app.state.ask_limiter = FailureLimiter(per_min, ASK_WINDOW_S)
    return limiter


@router.post("/cities/{city_id}/ask", response_model=AskResponse)
async def ask(city_id: str, body: AskRequest, request: Request, session: SessionDep) -> AskResponse:
    if body.options.graph == "off" and session.role != "admin":
        raise ApiError(
            403, "forbidden", "Switching the knowledge graph off is for the presenter only."
        )
    # One session's questions per minute (limits.ask_per_min): keyed by the session itself
    key = hashlib.sha256(request.cookies.get(COOKIE_NAME, "").encode()).hexdigest()
    limiter = _ask_limiter(request)
    if limiter.blocked(key):
        raise ApiError(429, "rate_limited", "Too many questions. Wait a minute, then ask again.")
    limiter.record_failure(key)  # counts every question, answered or not

    row = await reading.city(request, city_id)
    store = reading.relational(request)
    previous = None
    turn = 1
    conversation_id = body.conversation_id or new_id("conv")
    if body.conversation_id:
        last = await store.answers.last_turn(body.conversation_id)
        if last is None or last["city_id"] != city_id:
            raise ApiError(
                404, "conversation_not_found", "That conversation is not about this city."
            )
        previous, turn = last["classification"], int(last["turn"]) + 1

    deps = await ask_deps(request, row, graph_on=body.options.graph == "on")
    try:
        outcome = await answer_question(deps, body.question, previous)
    except (PortError, BudgetExhaustedError) as exc:
        log.warning("ask: answering failed (%s)", type(exc).__name__)
        raise dependency_unavailable(
            "llm", "Answering is not available right now. Try again."
        ) from exc

    answer_id = new_id("ans")
    sentences = [
        AnswerSentenceOut(
            text=s.text, kind=s.kind, refs=s.refs, main_badge=s.main_badge,
            status_word=s.status_word, slot_id=s.slot_id,
        )
        for s in outcome.sentences
    ]  # fmt: skip
    trace = {**outcome.trace, "budget": deps.ledger.snapshot()}  # type: ignore[attr-defined]
    await store.answers.add_answer(
        {
            "answer_id": answer_id,
            "city_id": city_id,
            "run_id": deps.run_id,
            "question": body.question,
            "question_type": outcome.question_type,
            "body": {"sentences": [s.model_dump(mode="json") for s in sentences]},
            "cited_claim_ids": outcome.cited,
            "graph_used": outcome.graph_used,
            "models": outcome.models,
            "conversation_id": conversation_id,
            "turn": turn,
            "trace": trace,
        }
    )
    return AskResponse(
        answer_id=answer_id,
        question_type=outcome.question_type,
        sentences=sentences,
        graph_used=outcome.graph_used,
        run_id=deps.run_id,
        conversation_id=conversation_id,
        turn=turn,
        trace=trace if session.role == "admin" else None,
    )


@router.get("/admin/answers/{answer_id}/trace", response_model=AnswerTraceResponse)
async def answer_trace(answer_id: str, request: Request, _: AdminDep) -> AnswerTraceResponse:
    """The stored retrieval trace of one answer (LLD-5 §10; DS-5 "why this answer")."""
    row = await reading.relational(request).answers.answer_row(answer_id)
    if row is None:
        raise ApiError(404, "not_found", "That answer does not exist.")
    return AnswerTraceResponse(answer_id=answer_id, question=row["question"], trace=row["trace"])
