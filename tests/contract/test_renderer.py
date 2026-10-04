"""RendererPort (AT-35; D3-3, BD-40): HTML in, a PDF whose text can be read back out,
in any script the sources use. One adapter: fpdf2."""

import io

import pdfplumber

from app.adapters.renderer.fpdf2 import Fpdf2Renderer

HTML = (
    "<h1>Halden Bay: cardiovascular research brief</h1>"
    "<p>31.2% of adults [1] (Not city-level). São, ≥140/90 mmHg, “quoted”, Ελληνικά.</p>"
    "<ul><li>One</li><li>Two</li></ul>"
    '<ol><li><a href="https://health.halden-bay.test/x">Survey</a></li></ol>'
)


async def test_html_becomes_a_pdf_with_its_text() -> None:
    pdf = await Fpdf2Renderer().to_pdf(HTML)
    assert pdf.startswith(b"%PDF")
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = doc.pages[0].extract_text() or ""
    for part in (
        "Halden Bay: cardiovascular research brief",
        "31.2% of adults [1]",
        "São",
        "≥140/90",
        "Ελληνικά",
    ):
        assert part in text
