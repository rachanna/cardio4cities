"""The downloadable report (LLD-4 §3.4, R-17, AT-18; D3-3). Generated on the first request
for a run, in all three formats at once, so the linking prose is written once; later
requests serve the stored copy."""

import asyncio
import re
import unicodedata
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api import reading
from app.api.auth import Session, current_session
from app.api.errors import dependency_unavailable
from app.api.reporting import build
from app.ports.renderer import RendererPort
from app.workflow.ids import new_id

router = APIRouter(tags=["reports"])
SessionDep = Annotated[Session, Depends(current_session)]
Format = Literal["md", "html", "pdf"]
MEDIA = {
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}


def filename(city_name: str, when: str, fmt: str) -> str:
    """`<city>-research-<date>.<ext>` in plain ASCII (LLD-4 §3.4)."""
    plain = unicodedata.normalize("NFKD", city_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.casefold()).strip("-") or "city"
    return f"{slug}-research-{when}.{fmt}"


def _locks(request: Request) -> dict[str, asyncio.Lock]:
    locks: dict[str, asyncio.Lock] | None = getattr(request.app.state, "report_locks", None)
    if locks is None:
        locks = request.app.state.report_locks = {}
    return locks


@router.get("/cities/{city_id}/report")
async def report(
    city_id: str,
    request: Request,
    _: SessionDep,
    format: Annotated[Format, Query()] = "pdf",
) -> Response:
    row = await reading.city(request, city_id)
    store = reading.relational(request)
    run_id = str(row["latest_run_id"])
    content = await store.reports.report(run_id, format)
    if content is None:
        # One generation per run, however many downloads arrive together
        async with _locks(request).setdefault(run_id, asyncio.Lock()):
            content = await store.reports.report(run_id, format)
            if content is None:
                content = await _generate(request, row, format)
    when = (row["latest_run_at"] or row["latest_run_started"]).date().isoformat()
    name = filename(str(row["identity"]["name"]), when, format)
    return Response(
        content=content,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


async def _generate(request: Request, row: dict[str, object], fmt: str) -> bytes:
    store = reading.relational(request)
    renderer: RendererPort | None = request.app.state.container.renderer
    built = await build(request, row)
    outputs = {"md": built.markdown, "html": built.html}
    if renderer is not None:
        outputs["pdf"] = await renderer.to_pdf(built.pdf_html)
    elif fmt == "pdf":
        raise dependency_unavailable("renderer", "PDF reports are not available right now.")
    for kind, content in outputs.items():
        await store.reports.add_report(
            new_id("rep"), str(row["city_id"]), str(row["latest_run_id"]), kind, content
        )
    return outputs[fmt]
