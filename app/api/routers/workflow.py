"""The workflow as a diagram (LLD-4 §3.5, AT-03, DS-2): Mermaid text generated from the
compiled graphs, so what the panel sees is what runs."""

from functools import cache
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth import Session, current_session
from app.api.schemas import DiagramResponse
from app.workflow.graph import build_graph, build_slot_graph

router = APIRouter(tags=["workflow"])
SessionDep = Annotated[Session, Depends(current_session)]


@cache
def _diagrams() -> DiagramResponse:
    return DiagramResponse(
        main=build_graph().get_graph(xray=1).draw_mermaid(),
        slot=build_slot_graph().get_graph().draw_mermaid(),
    )


@router.get("/workflow/diagram", response_model=DiagramResponse)
async def diagram(_: SessionDep) -> DiagramResponse:
    return _diagrams()
