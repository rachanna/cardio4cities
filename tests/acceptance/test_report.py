"""AT-18: the downloaded report has citations for every fact, flags and a gaps section
(R-17; D3-3, BD-40). Built from the thin slice's real stores with a scripted reporter
model; the PDF comes from the real fpdf2 renderer. Fictional Halden Bay, Norvania."""

import io
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pdfplumber
import pytest

from app.adapters.renderer.fpdf2 import Fpdf2Renderer
from app.api.auth import COOKIE_NAME, AccessConfig, issue_token
from app.container import Container
from app.main import create_app
from app.prompts.reporter.schema import (
    AnalysisOutput,
    AnalysisPoint,
    DimensionIntro,
    ReportSentence,
)
from tests.acceptance.test_read_api import SECRET
from tests.support.thin_slice import NEARBY_STATEMENT, NEW_GOV_STATEMENT, TRUE_STATEMENT, Slice
from tests.support.workflow_fakes import ScriptedLLM

pytestmark = [pytest.mark.db, pytest.mark.stores]
_REF = re.compile(r"\[(clm_\w+)\]")
INTRO = (
    "This section gathers what the sources confirm about the city, with every figure and"
    " statement cited to the source it comes from below."
)


@dataclass
class Reporter:
    """Cites the first fact of each section; its analysis adds one good point and one
    with an invented number, which the post-check must drop."""

    calls: list[str] = field(default_factory=list)

    def __call__(self, user: str) -> Any:
        self.calls.append(user)
        refs = _REF.findall(user)
        if "Write up to" in user:  # the analysis
            return AnalysisOutput(
                points=[
                    AnalysisPoint(
                        text="City figures exist for hypertension control.",
                        derived_from=refs[:1],
                        kind="opportunity",
                    ),
                    AnalysisPoint(
                        text="About 64% of clinics lack staff.", derived_from=refs[:1], kind="risk"
                    ),
                ]
            )
        sentences = (
            [
                ReportSentence(
                    text=INTRO,
                    refs=refs[:1],
                    kind="fact",
                )
            ]
            if refs
            else []
        )
        return DimensionIntro(sentences=sentences)


@dataclass
class Downloader:
    client: httpx.AsyncClient
    slice: Slice
    reporter: Reporter

    async def get(self, fmt: str) -> httpx.Response:
        response = await self.client.get(
            f"/api/v1/cities/{self.slice.city_id}/report", params={"format": fmt}
        )
        assert response.status_code == 200, response.text
        return response


@pytest.fixture
async def downloads(thin_slice: Slice) -> AsyncIterator[Downloader]:
    assert thin_slice.ports is not None
    reporter = Reporter()
    app = create_app(env_file=None)
    app.state.container = Container(
        settings=thin_slice.settings,
        relational=thin_slice.store,
        graph=thin_slice.graph,
        llm={"anthropic": ScriptedLLM("anthropic", {"reporter": reporter})},
        snapshots=thin_slice.ports.snapshots,
        renderer=Fpdf2Renderer(),
    )
    app.state.access = AccessConfig("a" * 12, "b" * 12, SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, issue_token("viewer", SECRET))
        yield Downloader(client, thin_slice, reporter)


def sources_cited(text: str) -> tuple[set[int], int]:
    """(citation numbers used, number of sources listed)."""
    used = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    listed = len(
        re.findall(r"^\d+\. ", text.split("## Sources")[1].split("## Run details")[0], re.M)
    )
    return used, listed


async def test_every_fact_is_cited_and_flagged_and_the_gaps_are_listed(
    downloads: Downloader,
) -> None:
    """AT-18 on the Markdown download."""
    md = (await downloads.get("md")).text
    for statement in (TRUE_STATEMENT, NEARBY_STATEMENT, NEW_GOV_STATEMENT):
        line = next(x for x in md.splitlines() if statement in x)
        assert re.search(r"\[\d+\]", line), line  # cited
    assert "Not city-level" in next(x for x in md.splitlines() if NEARBY_STATEMENT in x)  # flagged
    used, listed = sources_cited(md)
    assert used == set(range(1, listed + 1))  # every number points at a listed source
    assert "## What we could not find" in md
    assert "## Handle with care" in md
    assert "## Run details" in md
    assert downloads.slice.run_id in md


async def test_the_model_prose_is_post_checked(downloads: Downloader) -> None:
    """HD-07: an analysis point with a number its facts do not hold is dropped."""
    md = (await downloads.get("md")).text
    assert "City figures exist for hypertension control." in md
    assert "64%" not in md
    assert "This section gathers what the sources confirm" in md  # the introductions


async def test_the_pdf_and_html_hold_the_same_report(downloads: Downloader) -> None:
    pdf = await downloads.get("pdf")
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    assert re.fullmatch(
        r'attachment; filename="halden-bay-research-\d{4}-\d{2}-\d{2}\.pdf"',
        pdf.headers["content-disposition"],
    )
    with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
        text = " ".join((page.extract_text() or "") for page in doc.pages)
    assert "What we could not find" in text
    assert "Sources" in text
    assert "31.5%" in text
    html = (await downloads.get("html")).text
    assert html.startswith("<!doctype html>")
    assert "Not city-level" in html


async def test_the_report_is_generated_once_per_run(downloads: Downloader) -> None:
    """The three formats are written together; later downloads serve the stored copy."""
    await downloads.get("md")
    calls = len(downloads.reporter.calls)
    assert calls > 0
    await downloads.get("pdf")
    await downloads.get("html")
    await downloads.get("md")
    assert len(downloads.reporter.calls) == calls


async def test_a_report_needs_a_session_and_a_researched_city(downloads: Downloader) -> None:
    response = await downloads.client.get("/api/v1/cities/city_unknown/report")
    assert response.status_code == 404
    downloads.client.cookies.clear()
    response = await downloads.client.get(f"/api/v1/cities/{downloads.slice.city_id}/report")
    assert response.status_code == 401


async def test_the_layout_leads_with_an_overview_and_states_each_gap_once(
    downloads: Downloader,
) -> None:
    """D4-3 layout: a cover table and coverage overview first; questions as plain words,
    not internal codes; a not-found gap note once, in "What we could not find"."""
    md = (await downloads.get("md")).text
    assert md.index("## At a glance") < md.index("## Findings by area")
    assert "### Coverage by area" in md
    assert "| **All questions** |" in md
    assert not re.search(r"^#+ (D\d|S\d\d) ", md, re.M)  # no internal codes in headings
    not_found = [line for line in md.splitlines() if "nothing acceptable found" in line]
    for line in not_found:
        note = line.split("|")[-2].strip()
        assert md.count(note) == 1, note  # stated once, not in every section again


async def test_the_reporter_introduces_only_areas_with_findings(downloads: Downloader) -> None:
    """D4-3: an area with no confirmed finding gets a sentence written by code, never model
    prose with nothing to rest on."""
    await downloads.get("md")
    intros = [c for c in downloads.reporter.calls if "Write the introduction" in c]
    assert intros
    for message in intros:
        facts = message.split("facts in this section:\n")[1].split("\ngaps in this section")[0]
        assert facts != "- none"
