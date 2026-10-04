"""RendererPort over fpdf2 (owner, BD-40): the report's HTML to PDF in pure Python, so no
system libraries are needed on Render, in CI or on Windows. The DejaVu fonts (bundled,
open licence: `fonts/LICENSE-DejaVu.txt`) cover every script a source may use. fpdf2
reads a plain subset of HTML (headings, paragraphs, lists, links, tables, bold), which
is what the report template writes."""

import asyncio
from pathlib import Path

from fpdf import FPDF, FontFace

from app.settings import Settings

FONTS = Path(__file__).resolve().parent / "fonts"
FAMILY = "DejaVu"
# Italic uses the upright faces: the report needs emphasis rarely, and two more files
# would only slant it
FACES = {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf", "I": "DejaVuSans.ttf",
         "BI": "DejaVuSans-Bold.ttf"}  # fmt: skip


INK = "#1f2937"  # headings in a dark neutral, not fpdf2's default red
HEADINGS = {
    "h1": FontFace(color=INK, size_pt=20, emphasis="BOLD"),
    "h2": FontFace(color=INK, size_pt=15, emphasis="BOLD"),
    "h3": FontFace(color=INK, size_pt=12, emphasis="BOLD"),
}


class Fpdf2Renderer:
    def __init__(self, font_size: float = 10.0) -> None:
        self._size = font_size

    def _render(self, html: str) -> bytes:
        pdf = FPDF(format="A4")
        pdf.set_margins(18, 18, 18)
        pdf.set_auto_page_break(auto=True, margin=18)
        for style, name in FACES.items():
            pdf.add_font(FAMILY, style, str(FONTS / name))
        pdf.set_font(FAMILY, size=self._size)
        pdf.add_page()
        pdf.write_html(html, font_family=FAMILY, tag_styles=HEADINGS)
        return bytes(pdf.output())

    async def to_pdf(self, html: str) -> bytes:
        # Laying out pages takes a moment: off the event loop (BD-27)
        return await asyncio.to_thread(self._render, html)


def make(settings: Settings) -> Fpdf2Renderer:
    return Fpdf2Renderer()
